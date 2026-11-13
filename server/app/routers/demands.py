"""Router de demandas. Implementado na fase F4."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.auth import User, require_scope, require_user
from app.db import get_pool
from app.services import demands as service
from app.services.lifecycle import (
    ApiError,
    api_route,
    assert_repo_allowed,
    parse_uuid,
)

router = APIRouter()


class CreateDemandBody(BaseModel):
    repo: str
    module: str
    title: str
    body: str


class BlockDemandBody(BaseModel):
    reason: str = ""


class ReconcileDemandBody(BaseModel):
    branch: str | None = None


@router.post("/demands", dependencies=[Depends(require_scope("demand:write"))])
@api_route
async def create_demand(
    request: Request,
    body: CreateDemandBody,
    user: User = Depends(require_user),
) -> dict:
    await assert_repo_allowed(request, body.repo)
    pool = await get_pool()
    return await service.create_demand(
        pool,
        repo=body.repo,
        module=body.module,
        title=body.title,
        body=body.body,
        created_by=user.id,
    )


@router.get("/demands")
@api_route
async def list_demands(
    repo: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(require_user),
) -> dict:
    pool = await get_pool()
    demands = await service.list_demands(
        pool, repo=repo, status=status, limit=limit, offset=offset
    )
    return {"demands": demands}


@router.get("/demands/{demand_id}")
@api_route
async def get_demand(
    demand_id: str,
    user: User = Depends(require_user),
) -> dict:
    pool = await get_pool()
    demand = await service.get_demand(pool, parse_uuid(demand_id))
    if demand is None:
        raise ApiError("not_found", "demanda inexistente", 404, {"id": demand_id})
    return demand


@router.post("/demands/{demand_id}/start", dependencies=[Depends(require_scope("demand:write"))])
@api_route
async def start_demand(
    demand_id: str,
    user: User = Depends(require_user),
) -> dict:
    pool = await get_pool()
    return await service.start_demand(pool, demand_id=parse_uuid(demand_id), actor_id=user.id)


@router.post("/demands/{demand_id}/merge", dependencies=[Depends(require_scope("demand:write"))])
@api_route
async def merge_demand(
    demand_id: str,
    user: User = Depends(require_user),
) -> dict:
    pool = await get_pool()
    return await service.merge_demand(pool, demand_id=parse_uuid(demand_id), actor_id=user.id)


@router.post("/demands/{demand_id}/close", dependencies=[Depends(require_scope("demand:write"))])
@api_route
async def close_demand(
    demand_id: str,
    user: User = Depends(require_user),
) -> dict:
    pool = await get_pool()
    return await service.close_demand(pool, demand_id=parse_uuid(demand_id), actor_id=user.id)


@router.post("/demands/{demand_id}/block", dependencies=[Depends(require_scope("demand:write"))])
@api_route
async def block_demand(
    demand_id: str,
    body: BlockDemandBody,
    user: User = Depends(require_user),
) -> dict:
    pool = await get_pool()
    return await service.block_demand(
        pool,
        demand_id=parse_uuid(demand_id),
        reason=body.reason,
        actor_id=user.id,
    )


@router.post("/demands/{demand_id}/release", dependencies=[Depends(require_scope("demand:write"))])
@api_route
async def release_demand(
    demand_id: str,
    user: User = Depends(require_user),
) -> dict:
    pool = await get_pool()
    return await service.release_demand(pool, demand_id=parse_uuid(demand_id), actor_id=user.id)


@router.post("/demands/{demand_id}/reconcile", dependencies=[Depends(require_scope("demand:write"))])
@api_route
async def reconcile_demand(
    demand_id: str,
    body: ReconcileDemandBody | None = None,
    user: User = Depends(require_user),
) -> dict:
    pool = await get_pool()
    return await service.reconcile_demand(
        pool,
        demand_id=parse_uuid(demand_id),
        branch=body.branch if body else None,
        actor_id=user.id,
    )
