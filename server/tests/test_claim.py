"""Claim atômico da fila — o teste mais importante da F4 (design master §20).

N corrotinas disputando a mesma demanda: exatamente uma vence.

Usa as fixtures reais do F1 (`pool`, `client`, `auth_token`) e os módulos
reais — nada é injetado em `sys.modules`.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from app.services import claims as claims_service


async def _new_user(pool, login: str = "dev") -> str:
    row = await pool.fetchrow(
        "INSERT INTO users (github_id, login) VALUES ($1, $2) RETURNING id",
        uuid.uuid4().int % 10**12,
        login,
    )
    return str(row["id"])


async def _new_repo(pool, owner: str = "acme", name: str = "app") -> str:
    row = await pool.fetchrow(
        "INSERT INTO repos (owner, name) VALUES ($1, $2) RETURNING id",
        owner,
        name,
    )
    return str(row["id"])


async def _new_demand(pool, repo_id: str, created_by: str, title: str = "demanda") -> str:
    row = await pool.fetchrow(
        """
        INSERT INTO demands (repo_id, module, title, body, status, created_by)
        VALUES ($1, 'login', $2, 'corpo', 'open', $3)
        RETURNING id
        """,
        uuid.UUID(repo_id),
        title,
        uuid.UUID(created_by),
    )
    return str(row["id"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------
# Testes
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_claim_single_winner(pool):
    """8 corrotinas disputando 1 demanda → 1 vencedora, 7 com a fila vazia."""
    creator = await _new_user(pool)
    repo_id = await _new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, creator)

    users = [await _new_user(pool, f"agente-{index}") for index in range(8)]

    results = await asyncio.gather(
        *[
            claims_service.claim_next(pool, repo="acme/app", user_id=user_id)
            for user_id in users
        ]
    )

    winners = [result for result in results if result is not None]
    assert len(winners) == 1, f"esperado 1 vencedor, veio {len(winners)}"
    assert winners[0]["id"] == demand_id

    row = await pool.fetchrow("SELECT * FROM demands WHERE id = $1", uuid.UUID(demand_id))
    assert row["status"] == "claimed"
    assert str(row["claimed_by"]) == winners[0]["claimed_by"]


@pytest.mark.asyncio
async def test_claim_sets_owner(pool):
    user_id = await _new_user(pool)
    repo_id = await _new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, user_id)

    claimed = await claims_service.claim_next(pool, repo="acme/app", user_id=user_id)

    assert claimed["id"] == demand_id
    assert claimed["status"] == "claimed"
    assert claimed["claimed_by"] == user_id
    assert claimed["claimed_at"] is not None


@pytest.mark.asyncio
async def test_claim_event(pool):
    user_id = await _new_user(pool)
    repo_id = await _new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, user_id)

    await claims_service.claim_next(pool, repo="acme/app", user_id=user_id)

    event = await pool.fetchrow(
        "SELECT * FROM events WHERE demand_id = $1 AND type = 'demand.claimed'",
        uuid.UUID(demand_id),
    )
    assert event is not None
    payload = _payload(event["payload"])
    assert payload["repo"] == "acme/app"
    assert payload["claimed_by"] == user_id


@pytest.mark.asyncio
async def test_claim_empty_queue(pool):
    user_id = await _new_user(pool)
    await _new_repo(pool)

    assert await claims_service.claim_next(pool, repo="acme/app", user_id=user_id) is None


@pytest.mark.asyncio
async def test_claim_skips_locked_row(pool):
    """Linha travada por outra transação → o claim pega a próxima."""
    user_id = await _new_user(pool)
    repo_id = await _new_repo(pool)
    first = await _new_demand(pool, repo_id, user_id, title="primeira")
    second = await _new_demand(pool, repo_id, user_id, title="segunda")

    async with pool.acquire() as locker:
        async with locker.transaction():
            await locker.execute(
                "SELECT id FROM demands WHERE id = $1 FOR UPDATE", uuid.UUID(first)
            )
            claimed = await claims_service.claim_next(pool, repo="acme/app", user_id=user_id)

    assert claimed["id"] == second
    assert claimed["id"] != first


@pytest.mark.asyncio
async def test_current_claim(pool):
    user_id = await _new_user(pool)
    repo_id = await _new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, user_id)

    assert await claims_service.current_claim(pool, user_id=user_id, repo="acme/app") is None

    await claims_service.claim_next(pool, repo="acme/app", user_id=user_id)

    current = await claims_service.current_claim(pool, user_id=user_id, repo="acme/app")
    assert current["id"] == demand_id
    assert current["status"] == "claimed"


@pytest.mark.asyncio
async def test_claims_route_release_absent():
    """`POST /api/claims/{id}/release` não existe (Contrato Comum §8.2)."""
    from app.routers import claims as claims_router

    paths = {route.path for route in claims_router.router.routes}
    assert "/claims" in paths
    assert not any("release" in path for path in paths), paths


@pytest.mark.asyncio
async def test_claim_empty_queue_is_404_empty(client, auth_token):
    """Fila vazia → 404 `empty` no envelope canônico (Contrato Comum §3)."""
    response = await client.post(
        "/api/claims", json={"repo": "acme/app"}, headers=_auth(auth_token)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "empty"


@pytest.mark.asyncio
async def test_claim_invalid_repo_400(pool):
    """Repo malformado → 400 `invalid_repo`."""
    from app.services.lifecycle import ApiError

    user_id = await _new_user(pool)

    with pytest.raises(ApiError) as excinfo:
        await claims_service.claim_next(pool, repo="sem-slash", user_id=user_id)

    assert excinfo.value.code == "invalid_repo"
    assert excinfo.value.status == 400


def _payload(value) -> dict:
    import json

    return json.loads(value) if isinstance(value, str) else value
