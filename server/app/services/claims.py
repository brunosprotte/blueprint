"""Claim atômico da fila de demandas. F4.

`FOR UPDATE SKIP LOCKED` resolve a corrida no Postgres: N agentes disputando a
mesma demanda → exatamente um vence (design master §9.1 e §20).
"""

from __future__ import annotations

from app.db import fetch, fetchrow
from app.services.artifacts import ensure_repo
from app.services.lifecycle import (
    IllegalTransition,
    as_uuid,
    can_transition,
    record_event,
    row_to_dict,
    split_repo,
)

CLAIM_SQL = """
UPDATE demands
   SET status='claimed', claimed_by=$1, claimed_at=now(), updated_at=now()
 WHERE id = (
     SELECT id FROM demands
      WHERE repo_id=$2 AND status='open'
      ORDER BY created_at
      FOR UPDATE SKIP LOCKED
      LIMIT 1
 )
 RETURNING *;
"""


async def claim_next(pool, *, repo: str, user_id: str) -> dict | None:
    """Pega a próxima demanda `open` do repo. `None` = fila vazia."""
    owner, name = split_repo(repo)
    repo_id = await ensure_repo(pool, f"{owner}/{name}")

    # A decisão de transição passa pelo lifecycle (único dono do status).
    if not can_transition("demand", "open", "claimed"):
        raise IllegalTransition("demand", "open", "claimed")

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(CLAIM_SQL, as_uuid(user_id), as_uuid(repo_id))
            if row is None:
                return None

            demand = row_to_dict(row)
            demand["repo"] = f"{owner}/{name}"
            await record_event(
                conn,
                type="demand.claimed",
                demand_id=demand["id"],
                payload={
                    "demand_id": demand["id"],
                    "repo": demand["repo"],
                    "claimed_by": str(user_id),
                },
                actor_id=user_id,
            )
    return demand


async def current_claim(pool, *, user_id: str, repo: str | None) -> dict | None:
    """Demanda `claimed`/`in_progress` do usuário. `None` se não houver."""
    args: list[object] = [as_uuid(user_id)]
    clause = "d.claimed_by = $1 AND d.status IN ('claimed', 'in_progress')"

    if repo:
        owner, name = split_repo(repo)
        args.append(owner)
        args.append(name)
        clause += f" AND r.owner = ${len(args) - 1} AND r.name = ${len(args)}"

    row = await fetchrow(
        pool,
        f"""
        SELECT d.*, r.owner, r.name
          FROM demands d
          LEFT JOIN repos r ON r.id = d.repo_id
         WHERE {clause}
         ORDER BY d.claimed_at DESC NULLS LAST, d.created_at DESC
         LIMIT 1
        """,
        *args,
    )
    if row is None:
        return None

    demand = row_to_dict(row)
    owner = demand.pop("owner", None)
    name = demand.pop("name", None)
    if owner and name:
        demand["repo"] = f"{owner}/{name}"
    return demand


async def list_claims(pool, *, repo: str | None, limit: int = 50, offset: int = 0) -> list[dict]:
    """Demandas em `claimed`/`in_progress` — usado pelo painel (F10)."""
    args: list[object] = []
    clause = "d.status IN ('claimed', 'in_progress')"
    if repo:
        owner, name = split_repo(repo)
        args.extend([owner, name])
        clause += f" AND r.owner = ${len(args) - 1} AND r.name = ${len(args)}"
    args.extend([min(max(int(limit), 1), 200), max(int(offset), 0)])

    rows = await fetch(
        pool,
        f"""
        SELECT d.*, r.owner, r.name
          FROM demands d
          LEFT JOIN repos r ON r.id = d.repo_id
         WHERE {clause}
         ORDER BY d.claimed_at DESC NULLS LAST
         LIMIT ${len(args) - 1} OFFSET ${len(args)}
        """,
        *args,
    )
    out = []
    for row in rows:
        data = row_to_dict(row)
        owner = data.pop("owner", None)
        name = data.pop("name", None)
        if owner and name:
            data["repo"] = f"{owner}/{name}"
        out.append(data)
    return out
