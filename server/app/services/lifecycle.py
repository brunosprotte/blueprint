"""Ciclo de vida — máquina de estados de demandas e artefatos. F4.

Dona única de qualquer escrita de `status` (invariante 2 do design master §7.1).
Fornece também o envelope de erro canônico do contrato (§3) — os routers de F4
não usam `HTTPException`.
"""

from __future__ import annotations

import inspect
import json
import uuid as _uuid
from functools import wraps
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

DEMAND_STATUSES = ("open", "claimed", "in_progress", "review", "merged", "done", "blocked")
ARTIFACT_STATUSES = ("draft", "pending", "on user review", "on agents review", "approved", "stable")

DEMAND_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "open": ("claimed", "blocked"),
    "claimed": ("in_progress", "open", "blocked"),
    "in_progress": ("review", "blocked"),
    "review": ("in_progress", "merged", "blocked"),
    "merged": ("done", "blocked"),
    "done": ("blocked",),
    "blocked": ("open",),
}

ARTIFACT_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft": ("pending",),
    "pending": ("on user review",),
    "on user review": ("on agents review",),
    "on agents review": ("approved",),
    "approved": ("stable",),
    "stable": (),
}

_TRANSITIONS: dict[str, dict[str, tuple[str, ...]]] = {
    "demand": DEMAND_TRANSITIONS,
    "artifact": ARTIFACT_TRANSITIONS,
}

# `events.type` — nomenclatura `<entidade>.<ação>` (spec §5.9).
DEMAND_EVENTS: dict[tuple[str, str], str] = {
    ("open", "claimed"): "demand.claimed",
    ("claimed", "in_progress"): "demand.started",
    ("review", "merged"): "demand.merged",
    ("merged", "done"): "demand.closed",
    ("claimed", "open"): "demand.released",
    ("blocked", "open"): "demand.released",
}

ARTIFACT_EVENTS: dict[tuple[str, str], str] = {
    ("draft", "pending"): "artifact.promoted",
    ("pending", "on user review"): "artifact.review_requested",
    ("on user review", "on agents review"): "artifact.agents_review_started",
    ("on agents review", "approved"): "artifact.approved",
    ("approved", "stable"): "artifact.stabilized",
}


class IllegalTransition(Exception):
    """Transição fora da tabela de estados — HTTP 409."""

    code = "illegal_transition"
    http_status = 409

    def __init__(self, entity: str, current: str, target: str):
        self.entity = entity
        self.current = current
        self.target = target
        self.message = f"{current} -> {target}"
        super().__init__(self.message)


class ApiError(Exception):
    """Erro de API no envelope canônico do contrato §3."""

    def __init__(self, code: str, message: str, status: int = 400, detail: dict | None = None):
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail or {}
        super().__init__(message)


def error_payload(code: str, message: str, detail: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "detail": detail or {}}}


def error_response(err: ApiError) -> JSONResponse:
    return JSONResponse(status_code=err.status, content=error_payload(err.code, err.message, err.detail))


def illegal_transition_error(err: IllegalTransition) -> ApiError:
    """`IllegalTransition` → `ApiError` 409 no envelope canônico."""
    return ApiError(
        err.code,
        err.message,
        err.http_status,
        {"entity": err.entity, "current": err.current, "target": err.target},
    )


def http_error_code(status: int) -> str:
    """Código canônico para um `HTTPException` herdado do core (F1)."""
    return {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
    }.get(status, "error")


def api_route(func):
    """Envolve o handler e devolve o envelope canônico em qualquer erro do F4.

    Erros de auth que chegam pelo corpo do handler (ex.: `current_repo`) também
    são convertidos; erros levantados por *dependências* do core (F1) ficam por
    conta do handler global de `HTTPException` do `main.py`.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except ApiError as exc:
            return error_response(exc)
        except IllegalTransition as exc:
            return error_response(illegal_transition_error(exc))
        except HTTPException as exc:
            return error_response(
                ApiError(http_error_code(exc.status_code), str(exc.detail), exc.status_code)
            )

    return wrapper


def can_transition(table: str, current: str, target: str) -> bool:
    """`False` para table/current/target inválidos — nunca levanta."""
    transitions = _TRANSITIONS.get(table)
    if transitions is None:
        return False
    allowed = transitions.get(current)
    if allowed is None:
        return False
    return target in allowed


def allowed_targets(table: str, current: str) -> list[str]:
    transitions = _TRANSITIONS.get(table) or {}
    return list(transitions.get(current, ()))


def as_uuid(value: Any) -> Any:
    """asyncpg exige `uuid.UUID` (não `str`) em coluna uuid."""
    if isinstance(value, str):
        return _uuid.UUID(value)
    return value


def split_repo(repo: str) -> tuple[str, str]:
    """`owner/name` → `(owner, name)`. 400 se malformado."""
    owner, separator, name = (repo or "").partition("/")
    if not separator or not owner or not name or "/" in name:
        raise ApiError("invalid_repo", "repo deve ser owner/name", 400, {"repo": repo})
    return owner, name


def parse_uuid(value: str) -> str:
    """Valida o uuid de uma rota. Id malformado = recurso inexistente (404)."""
    try:
        return str(_uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError):
        raise ApiError("not_found", "recurso inexistente", 404, {"id": value})


def jsonable(value: Any) -> Any:
    """Converte linha do banco em valor serializável em JSON."""
    if isinstance(value, _uuid.UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def row_to_dict(row: Any) -> dict:
    """Linha asyncpg → dict serializável."""
    if row is None:
        return {}
    return {k: jsonable(v) for k, v in dict(row).items()}


async def resolve_token_repo(request) -> str | None:
    """Repo do token (`owner/name`) ou `None` quando o token não está preso a um repo.

    `current_repo` (F1) levanta 403 para token/sessão sem repo — nesse caso o
    token não restringe repositório.
    """
    try:
        from app.auth import current_repo

        repo = current_repo(request)
        if inspect.isawaitable(repo):
            repo = await repo
        return repo
    except (HTTPException, ImportError):
        return None


async def assert_repo_allowed(request, repo: str) -> None:
    """403 `repo_forbidden` quando o token está preso a outro repo (contrato §6)."""
    token_repo = await resolve_token_repo(request)
    if token_repo and token_repo.strip().lower() != (repo or "").strip().lower():
        raise ApiError(
            "repo_forbidden",
            "token sem acesso a este repo",
            403,
            {"repo": repo, "token_repo": token_repo},
        )


async def record_event(
    conn,
    *,
    type: str,
    demand_id: Any = None,
    artifact_id: str | None = None,
    payload: dict | None = None,
    actor_id: Any = None,
) -> None:
    """Grava um evento. Chamado dentro da transação da mudança que o produziu."""
    await conn.execute(
        """
        INSERT INTO events (demand_id, artifact_id, type, payload, actor, at)
        VALUES ($1, $2, $3, $4::jsonb, $5, now())
        """,
        as_uuid(demand_id) if demand_id is not None else None,
        artifact_id,
        type,
        json.dumps(payload or {}),
        as_uuid(actor_id) if actor_id is not None else None,
    )


async def _apply_demand(
    conn,
    *,
    demand_id: str,
    target: str,
    actor_id: str | None,
    payload: dict | None,
    event_type: str | None,
) -> dict:
    row = await conn.fetchrow("SELECT * FROM demands WHERE id = $1 FOR UPDATE", as_uuid(demand_id))
    if row is None:
        raise ApiError("not_found", "demanda inexistente", 404, {"id": demand_id})

    current = row["status"]
    if not can_transition("demand", current, target):
        raise IllegalTransition("demand", current, target)

    if target == "open":
        # `release` devolve a demanda à fila e zera o ownership.
        updated = await conn.fetchrow(
            """
            UPDATE demands
               SET status = $2, claimed_by = NULL, claimed_at = NULL, updated_at = now()
             WHERE id = $1
            RETURNING *
            """,
            as_uuid(demand_id),
            target,
        )
    else:
        updated = await conn.fetchrow(
            "UPDATE demands SET status = $2, updated_at = now() WHERE id = $1 RETURNING *",
            as_uuid(demand_id),
            target,
        )

    event_payload = {"demand_id": str(demand_id), "from": current, "to": target}
    event_payload.update(payload or {})
    await record_event(
        conn,
        type=event_type or DEMAND_EVENTS.get((current, target)) or f"demand.{target}",
        demand_id=demand_id,
        payload=event_payload,
        actor_id=actor_id,
    )
    return row_to_dict(updated)


async def _apply_artifact(
    conn,
    *,
    artifact_id: str,
    target: str,
    actor_id: str | None,
    payload: dict | None,
    event_type: str | None,
) -> dict:
    row = await conn.fetchrow("SELECT * FROM artifacts WHERE id = $1 FOR UPDATE", artifact_id)
    if row is None:
        raise ApiError("not_found", "artefato inexistente", 404, {"id": artifact_id})

    current = row["status"]
    if not can_transition("artifact", current, target):
        raise IllegalTransition("artifact", current, target)

    updated = await conn.fetchrow(
        "UPDATE artifacts SET status = $2, updated_at = now() WHERE id = $1 RETURNING *",
        artifact_id,
        target,
    )

    event_payload = {"id": artifact_id, "from": current, "to": target}
    event_payload.update(payload or {})
    await record_event(
        conn,
        type=event_type or ARTIFACT_EVENTS.get((current, target)) or f"artifact.{target}",
        artifact_id=artifact_id,
        payload=event_payload,
        actor_id=actor_id,
    )
    return row_to_dict(updated)


async def _with_conn(conn, fn):
    """Aceita conexão (transação do chamador) ou pool (transação própria)."""
    if hasattr(conn, "acquire"):
        async with conn.acquire() as acquired:
            async with acquired.transaction():
                return await fn(acquired)
    return await fn(conn)


async def apply_demand_transition(
    conn,
    demand_id: str | None = None,
    target: str | None = None,
    *,
    actor_id: str | None = None,
    payload: dict | None = None,
    event_type: str | None = None,
) -> dict:
    """Aplica a transição e grava o evento na mesma transação. Sem estado parcial."""
    if demand_id is None or target is None:
        raise ApiError("invalid_request", "demand_id e target são obrigatórios", 400)
    return await _with_conn(
        conn,
        lambda c: _apply_demand(
            c,
            demand_id=demand_id,
            target=target,
            actor_id=actor_id,
            payload=payload,
            event_type=event_type,
        ),
    )


async def apply_artifact_transition(
    conn,
    artifact_id: str | None = None,
    target: str | None = None,
    *,
    actor_id: str | None = None,
    payload: dict | None = None,
    event_type: str | None = None,
) -> dict:
    """Idem `apply_demand_transition`, para artefatos."""
    if artifact_id is None or target is None:
        raise ApiError("invalid_request", "artifact_id e target são obrigatórios", 400)
    return await _with_conn(
        conn,
        lambda c: _apply_artifact(
            c,
            artifact_id=artifact_id,
            target=target,
            actor_id=actor_id,
            payload=payload,
            event_type=event_type,
        ),
    )
