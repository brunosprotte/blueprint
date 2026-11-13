"""Serviço de demandas — criação, consulta e transições. F4.

Regra de negócio do ciclo de vida da demanda; toda escrita de status passa por
`app/services/lifecycle.py` (invariante 2 do design master §7.1).
"""

from __future__ import annotations

import httpx

from app.db import fetch, fetchrow
from app.services.artifacts import ensure_repo
from app.services.lifecycle import (
    DEMAND_STATUSES,
    ApiError,
    IllegalTransition,
    apply_demand_transition,
    as_json,
    as_uuid,
    can_transition,
    record_event,
    row_to_dict,
    split_repo,
)

GITHUB_TIMEOUT_S = 10.0
MAX_LIMIT = 200


async def create_demand(
    pool,
    *,
    repo: str,
    module: str,
    title: str,
    body: str,
    created_by: str,
) -> dict:
    if not (body or "").strip():
        raise ApiError("empty_body", "body da demanda é obrigatório", 400)

    owner, name = split_repo(repo)
    repo_id = await ensure_repo(pool, f"{owner}/{name}")

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """
                INSERT INTO demands (repo_id, module, title, body, status, created_by)
                VALUES ($1, $2, $3, $4, 'open', $5)
                RETURNING *
                """,
                as_uuid(repo_id),
                module,
                title,
                body,
                as_uuid(created_by),
            )
            demand = row_to_dict(row)
            demand["repo"] = f"{owner}/{name}"
            await record_event(
                conn,
                type="demand.created",
                demand_id=demand["id"],
                payload={
                    "demand_id": demand["id"],
                    "module": module,
                    "title": title,
                },
                actor_id=created_by,
            )
    return demand


async def list_demands(
    pool,
    *,
    repo: str | None,
    status: str | None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    if status and status not in DEMAND_STATUSES:
        raise ApiError("invalid_status", f"status inválido: {status}", 400, {"status": status})

    where: list[str] = []
    args: list[object] = []

    if repo:
        owner, name = split_repo(repo)
        args.append(owner)
        args.append(name)
        where.append(f"r.owner = ${len(args) - 1} AND r.name = ${len(args)}")
    if status:
        args.append(status)
        where.append(f"d.status = ${len(args)}")

    clause = f"WHERE {' AND '.join(where)}" if where else ""
    args.append(min(max(int(limit), 1), MAX_LIMIT))
    args.append(max(int(offset), 0))

    rows = await fetch(
        pool,
        f"""
        SELECT d.*, r.owner, r.name
          FROM demands d
          LEFT JOIN repos r ON r.id = d.repo_id
          {clause}
         ORDER BY d.created_at ASC
         LIMIT ${len(args) - 1} OFFSET ${len(args)}
        """,
        *args,
    )
    return [_demand_row(r) for r in rows]


def _demand_row(row) -> dict:
    data = row_to_dict(row)
    owner = data.pop("owner", None)
    name = data.pop("name", None)
    if owner and name:
        data["repo"] = f"{owner}/{name}"
    return data


async def get_demand(pool, demand_id: str) -> dict | None:
    row = await fetchrow(
        pool,
        """
        SELECT d.*, r.owner, r.name
          FROM demands d
          LEFT JOIN repos r ON r.id = d.repo_id
         WHERE d.id = $1
        """,
        as_uuid(demand_id),
    )
    if row is None:
        return None

    demand = _demand_row(row)
    artifacts = await fetch(
        pool,
        """
        SELECT id, kind, path, status
          FROM artifacts
         WHERE demand_id = $1
         ORDER BY created_at ASC
        """,
        as_uuid(demand_id),
    )
    events = await fetch(
        pool,
        """
        SELECT id, type, payload, actor, at
          FROM events
         WHERE demand_id = $1
         ORDER BY at ASC, id ASC
         LIMIT 20
        """,
        as_uuid(demand_id),
    )
    demand["artifacts"] = [row_to_dict(a) for a in artifacts]
    demand["events"] = [_event_row(e) for e in events]
    return demand


def _event_row(row) -> dict:
    event = row_to_dict(row)
    event["payload"] = as_json(event.get("payload"))
    return event


async def _load_demand(pool, demand_id: str) -> dict:
    demand = await get_demand(pool, demand_id)
    if demand is None:
        raise ApiError("not_found", "demanda inexistente", 404, {"id": demand_id})
    return demand


async def _assert_claim_owner(demand: dict, actor_id: str) -> None:
    if demand.get("claimed_by") != str(actor_id):
        raise ApiError(
            "not_claim_owner",
            "somente o dono do claim pode transicionar esta demanda",
            403,
            {"claimed_by": demand.get("claimed_by")},
        )


async def start_demand(pool, *, demand_id: str, actor_id: str) -> dict:
    demand = await _load_demand(pool, demand_id)
    await _assert_claim_owner(demand, actor_id)
    return await apply_demand_transition(
        pool,
        demand_id,
        "in_progress",
        actor_id=actor_id,
        event_type="demand.started",
    )


async def merge_demand(pool, *, demand_id: str, actor_id: str) -> dict:
    demand = await _load_demand(pool, demand_id)
    current = demand.get("status") or ""
    if not can_transition("demand", current, "merged"):
        raise IllegalTransition("demand", current, "merged")

    review = await fetchrow(
        pool,
        """
        SELECT verdict
          FROM reviews
         WHERE demand_id = $1
         ORDER BY created_at DESC, id DESC
         LIMIT 1
        """,
        as_uuid(demand_id),
    )
    if review is None:
        raise ApiError("review_required", "a demanda não tem review", 409)
    verdict = review["verdict"]
    if verdict == "blocking":
        raise ApiError("review_blocking", "a review mais recente é blocking", 409, {"verdict": verdict})
    if verdict == "pending":
        raise ApiError("review_pending", "a review mais recente está pendente", 409, {"verdict": verdict})

    return await apply_demand_transition(
        pool,
        demand_id,
        "merged",
        actor_id=actor_id,
        event_type="demand.merged",
    )


async def close_demand(pool, *, demand_id: str, actor_id: str) -> dict:
    await _load_demand(pool, demand_id)
    return await apply_demand_transition(
        pool,
        demand_id,
        "done",
        actor_id=actor_id,
        event_type="demand.closed",
    )


async def block_demand(pool, *, demand_id: str, reason: str, actor_id: str) -> dict:
    if not (reason or "").strip():
        raise ApiError("reason_required", "motivo do bloqueio é obrigatório", 400)
    await _load_demand(pool, demand_id)
    return await apply_demand_transition(
        pool,
        demand_id,
        "blocked",
        actor_id=actor_id,
        payload={"reason": reason},
        event_type="demand.blocked",
    )


async def release_demand(pool, *, demand_id: str, actor_id: str) -> dict:
    """`claimed → open` e `blocked → open` (decisão D2)."""
    demand = await _load_demand(pool, demand_id)
    if demand.get("status") == "claimed":
        await _assert_claim_owner(demand, actor_id)
    return await apply_demand_transition(
        pool,
        demand_id,
        "open",
        actor_id=actor_id,
        event_type="demand.released",
    )


async def _github_shas(owner: str, name: str, branch: str) -> list[str]:
    url = f"https://api.github.com/repos/{owner}/{name}/commits"
    params = {"sha": branch, "per_page": "100"}
    async with httpx.AsyncClient(timeout=GITHUB_TIMEOUT_S) as client:
        response = await client.get(url, params=params, headers={"Accept": "application/vnd.github+json"})
    if response.status_code != 200:
        raise ApiError(
            "github_unavailable",
            f"GitHub respondeu {response.status_code}",
            503,
            {"status": response.status_code},
        )
    return [item["sha"] for item in response.json()]


async def reconcile_demand(pool, *, demand_id: str, branch: str | None, actor_id: str) -> dict:
    """Compara `commits.sha` com o head real da branch. Best-effort (§5.5)."""
    demand = await _load_demand(pool, demand_id)
    repo = demand.get("repo")
    if not repo:
        raise ApiError("not_found", "demanda sem repo", 404, {"id": demand_id})
    owner, name = split_repo(repo)

    if not branch:
        row = await fetchrow(
            pool,
            "SELECT default_branch FROM repos WHERE owner = $1 AND name = $2",
            owner,
            name,
        )
        branch = row["default_branch"] if row else "main"

    try:
        remote_shas = await _github_shas(owner, name, branch)
    except httpx.HTTPError as exc:
        await _record_reconcile_failure(pool, demand_id, branch, str(exc), actor_id)
        raise ApiError("github_unavailable", "GitHub indisponível", 503, {"branch": branch}) from exc
    except ApiError as exc:
        await _record_reconcile_failure(pool, demand_id, branch, exc.message, actor_id)
        raise

    remote = set(remote_shas)
    commits = await fetch(
        pool,
        """
        SELECT id, sha, status
          FROM commits
         WHERE demand_id = $1
         ORDER BY created_at ASC
        """,
        as_uuid(demand_id),
    )

    orphaned: list[str] = []
    kept: list[str] = []
    async with pool.acquire() as conn:
        async with conn.transaction():
            for commit in commits:
                sha = commit["sha"]
                if sha in remote:
                    kept.append(sha)
                    if commit["status"] == "orphaned":
                        await conn.execute(
                            "UPDATE commits SET status = 'present' WHERE id = $1",
                            as_uuid(commit["id"]),
                        )
                else:
                    orphaned.append(sha)
                    if commit["status"] != "orphaned":
                        await conn.execute(
                            "UPDATE commits SET status = 'orphaned' WHERE id = $1",
                            as_uuid(commit["id"]),
                        )
            await record_event(
                conn,
                type="demand.reconciled",
                demand_id=demand_id,
                payload={
                    "demand_id": str(demand_id),
                    "branch": branch,
                    "orphaned": orphaned,
                    "kept": kept,
                },
                actor_id=actor_id,
            )

    return {
        "demand_id": str(demand_id),
        "branch": branch,
        "orphaned": orphaned,
        "kept": kept,
    }


async def _record_reconcile_failure(
    pool, demand_id: str, branch: str, reason: str, actor_id: str
) -> None:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await record_event(
                conn,
                type="demand.reconcile_failed",
                demand_id=demand_id,
                payload={
                    "demand_id": str(demand_id),
                    "branch": branch,
                    "reason": reason,
                },
                actor_id=actor_id,
            )
