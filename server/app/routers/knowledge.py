"""Rotas de conhecimento — fase F7.

- `GET /api/knowledge?q=&repo=&top=` — busca BM25 de duas etapas.
- `GET /api/knowledge/dossier/{demand_id}` — dossiê da demanda.

O prefixo `/api` é aplicado pelo F1 em `main.py`.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.auth import current_repo, require_user
from app.db import fetchrow, get_pool
from app.services.indexer import METHOD_CORPUS
from app.services.retriever import build_dossier, search

__all__ = ["router"]

router = APIRouter()

#: `owner/name` — o mesmo formato que `current_repo` devolve.
REPO_PATTERN = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"


def _error(status: int, code: str, message: str) -> JSONResponse:
    """Envelope único de erro (Contrato Comum §3)."""
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": {}}},
    )


def _hit_payload(hit: Any) -> dict:
    """Hit serializado — exatamente as 7 chaves do contrato (§9.2). `chunk_id` fica de fora."""
    return {
        "heading": hit.heading,
        "text": hit.text,
        "score": round(hit.score, 4),
        "source_kind": hit.source_kind,
        "artifact_id": hit.artifact_id,
        "demand_id": hit.demand_id,
        "corpus_id": hit.corpus_id,
    }


async def _resolve_repo(pool: Any, repo: str) -> Any:
    owner, _, name = repo.partition("/")
    return await fetchrow(
        pool, "SELECT id, owner, name FROM repos WHERE owner = $1 AND name = $2", owner, name
    )


async def _caller_repo(request: Request) -> str:
    """Repo (`owner/name`) do token do chamador.

    Sessão web (cookie) não tem restrição de repo (§9.1) — só o token carrega repo.
    """
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        return ""
    return await current_repo(request)


@router.get("/knowledge")
async def knowledge_search(
    request: Request,
    q: str = Query(..., min_length=1),
    repo: str | None = Query(None, pattern=REPO_PATTERN),
    top: int = Query(10, ge=1, le=200),
    _user: Any = Depends(require_user),
    caller_repo: str = Depends(_caller_repo),
):
    """Busca no corpus `method` (sem `repo`) ou no corpus do repo (`repo:<uuid>`)."""
    corpus_id = METHOD_CORPUS
    if repo:
        pool = await get_pool()
        row = await _resolve_repo(pool, repo)
        if row is None:
            return _error(404, "repo_not_found", "repo não registrado")
        if caller_repo and caller_repo != repo:
            return _error(403, "repo_forbidden", "token sem acesso ao repo")
        corpus_id = f"repo:{row['id']}"

    hits = await search(q, corpus_id, top)
    return {"query": q, "hits": [_hit_payload(hit) for hit in hits]}


@router.get("/knowledge/dossier/{demand_id}")
async def knowledge_dossier(
    request: Request,
    demand_id: uuid.UUID,
    _user: Any = Depends(require_user),
    caller_repo: str = Depends(_caller_repo),
):
    """Dossiê da demanda: necessidade, proposta, implementação e desvios."""
    pool = await get_pool()
    demand = await fetchrow(
        pool,
        "SELECT d.id, r.owner, r.name FROM demands d "
        "JOIN repos r ON r.id = d.repo_id WHERE d.id = $1",
        demand_id,
    )
    if demand is None:
        return _error(404, "demand_not_found", "demanda inexistente")

    demand_repo = f"{demand['owner']}/{demand['name']}"
    if caller_repo and caller_repo != demand_repo:
        return _error(403, "repo_forbidden", "token sem acesso ao repo")

    dossier = await build_dossier(pool, demand_id)
    if dossier is None:
        return _error(404, "demand_not_found", "demanda inexistente")
    return dossier
