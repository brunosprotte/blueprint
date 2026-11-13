"""Pool do Postgres, runner de migrations e helpers de query (Contrato Comum §4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import asyncpg

POOL: asyncpg.Pool | None = None

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"

SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text primary key,
    applied_at timestamptz not null default now()
)
"""


async def get_pool() -> asyncpg.Pool:
    """Devolve o pool global; levanta RuntimeError se o startup não rodou."""
    if POOL is None:
        raise RuntimeError("pool do Postgres não inicializado")
    return POOL


async def run_migrations(pool: asyncpg.Pool) -> list[str]:
    """Aplica `server/migrations/*.sql` em ordem lexicográfica.

    Cada arquivo roda dentro de uma transação e vira uma linha em
    `schema_migrations`. Já aplicadas são ignoradas — a função é idempotente.
    Devolve as versões aplicadas nesta chamada.
    """
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_MIGRATIONS_DDL)
        applied = {
            row["version"]
            for row in await conn.fetch("SELECT version FROM schema_migrations")
        }
        newly_applied: list[str] = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = path.name
            if version in applied:
                continue
            sql = path.read_text(encoding="utf-8")
            async with conn.transaction():
                await conn.execute(sql)
                await conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES ($1)", version
                )
            newly_applied.append(version)
        return newly_applied


async def fetch(pool: asyncpg.Pool, query: str, *args: Any) -> list[asyncpg.Record]:
    """SELECT que devolve várias linhas."""
    return await pool.fetch(query, *args)


async def fetchrow(
    pool: asyncpg.Pool, query: str, *args: Any
) -> asyncpg.Record | None:
    """SELECT que devolve no máximo uma linha."""
    return await pool.fetchrow(query, *args)


async def fetchval(pool: asyncpg.Pool, query: str, *args: Any) -> Any:
    """SELECT que devolve um único valor."""
    return await pool.fetchval(query, *args)


async def execute(pool: asyncpg.Pool, query: str, *args: Any) -> str:
    """Comando que não devolve linhas."""
    return await pool.execute(query, *args)
