"""Router de artefatos. Implementado na fase F4.

`POST /api/artifacts/{id}/approve` devolve 503 enquanto o F6 não existe — o
corpo do handler **não** muda quando o F6 chegar (contrato §8.1): o pipeline é
importado de forma tardia, dentro do handler.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.auth import User, require_scope, require_user
from app.db import get_pool
from app.services import artifacts as service
from app.services.lifecycle import (
    ApiError,
    api_route,
    assert_repo_allowed,
)

router = APIRouter()


class SyncDoc(BaseModel):
    path: str
    content: str = ""


class SyncBody(BaseModel):
    repo: str
    docs: list[SyncDoc] = []
    repo_path: str | None = None


class RequestReviewBody(BaseModel):
    repo_path: str | None = None


@router.get("/artifacts")
@api_route
async def list_artifacts(
    demand: str | None = None,
    repo: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(require_user),
) -> dict:
    pool = await get_pool()
    artifacts = await service.list_artifacts(
        pool,
        demand_id=demand,
        repo=repo,
        limit=limit,
        offset=offset,
    )
    return {"artifacts": artifacts}


@router.get("/artifacts/pending")
@api_route
async def list_pending(
    request: Request,
    repo: str | None = None,
    demand: str | None = None,
    user: User = Depends(require_user),
) -> dict:
    """Artefatos que o kit (`sdd.py pull`) precisa escrever no repo de dev."""
    if not repo:
        raise ApiError("invalid_request", "repo é obrigatório", 400)
    await assert_repo_allowed(request, repo)
    pool = await get_pool()
    artifacts = await service.list_pending(pool, repo=repo, demand_id=demand)
    return {"artifacts": artifacts}


@router.get("/artifacts/{artifact_id}")
@api_route
async def get_artifact(
    artifact_id: str,
    user: User = Depends(require_user),
) -> dict:
    pool = await get_pool()
    artifact = await service.get_artifact(pool, artifact_id)
    if artifact is None:
        raise ApiError("not_found", "artefato inexistente", 404, {"id": artifact_id})
    return artifact


@router.post("/artifacts/sync", dependencies=[Depends(require_scope("artifact:sync"))])
@api_route
async def sync(
    request: Request,
    body: SyncBody,
    user: User = Depends(require_user),
) -> dict:
    await assert_repo_allowed(request, body.repo)
    pool = await get_pool()
    return await service.sync(
        pool,
        repo=body.repo,
        docs=[doc.model_dump() for doc in body.docs],
        actor_id=user.id,
        repo_path=body.repo_path,
    )


@router.post(
    "/artifacts/{artifact_id}/request-review",
    dependencies=[Depends(require_scope("artifact:approve"))],
)
@api_route
async def request_review(
    artifact_id: str,
    body: RequestReviewBody | None = None,
    user: User = Depends(require_user),
) -> dict:
    pool = await get_pool()
    return await service.request_review(
        pool,
        artifact_id=artifact_id,
        actor_id=user.id,
        repo_path=body.repo_path if body else None,
    )


@router.post(
    "/artifacts/{artifact_id}/approve",
    dependencies=[Depends(require_scope("artifact:approve"))],
)
@api_route
async def approve(
    artifact_id: str,
    user: User = Depends(require_user),
) -> dict:
    pool = await get_pool()
    return await service.approve(pool, artifact_id=artifact_id, actor_id=user.id)


@router.post(
    "/artifacts/{artifact_id}/stabilize",
    dependencies=[Depends(require_scope("artifact:approve"))],
)
@api_route
async def stabilize(
    artifact_id: str,
    user: User = Depends(require_user),
) -> dict:
    pool = await get_pool()
    return await service.stabilize(pool, artifact_id=artifact_id, actor_id=user.id)


@router.get("/artifacts/{artifact_id}/doubts")
@api_route
async def list_doubts(
    artifact_id: str,
    user: User = Depends(require_user),
) -> dict:
    pool = await get_pool()
    artifact = await service.get_artifact(pool, artifact_id)
    if artifact is None:
        raise ApiError("not_found", "artefato inexistente", 404, {"id": artifact_id})
    doubts = await service.list_doubts(pool, artifact_id)
    return {
        "artifact_id": artifact_id,
        "doubts_index": artifact.get("doubts_index"),
        "doubts": doubts,
    }
