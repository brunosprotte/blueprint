"""Router de commits. Implementado na fase F4.

O repo vem do token — o corpo **não** aceita `repo`. O registro é idempotente
por `(repo_id, sha)`: reenviar o mesmo commit devolve o mesmo `id` com
`created: false` (spec §4.4).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.auth import User, require_scope, require_user
from app.db import get_pool
from app.services import commits as service
from app.services.lifecycle import (
    ApiError,
    api_route,
    parse_uuid,
    resolve_token_repo,
)

router = APIRouter()


class CommitFile(BaseModel):
    path: str
    additions: int | None = None
    deletions: int | None = None


class RecordCommitBody(BaseModel):
    sha: str
    message: str = ""
    branch: str = ""
    files: list[CommitFile] = []
    demand_id: str


@router.post("/commits", dependencies=[Depends(require_scope("review:write"))])
@api_route
async def record_commit(
    request: Request,
    body: RecordCommitBody,
    user: User = Depends(require_user),
) -> dict:
    repo = await resolve_token_repo(request)
    if not repo:
        raise ApiError(
            "invalid_repo",
            "token sem repo: o repo do commit vem do token — use um token de API "
            "preso a um repo (owner/name) para registrar o commit",
            400,
            {"repo": None},
        )
    pool = await get_pool()
    return await service.record_commit(
        pool,
        repo=repo,
        sha=body.sha,
        message=body.message,
        branch=body.branch,
        files=[file.model_dump() for file in body.files],
        demand_id=body.demand_id,
        actor_id=user.id,
    )


@router.get("/commits")
@api_route
async def list_commits(
    demand: str | None = None,
    repo: str | None = None,
    include_orphaned: bool = False,
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(require_user),
) -> dict:
    pool = await get_pool()
    commits = await service.list_commits(
        pool,
        demand_id=demand,
        repo=repo,
        include_orphaned=include_orphaned,
        limit=limit,
        offset=offset,
    )
    return {"commits": commits}


@router.get("/commits/{demand_id}")
@api_route
async def list_commits_of_demand(
    demand_id: str,
    include_orphaned: bool = False,
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(require_user),
) -> dict:
    """Commits de uma demanda (design master §17). Convive com `GET /api/commits`."""
    pool = await get_pool()
    commits = await service.list_commits(
        pool,
        demand_id=parse_uuid(demand_id),
        repo=None,
        include_orphaned=include_orphaned,
        limit=limit,
        offset=offset,
    )
    return {"commits": commits}
