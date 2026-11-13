"""Router de geração de BR/SPEC — fase F5.

Prefixo próprio `/api/generation/...` (decisão D5 da spec F5): `demands.py` e
`artifacts.py` são do F4 e o F5 não pode editá-los.

O servidor devolve markdown; quem escreve no repo de dev é o kit (`sdd.py pull`,
F8) — invariante 1 do design master.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.services import generator
from app.services.generator import (
    ArtifactPathConflict,
    GenerationContext,
    IllegalDemandState,
    InvalidArtifactPath,
    LLMUnavailable,
    TERMINAL_DEMAND_STATUSES,
)

router = APIRouter()

try:
    from app.auth import require_scope
except ImportError:  # core do F1 ainda não existe — a rota falha fechada
    require_scope = None

try:
    from app.db import get_pool
except ImportError:  # core do F1 ainda não existe — a rota falha fechada
    get_pool = None


def _scope_dependency(scope: str) -> Callable[..., Any]:
    """Dependência que exige o escopo `scope`.

    `app.auth` é a única fonte de autorização (Contrato Comum §2). Enquanto o core
    do F1 não existir, a rota responde 503 em vez de liberar o acesso.
    """
    if require_scope is None:

        async def _pending(request: Request) -> Any:
            raise _error(503, "auth_unavailable", "autenticação indisponível (F1 pendente)")

        return _pending
    return require_scope(scope)


def _error(
    status: int,
    code: str,
    message: str,
    detail: Mapping[str, Any] | None = None,
) -> JSONResponse:
    """Envelope único de erro (Contrato Comum §3)."""
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": dict(detail or {})}},
    )


async def _pool() -> Any:
    """Pool do Postgres (F1).

    `get_pool` é importado no módulo (e não dentro do handler) para que o
    vínculo seja resolvido com o core real, como nos demais routers do F4.
    """
    if get_pool is None:
        raise _error(503, "core_unavailable", "core do servidor indisponível (F1 pendente)")
    try:
        return await get_pool()
    except RuntimeError as exc:
        raise _error(503, "database_unavailable", str(exc)) from exc


async def handle_generate_br(
    pool: Any,
    demand_id: str,
    *,
    client: Any | None = None,
) -> tuple[int, dict[str, Any]]:
    """Núcleo da rota de BR — devolve (status, payload).

    Fica separado do handler HTTP para poder ser testado sem o core do F1.
    """
    demand = await pool.fetchrow(
        "SELECT id, repo_id, module, title, body, status FROM demands WHERE id = $1", demand_id
    )
    if demand is None:
        return 404, _error_body("not_found", f"demanda não encontrada: {demand_id}")
    if not demand["repo_id"]:
        return 400, _error_body("missing_repo", "a demanda não tem repo")
    if str(demand["status"]) in TERMINAL_DEMAND_STATUSES:
        return 409, _error_body(
            "illegal_transition", f"{demand['status']} -> generate-br"
        )

    module = str(demand["module"] or "")
    method_context = await generator.resolve_method_context("br", module)
    repo_context = await generator.resolve_repo_context(
        str(demand["repo_id"]),
        f"{demand['title'] or ''}\n{(demand['body'] or '')[:2000]}",
    )
    ctx = GenerationContext(
        pool=pool,
        demand_id=str(demand["id"]),
        repo_id=str(demand["repo_id"]),
        module=module,
        method_context=method_context,
        repo_context=repo_context,
        client=client,
    )

    try:
        report = await generator.generate_br_report(demand, ctx)
    except LLMUnavailable as exc:
        return 503, _error_body(
            "llm_unavailable",
            "Claude API indisponível",
            {"stage": exc.stage or "br", "error_type": type(exc).__name__},
        )
    except InvalidArtifactPath as exc:
        return 422, _error_body(
            "invalid_module_feature",
            str(exc),
            {"module": exc.module, "feature": exc.feature},
        )
    except ArtifactPathConflict as exc:
        return 409, _error_body("artifact_path_conflict", str(exc), {"path": exc.path})
    except IllegalDemandState as exc:
        return 409, _error_body("illegal_transition", str(exc))

    doubts_file = report.doubts_files[0] if report.doubts_files else None
    return 200, {
        "created": report.created,
        "idempotent": report.idempotent,
        "artifact": report.artifacts[0],
        "doubts_file": (
            {"path": doubts_file.path, "content": doubts_file.content} if doubts_file else None
        ),
        "spec_edges": [
            {"parent_id": edge.parent_id, "child_id": edge.child_id, "type": edge.type}
            for edge in report.spec_edges
        ],
        "context": report.context,
        "usage": report.usage or {"input_tokens": 0, "output_tokens": 0},
    }


async def handle_generate_specs(
    pool: Any,
    artifact_id: str,
    *,
    client: Any | None = None,
) -> tuple[int, dict[str, Any]]:
    """Núcleo da rota de SPECs — devolve (status, payload)."""
    br = await pool.fetchrow(
        "SELECT id, demand_id, repo_id, kind, module, feature, path, sha, status, version, content"
        " FROM artifacts WHERE id = $1",
        artifact_id,
    )
    if br is None or str(br["kind"]) != "br":
        return 404, _error_body("not_found", f"BR não encontrada: {artifact_id}")
    if not br["demand_id"]:
        return 400, _error_body("missing_demand", "a BR não tem demanda de origem")

    demand = await pool.fetchrow(
        "SELECT id, repo_id, module, status FROM demands WHERE id = $1", br["demand_id"]
    )
    if demand is not None and str(demand["status"]) in TERMINAL_DEMAND_STATUSES:
        return 409, _error_body("illegal_transition", f"{demand['status']} -> generate-specs")

    br_front = generator.parse_frontmatter(str(br["content"] or ""))
    method_context = await generator.resolve_method_context(
        "spec", str(br["module"] or ""), br_content=str(br["content"] or "")
    )
    repo_context = await generator.resolve_repo_context(
        str(br["repo_id"] or (demand["repo_id"] if demand else "")),
        f"{br_front.get('title') or ''}\n{(br['content'] or '')[:2000]}",
    )
    ctx = GenerationContext(
        pool=pool,
        demand_id=str(br["demand_id"]),
        repo_id=str(br["repo_id"] or (demand["repo_id"] if demand else "")),
        module=str(br["module"] or ""),
        method_context=method_context,
        repo_context=repo_context,
        client=client,
    )

    try:
        report = await generator.generate_specs_report(br, ctx)
    except LLMUnavailable as exc:
        return 503, _error_body(
            "llm_unavailable",
            "Claude API indisponível",
            {"stage": exc.stage or "specs", "error_type": type(exc).__name__},
        )
    except InvalidArtifactPath as exc:
        return 422, _error_body(
            "invalid_module_feature",
            str(exc),
            {"module": exc.module, "feature": exc.feature},
        )
    except ArtifactPathConflict as exc:
        return 409, _error_body("artifact_path_conflict", str(exc), {"path": exc.path})
    except IllegalDemandState as exc:
        return 409, _error_body("illegal_transition", str(exc))

    return 200, {
        "created": report.created,
        "idempotent": report.idempotent,
        "artifacts": list(report.artifacts),
        "doubts_files": [
            {"path": doubts.path, "content": doubts.content} for doubts in report.doubts_files
        ],
        "spec_edges": [
            {"parent_id": edge.parent_id, "child_id": edge.child_id, "type": edge.type}
            for edge in report.spec_edges
        ],
        "context": report.context,
        "usage": report.usage or {"input_tokens": 0, "output_tokens": 0},
    }


def _error_body(code: str, message: str, detail: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Corpo do envelope de erro (Contrato Comum §3)."""
    return {"error": {"code": code, "message": message, "detail": dict(detail or {})}}


@router.post(
    "/generation/demands/{demand_id}/br",
    dependencies=[Depends(_scope_dependency("demand:write"))],
)
async def generate_br_route(demand_id: str) -> JSONResponse:
    """Gera a BR da demanda. Idempotente: BR existente devolve 200 com `created: false`."""
    pool = await _pool()
    status, payload = await handle_generate_br(pool, demand_id)
    return JSONResponse(status_code=status, content=payload)


@router.post(
    "/generation/artifacts/{artifact_id}/specs",
    dependencies=[Depends(_scope_dependency("demand:write"))],
)
async def generate_specs_route(artifact_id: str) -> JSONResponse:
    """Gera as SPECs da BR. Idempotente: SPECs existentes devolvem 200 com `created: false`."""
    pool = await _pool()
    status, payload = await handle_generate_specs(pool, artifact_id)
    return JSONResponse(status_code=status, content=payload)
