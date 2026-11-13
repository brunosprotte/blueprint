"""Registro e consulta de commits. F4.

`commits.status` ∈ {`present`, `orphaned`} — `orphaned` = commit registrado que
não existe no remoto (reconcile, design master §13). Dono da coluna: F4
(migration 004) — o F7 só consome.
"""

from __future__ import annotations

import json
import re

from app.db import fetch, fetchrow
from app.services.artifacts import ensure_repo
from app.services.lifecycle import (
    ApiError,
    as_uuid,
    record_event,
    row_to_dict,
    split_repo,
)

SHA_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")


def normalize_files(files) -> list[dict]:
    """`[{"path", "additions", "deletions"}]` — só o que o DDL guarda."""
    if isinstance(files, str):
        try:
            files = json.loads(files)
        except (TypeError, ValueError):
            return []
    normalized: list[dict] = []
    for item in files or []:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        if not path:
            continue
        normalized.append(
            {
                "path": str(path),
                "additions": _int_or_none(item.get("additions")),
                "deletions": _int_or_none(item.get("deletions")),
            }
        )
    return normalized


def _int_or_none(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def record_commit(
    pool,
    *,
    repo: str,
    sha: str,
    message: str,
    branch: str,
    files: list[dict],
    demand_id: str,
    actor_id: str | None,
) -> dict:
    """Grava o commit. Idempotente por `(repo_id, sha)`."""
    if not isinstance(sha, str) or not SHA_PATTERN.match(sha):
        raise ApiError("invalid_sha", "sha inválido", 400, {"sha": sha})

    owner, name = split_repo(repo)
    repo_id = await ensure_repo(pool, f"{owner}/{name}")

    demand = await fetchrow(
        pool,
        "SELECT id, repo_id FROM demands WHERE id = $1",
        as_uuid(demand_id),
    )
    if demand is None or str(demand["repo_id"]) != str(repo_id):
        raise ApiError(
            "demand_not_found",
            "demanda inexistente ou de outro repo",
            404,
            {"demand_id": demand_id},
        )

    author = await _author_login(pool, actor_id)
    normalized = normalize_files(files)

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO commits (demand_id, repo_id, sha, message, branch, author, files)
                VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                ON CONFLICT (repo_id, sha) DO NOTHING
                RETURNING *
                """,
                as_uuid(demand_id),
                as_uuid(repo_id),
                sha,
                message,
                branch,
                author,
                json.dumps(normalized),
            )
            if row is None:
                row = await conn.fetchrow(
                    "SELECT * FROM commits WHERE repo_id = $1 AND sha = $2",
                    as_uuid(repo_id),
                    sha,
                )
                created = False
            else:
                created = True
                await record_event(
                    conn,
                    type="commit.recorded",
                    demand_id=demand_id,
                    payload={
                        "commit_id": str(row["id"]),
                        "sha": sha,
                        "demand_id": str(demand_id),
                        "branch": branch,
                    },
                    actor_id=actor_id,
                )

    if row is None:
        raise ApiError("commit_conflict", "commit não pôde ser gravado", 409, {"sha": sha})

    data = row_to_dict(row)
    data["files"] = normalized
    data["created"] = created
    data["repo"] = f"{owner}/{name}"
    return data


async def _author_login(pool, actor_id: str | None) -> str | None:
    if not actor_id:
        return None
    row = await fetchrow(pool, "SELECT login FROM users WHERE id = $1", as_uuid(actor_id))
    return row["login"] if row else None


async def list_commits(
    pool,
    *,
    demand_id: str | None,
    repo: str | None,
    include_orphaned: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """Commits do repo. `orphaned` fica de fora por padrão (F7 exclui do dossiê)."""
    args: list[object] = []
    where: list[str] = []

    if demand_id:
        args.append(as_uuid(demand_id))
        where.append(f"c.demand_id = ${len(args)}")
    if repo:
        owner, name = split_repo(repo)
        args.extend([owner, name])
        where.append(f"r.owner = ${len(args) - 1} AND r.name = ${len(args)}")
    if not include_orphaned:
        where.append("c.status <> 'orphaned'")

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    args.extend([min(max(int(limit), 1), 200), max(int(offset), 0)])

    rows = await fetch(
        pool,
        f"""
        SELECT c.*, r.owner, r.name
          FROM commits c
          LEFT JOIN repos r ON r.id = c.repo_id
          {clause}
         ORDER BY c.created_at DESC
         LIMIT ${len(args) - 1} OFFSET ${len(args)}
        """,
        *args,
    )

    out: list[dict] = []
    for row in rows:
        data = row_to_dict(row)
        owner = data.pop("owner", None)
        name = data.pop("name", None)
        if owner and name:
            data["repo"] = f"{owner}/{name}"
        data["files"] = normalize_files(data.get("files"))
        out.append(data)
    return out
