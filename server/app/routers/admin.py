"""Router de administração — tokens de API, eventos e stream SSE. Implementado na fase F1."""

from __future__ import annotations

import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from app.auth import ALL_USER_SCOPES, error_detail, require_scope, require_user
from app.models import Token, User
from app.services import admin as admin_service

router = APIRouter()

SSE_POLL_SECONDS = 2.0


class TokenCreate(BaseModel):
    """Corpo de `POST /api/admin/tokens`."""

    scopes: list[str] | None = None
    repo_id: str | None = None


@router.post("/admin/tokens")
async def create_token(
    payload: TokenCreate,
    token: Token = Depends(require_scope("token:admin")),
) -> dict[str, object]:
    """Cria um token de API. O valor bruto volta uma única vez, nunca é persistido."""
    scopes = list(payload.scopes) if payload.scopes is not None else list(ALL_USER_SCOPES)
    unknown = [scope for scope in scopes if scope not in ALL_USER_SCOPES]
    if unknown:
        raise HTTPException(
            400,
            detail=error_detail(
                "invalid_scope",
                f"escopo desconhecido: {', '.join(unknown)}",
                scopes=unknown,
            ),
        )
    if payload.repo_id:
        try:
            uuid.UUID(payload.repo_id)
        except ValueError as exc:
            raise HTTPException(
                400, detail=error_detail("invalid_repo_id", "repo_id não é um uuid")
            ) from exc

    created, raw = await admin_service.create_token(
        token.user_id, scopes, payload.repo_id
    )
    return {"token": raw, "id": created.id, "scopes": list(created.scopes)}


@router.delete("/admin/tokens/{token_id}")
async def revoke_token(
    token_id: str,
    token: Token = Depends(require_scope("token:admin")),
) -> Response:
    """Revoga um token de API."""
    try:
        uuid.UUID(token_id)
    except ValueError as exc:
        raise HTTPException(
            400, detail=error_detail("invalid_token_id", "id de token inválido")
        ) from exc

    if not await admin_service.revoke_token(token_id):
        raise HTTPException(
            404, detail=error_detail("not_found", "token inexistente")
        )
    return Response(status_code=204)


@router.get("/events")
async def events(
    demand: str | None = None,
    since: int | None = None,
    user: User = Depends(require_user),
) -> dict[str, object]:
    """Eventos da timeline, filtráveis por `demand` e `since` (cursor do id)."""
    if demand:
        try:
            uuid.UUID(demand)
        except ValueError as exc:
            raise HTTPException(
                400, detail=error_detail("invalid_demand", "demand não é um uuid")
            ) from exc
    found = await admin_service.list_events(demand_id=demand, since=since)
    return {"events": [event.to_dict() for event in found]}


@router.get("/events/stream")
async def events_stream(
    request: Request,
    user: User = Depends(require_user),
) -> StreamingResponse:
    """SSE: emite os eventos novos a cada 2s, com `id:` incremental."""
    cursor = _last_event_id(request)

    async def event_source():
        last_id = cursor
        while True:
            found = await admin_service.list_events(since=last_id, limit=100)
            for event in found:
                last_id = event.id
                yield f"id: {event.id}\ndata: {json.dumps(event.to_dict())}\n\n"
            await asyncio.sleep(SSE_POLL_SECONDS)
            if await request.is_disconnected():
                break

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _last_event_id(request: Request) -> int:
    """Cursor de reconexão: header `Last-Event-ID` do painel."""
    raw = request.headers.get("last-event-id", "")
    try:
        return int(raw)
    except ValueError:
        return 0
