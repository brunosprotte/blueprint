"""Router de reviews — implementado na fase F6.

Duas rotas (design master §17, "Reviews e commits"):

  - `POST /api/reviews`       — review de commit (fluxo do hook, §13)
  - `GET  /api/reviews?demand=` — reviews da demanda, mais recente primeiro

`reviews.commit_id` é FK NOT NULL para `commits`: toda review de commit
precisa de uma linha em `commits` (spec D7). O F4 é dono de
`app/services/commits.py`; enquanto ele não existir, o F6 faz o INSERT no
**único** ponto de troca (`_resolve_commit_id`).

O corpo aceito é o do **kit** (Contrato Comum §4.2 b): `sha` e `demand_id`
são obrigatórios; `verdict` e `findings` são extras — quando faltam, a
review nasce `pending` (não houve veredito de revisor).

Erros usam o envelope único do Contrato Comum §3:
`{"error": {"code": ..., "message": ..., "detail": {}}}`.
"""

from __future__ import annotations

import json
import uuid as _uuid
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import require_scope, require_user
from app.db import get_pool
from app.services.doubts import as_uuid, to_iso

router = APIRouter()

__all__ = ["router"]

_VERDICTS = "^(clean|suggestions|blocking|pending)$"
_SEVERITIES = "^(blocking|suggestion|deferred)$"


# --------------------------------------------------------------------------
# Body
# --------------------------------------------------------------------------


class FindingIn(BaseModel):
    """Achado de revisão, no formato do contrato §7.4."""

    severity: str = Field(pattern=_SEVERITIES)
    title: str
    detail: str = ""
    ac: str = ""
    suggestion: str = ""


class ReviewIn(BaseModel):
    """Body de `POST /api/reviews` (spec §5.9 + Contrato Comum §4.2 b)."""

    sha: str = Field(min_length=1)
    demand_id: str = Field(min_length=1)
    verdict: str = Field(default="pending", pattern=_VERDICTS)
    findings: list[FindingIn] = Field(default_factory=list)
    message: str | None = None
    branch: str | None = None
    author: str | None = None
    files: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# SQL
# --------------------------------------------------------------------------

_SQL_DEMAND = """
SELECT id, status, repo_id, title
  FROM demands
 WHERE id = $1
"""

_SQL_FIND_COMMIT = """
SELECT id FROM commits
 WHERE repo_id = $1 AND sha = $2
"""

_SQL_INSERT_COMMIT = """
INSERT INTO commits (demand_id, repo_id, sha, message, branch, author, files)
VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
ON CONFLICT (repo_id, sha) DO NOTHING
RETURNING id
"""

_SQL_INSERT_REVIEW = """
INSERT INTO reviews (commit_id, demand_id, verdict, findings, created_at)
VALUES ($1, $2, $3, $4::jsonb, clock_timestamp())
RETURNING id, commit_id, demand_id, verdict, findings, created_at
"""

_SQL_LIST_REVIEWS = """
SELECT r.id, r.commit_id, r.demand_id, r.verdict, r.findings, r.created_at, c.sha
  FROM reviews r
  JOIN commits c ON c.id = r.commit_id
 WHERE r.demand_id = $1
 ORDER BY r.created_at DESC, r.id DESC
"""

_SQL_EVENT = """
INSERT INTO events (demand_id, artifact_id, type, payload, actor, at)
VALUES ($1, $2, $3, $4::jsonb, $5, now())
"""

#: Transições de demanda que o F6 provoca (design master §9.1).
_DEMAND_TRANSITIONS = {
    "in_progress": ("review",),
    "review": ("in_progress",),
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _error(status_code: int, code: str, message: str, detail: dict | None = None):
    """Envelope único de erro (Contrato Comum §3)."""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "detail": detail or {}}},
    )


def _field(row: Any, name: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(name, default)
    value = getattr(row, name, None)
    if value is not None:
        return value
    try:
        return row[name]
    except Exception:
        return default


def _json(value: Any) -> Any:
    """asyncpg devolve `jsonb` como texto."""
    if isinstance(value, (str, bytes)):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return value
    return value


def _parse_uuid(value: Any) -> _uuid.UUID | None:
    """Uuid válido ou `None` — id malformado é recurso inexistente (404)."""
    try:
        return _uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return None


async def _resolve_commit_id(conn: Any, demand: Any, payload: ReviewIn) -> str:
    """Garante a linha em `commits` (D7) e devolve o `commit_id`.

    Idempotente por `(repo_id, sha)` — o mesmo par é o índice único
    `commits_repo_sha_uniq` (Contrato Comum §4.3).

    O F4 é dono de `app/services/commits.py`, mas o contrato dele
    (`record_commit(pool, *, repo, sha, ..., files: list[dict])`, F4 §3.5) é
    incompatível com o payload do kit (`repo_id`, `files` como lista de
    strings). O F6 fica, portanto, no **ponto único de troca** que a D7
    autoriza: o INSERT direto.
    """
    demand_id = as_uuid(_field(demand, "id"))
    repo_id = as_uuid(_field(demand, "repo_id"))
    row = await conn.fetchrow(_SQL_FIND_COMMIT, repo_id, payload.sha)
    if row is not None:
        return str(_field(row, "id"))
    row = await conn.fetchrow(
        _SQL_INSERT_COMMIT,
        demand_id,
        repo_id,
        payload.sha,
        payload.message,
        payload.branch,
        payload.author,
        json.dumps(list(payload.files)),
    )
    if row is None:
        # Corrida: outro POST gravou o mesmo (repo_id, sha) entre o SELECT e o INSERT.
        row = await conn.fetchrow(_SQL_FIND_COMMIT, repo_id, payload.sha)
    if row is None:
        raise RuntimeError("INSERT em commits não retornou linha")
    return str(_field(row, "id"))


def _target_transition(current: str, verdict: str) -> str | None:
    """Estado-alvo da demanda, ou `None` quando nenhuma transição cabe.

    - `in_progress -> review`  (gatilho: commit reportada)
    - `review -> in_progress`  (verdict = blocking)

    Demanda em outro estado: nenhuma transição (revisão pode chegar fora de
    ordem) — não é erro.
    """
    if current == "in_progress":
        return "review"
    if current == "review" and verdict == "blocking":
        return "in_progress"
    return None


class _TransitionError(Exception):
    """Erro do lifecycle (F4) mapeado para o envelope da API."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        detail: dict | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.detail = detail or {}


async def _transition_demand(
    conn: Any, demand: Any, verdict: str, actor_id: str | None
) -> str:
    """Transição da demanda via `lifecycle` do F4 (invariante 2).

    Devolve o estado final da demanda. Sem o F4 pronto, nenhuma transição é
    aplicada — o lifecycle é o **único** caminho para escrever status
    (design master §7.1), e o F6 não escreve status por fora dele.

    A transição roda **na transação do chamador**: se ela for ilegal, tudo
    que foi gravado antes (commit + review) volta atrás.
    """
    from app.services.reviewers import call_lifecycle_transition

    demand_id = str(_field(demand, "id"))
    current = _field(demand, "status")
    target = _target_transition(current, verdict)
    if target is None:
        return current

    try:
        applied = await call_lifecycle_transition(
            "apply_demand_transition", demand_id, target, actor_id, conn=conn
        )
    except Exception as exc:  # noqa: BLE001 — erro do F4 vira erro de API
        if getattr(exc, "code", None) == "illegal_transition":
            raise _TransitionError(
                409,
                "illegal_transition",
                str(exc),
                {
                    "entity": getattr(exc, "entity", "demand"),
                    "current": getattr(exc, "current", current),
                    "target": getattr(exc, "target", target),
                },
            ) from exc
        status = getattr(exc, "status", None)
        if isinstance(status, int):
            raise _TransitionError(
                status, getattr(exc, "code", "error"), str(exc)
            ) from exc
        return current
    return target if applied else current


# --------------------------------------------------------------------------
# Rotas
# --------------------------------------------------------------------------


@router.post("/reviews")
async def create_review(
    payload: ReviewIn,
    user=Depends(require_user),
    token=Depends(require_scope("review:write")),
):
    """Registra a review de um commit e transiciona a demanda."""
    pool = await get_pool()

    demand_uuid = _parse_uuid(payload.demand_id)
    if demand_uuid is None:
        return _error(
            404,
            "not_found",
            f"demanda {payload.demand_id} não existe",
            {"demand_id": payload.demand_id},
        )

    demand = await pool.fetchrow(_SQL_DEMAND, demand_uuid)
    if demand is None:
        return _error(
            404,
            "not_found",
            f"demanda {payload.demand_id} não existe",
            {"demand_id": payload.demand_id},
        )

    findings = [
        {
            "severity": f.severity,
            "title": f.title,
            "detail": f.detail,
            "ac": f.ac,
            "suggestion": f.suggestion,
        }
        for f in payload.findings
    ]

    # Commit + review + transição + evento: **uma transação só**. Transição
    # ilegal devolve 409 e não deixa estado parcial (AGENT-BRIEF).
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                commit_id = await _resolve_commit_id(conn, demand, payload)
                row = await conn.fetchrow(
                    _SQL_INSERT_REVIEW,
                    commit_id,
                    demand_uuid,
                    payload.verdict,
                    json.dumps(findings, ensure_ascii=False),
                )
                if row is None:
                    raise RuntimeError("INSERT em reviews não retornou linha")
                review_id = str(_field(row, "id"))

                demand_status = await _transition_demand(
                    conn, demand, payload.verdict, getattr(user, "id", None)
                )

                await conn.execute(
                    _SQL_EVENT,
                    demand_uuid,
                    None,
                    "review_reported",
                    json.dumps(
                        {
                            "review_id": review_id,
                            "commit_id": commit_id,
                            "sha": payload.sha,
                            "verdict": payload.verdict,
                            "findings": len(findings),
                            "demand_status": demand_status,
                        },
                        ensure_ascii=False,
                    ),
                    as_uuid(getattr(user, "id", None)),
                )
    except _TransitionError as exc:
        return _error(exc.status, exc.code, exc.message, exc.detail)

    return JSONResponse(
        status_code=201,
        content={
            "review_id": review_id,
            "commit_id": commit_id,
            "demand_id": payload.demand_id,
            "sha": payload.sha,
            "verdict": payload.verdict,
            "findings": findings,
            "demand_status": demand_status,
            "created_at": to_iso(_field(row, "created_at")),
        },
    )


@router.get("/reviews")
async def list_reviews(
    demand: str | None = None,
    user=Depends(require_user),
):
    """Reviews da demanda, mais recente primeiro."""
    if not demand:
        return _error(
            400,
            "missing_parameter",
            "parâmetro 'demand' é obrigatório",
            {"parameter": "demand"},
        )

    pool = await get_pool()
    demand_uuid = _parse_uuid(demand)
    demand_row = None
    if demand_uuid is not None:
        demand_row = await pool.fetchrow(_SQL_DEMAND, demand_uuid)
    if demand_row is None:
        return _error(
            404,
            "not_found",
            f"demanda {demand} não existe",
            {"demand_id": demand},
        )

    rows = await pool.fetch(_SQL_LIST_REVIEWS, demand_uuid)
    reviews = [
        {
            "id": str(_field(row, "id")),
            "commit_id": str(_field(row, "commit_id")),
            "sha": _field(row, "sha"),
            "verdict": _field(row, "verdict"),
            "findings": _json(_field(row, "findings")) or [],
            "created_at": to_iso(_field(row, "created_at")),
        }
        for row in rows
    ]
    return {"demand_id": demand, "reviews": reviews}
