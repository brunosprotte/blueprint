"""Serviço de administração — tokens de API e eventos. Implementado na fase F1."""

from __future__ import annotations

import uuid

from app import db
from app.auth import generate_token
from app.models import Event, Token


async def create_token(
    user_id: str,
    scopes: list[str],
    repo_id: str | None = None,
) -> tuple[Token, str]:
    """Cria um token de API. Devolve `(token, bruto)` — o bruto só existe aqui.

    Só o sha256 do bruto vai para `tokens.token_hash`.
    """
    pool = await db.get_pool()
    raw, token_hash = generate_token()
    row = await db.fetchrow(
        pool,
        """
        INSERT INTO tokens (user_id, repo_id, token_hash, scopes)
        VALUES ($1, $2, $3, $4)
        RETURNING id, user_id, repo_id, scopes
        """,
        uuid.UUID(user_id),
        uuid.UUID(repo_id) if repo_id else None,
        token_hash,
        scopes,
    )
    return Token.from_row(row), raw


async def revoke_token(token_id: str) -> bool:
    """Revoga o token. Devolve False quando o token não existe."""
    pool = await db.get_pool()
    result = await db.execute(
        pool,
        "UPDATE tokens SET revoked_at = now() WHERE id = $1 AND revoked_at IS NULL",
        uuid.UUID(token_id),
    )
    return result != "UPDATE 0"


async def list_events(
    demand_id: str | None = None,
    since: int | None = None,
    limit: int = 200,
) -> list[Event]:
    """Eventos da timeline em ordem cronológica, filtráveis por demanda e cursor."""
    pool = await db.get_pool()
    rows = await db.fetch(
        pool,
        """
        SELECT id, demand_id, artifact_id, type, payload, actor, at
          FROM events
         WHERE ($1::uuid IS NULL OR demand_id = $1::uuid)
           AND ($2::bigint IS NULL OR id > $2::bigint)
         ORDER BY id ASC
         LIMIT $3
        """,
        uuid.UUID(demand_id) if demand_id else None,
        since,
        limit,
    )
    return [Event.from_row(row) for row in rows]
