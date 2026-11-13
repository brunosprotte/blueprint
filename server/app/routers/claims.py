"""Router de claims. Implementado na fase F4.

`POST /api/claims/{id}/release` **não** existe — `release` mora em
`/api/demands/{id}/release` (contrato §8.2).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.auth import User, require_scope, require_user
from app.db import get_pool
from app.services import claims as service
from app.services.lifecycle import (
    ApiError,
    api_route,
    assert_repo_allowed,
    resolve_token_repo,
)

router = APIRouter()


class ClaimBody(BaseModel):
    repo: str | None = None


@router.post("/claims", dependencies=[Depends(require_scope("demand:claim"))])
@api_route
async def claim(
    request: Request,
    body: ClaimBody | None = None,
    user: User = Depends(require_user),
) -> dict:
    token_repo = await resolve_token_repo(request)
    repo = (body.repo if body and body.repo else token_repo)
    if not repo:
        raise ApiError("invalid_repo", "repo é obrigatório para o claim", 400)
    await assert_repo_allowed(request, repo)

    pool = await get_pool()
    demand = await service.claim_next(pool, repo=repo, user_id=user.id)
    if demand is None:
        raise ApiError("empty", "não há demanda disponível", 404, {"repo": repo})
    return {"demand": demand}


@router.get("/claims/current")
@api_route
async def current_claim(
    request: Request,
    user: User = Depends(require_user),
) -> dict:
    pool = await get_pool()
    token_repo = await resolve_token_repo(request)
    demand = await service.current_claim(pool, user_id=user.id, repo=token_repo)
    return {"demand": demand}
