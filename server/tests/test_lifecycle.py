"""Ciclo de vida — máquina de estados e transições de demanda (spec §7).

A primeira parte é lógica pura (sem banco). A segunda exercita as transições
pelas rotas reais, com as fixtures do F1 (`pool`, `client`, `auth_token`).
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.services.lifecycle import (
    ARTIFACT_STATUSES,
    ARTIFACT_TRANSITIONS,
    DEMAND_STATUSES,
    DEMAND_TRANSITIONS,
    ApiError,
    IllegalTransition,
    allowed_targets,
    can_transition,
    error_payload,
    error_response,
)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _payload(value) -> dict:
    return json.loads(value) if isinstance(value, str) else value


async def _user_id(pool) -> str:
    row = await pool.fetchrow("SELECT id FROM users WHERE login = 'tester'")
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


async def _create_demand(client, auth_token, title: str = "demanda") -> str:
    """Cria uma demanda `open` pela API e devolve o id."""
    response = await client.post(
        "/api/demands",
        json={
            "repo": "acme/app",
            "module": "login",
            "title": title,
            "body": "preciso de login",
        },
        headers=_auth(auth_token),
    )
    assert response.status_code == 200
    return response.json()["id"]


# --------------------------------------------------------------------------
# Lógica pura — sem banco
# --------------------------------------------------------------------------
def test_demand_transitions_legal():
    for current, targets in DEMAND_TRANSITIONS.items():
        assert current in DEMAND_STATUSES
        for target in targets:
            assert target in DEMAND_STATUSES
            assert can_transition("demand", current, target) is True


def test_demand_transitions_illegal():
    for current in DEMAND_STATUSES:
        for target in DEMAND_STATUSES:
            if target in DEMAND_TRANSITIONS.get(current, ()):
                continue
            assert can_transition("demand", current, target) is False

    # table/current/target inválidos → False, nunca levanta.
    assert can_transition("demanda", "open", "claimed") is False
    assert can_transition("demand", "inexistente", "claimed") is False
    assert can_transition("demand", "open", "inexistente") is False


def test_artifact_transitions_legal():
    for current, targets in ARTIFACT_TRANSITIONS.items():
        assert current in ARTIFACT_STATUSES
        for target in targets:
            assert target in ARTIFACT_STATUSES
            assert can_transition("artifact", current, target) is True

    assert can_transition("artifact", "stable", "approved") is False
    assert can_transition("artifact", "draft", "approved") is False


def test_allowed_targets():
    for current, targets in DEMAND_TRANSITIONS.items():
        assert allowed_targets("demand", current) == list(targets)
    for current, targets in ARTIFACT_TRANSITIONS.items():
        assert allowed_targets("artifact", current) == list(targets)

    assert allowed_targets("artifact", "pending") == ["on user review"]
    assert allowed_targets("artifact", "inexistente") == []
    assert allowed_targets("table_invalida", "open") == []


def test_illegal_transition_exception():
    error = IllegalTransition("demand", "open", "merged")

    assert error.code == "illegal_transition"
    assert error.http_status == 409
    assert error.entity == "demand"
    assert error.current == "open"
    assert error.target == "merged"
    assert error.message == "open -> merged"


def test_error_envelope():
    payload = error_payload("empty", "não há demanda disponível", {"repo": "acme/app"})

    assert payload == {
        "error": {
            "code": "empty",
            "message": "não há demanda disponível",
            "detail": {"repo": "acme/app"},
        }
    }
    assert error_payload("x", "y")["error"]["detail"] == {}


def test_error_response_status():
    response = error_response(ApiError("empty", "não há demanda", 404))

    assert response.status_code == 404
    assert b'"empty"' in response.body


# --------------------------------------------------------------------------
# Criação de demanda — rotas reais
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_demand_open_and_event(client, auth_token, pool):
    """`POST /api/demands` cria a demanda `open` e grava `demand.created`."""
    response = await client.post(
        "/api/demands",
        json={
            "repo": "acme/app",
            "module": "login",
            "title": "login",
            "body": "preciso de login",
        },
        headers=_auth(auth_token),
    )

    assert response.status_code == 200
    demand = response.json()
    assert demand["status"] == "open"
    assert demand["repo"] == "acme/app"
    assert demand["claimed_by"] is None

    event = await pool.fetchrow(
        "SELECT * FROM events WHERE demand_id = $1 AND type = 'demand.created'",
        uuid.UUID(demand["id"]),
    )
    assert event is not None


@pytest.mark.asyncio
async def test_create_demand_empty_body_400(client, auth_token):
    """Body vazio → 400 `empty_body`."""
    response = await client.post(
        "/api/demands",
        json={"repo": "acme/app", "module": "login", "title": "login", "body": "   "},
        headers=_auth(auth_token),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "empty_body"


@pytest.mark.asyncio
async def test_get_demand_carries_artifacts_and_events(client, auth_token, pool):
    """`GET /api/demands/{id}` devolve a demanda + artefatos + eventos."""
    user_id = await _user_id(pool)
    repo_id = await pool.fetchval(
        "INSERT INTO repos (owner, name) VALUES ('acme', 'app') RETURNING id"
    )
    demand_id = await _new_demand(pool, str(repo_id), user_id)
    await pool.execute(
        """
        INSERT INTO artifacts (id, demand_id, repo_id, kind, path, status)
        VALUES ('BR-009', $1, $2, 'br', 'docs/BR/login/login.md', 'draft')
        """,
        uuid.UUID(demand_id),
        repo_id,
    )

    response = await client.get(f"/api/demands/{demand_id}", headers=_auth(auth_token))

    assert response.status_code == 200
    demand = response.json()
    assert demand["id"] == demand_id
    assert [artifact["id"] for artifact in demand["artifacts"]] == ["BR-009"]
    assert isinstance(demand["events"], list)


@pytest.mark.asyncio
async def test_get_demand_not_found_404(client, auth_token):
    response = await client.get(
        f"/api/demands/{uuid.uuid4()}", headers=_auth(auth_token)
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --------------------------------------------------------------------------
# Transições
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_start_demand_by_owner(client, auth_token, pool):
    """`claimed → in_progress` pelo dono do claim."""
    await _create_demand(client, auth_token)

    claim = await client.post(
        "/api/claims", json={"repo": "acme/app"}, headers=_auth(auth_token)
    )
    assert claim.status_code == 200
    demand_id = claim.json()["demand"]["id"]

    response = await client.post(
        f"/api/demands/{demand_id}/start", headers=_auth(auth_token)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "in_progress"


@pytest.mark.asyncio
async def test_start_demand_by_non_owner_403(client, auth_token, pool):
    """`start` por quem não é o dono do claim → 403 `not_claim_owner`."""
    from app.services import claims as claims_service

    owner_id = str(
        await pool.fetchval(
            "INSERT INTO users (github_id, login) VALUES ($1, 'dono') RETURNING id",
            uuid.uuid4().int % 10**12,
        )
    )
    repo_id = await pool.fetchval(
        "INSERT INTO repos (owner, name) VALUES ('acme', 'app') RETURNING id"
    )
    demand_id = await _new_demand(pool, str(repo_id), owner_id)
    await claims_service.claim_next(pool, repo="acme/app", user_id=owner_id)

    response = await client.post(
        f"/api/demands/{demand_id}/start", headers=_auth(auth_token)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_claim_owner"

    row = await pool.fetchrow("SELECT status FROM demands WHERE id = $1", uuid.UUID(demand_id))
    assert row["status"] == "claimed"


@pytest.mark.asyncio
async def test_release_by_non_owner_403(client, auth_token, pool):
    """Só o dono do claim libera a demanda."""
    from app.services import claims as claims_service

    owner_id = str(
        await pool.fetchval(
            "INSERT INTO users (github_id, login) VALUES ($1, 'dono') RETURNING id",
            uuid.uuid4().int % 10**12,
        )
    )
    repo_id = await pool.fetchval(
        "INSERT INTO repos (owner, name) VALUES ('acme', 'app') RETURNING id"
    )
    demand_id = await _new_demand(pool, str(repo_id), owner_id)
    await claims_service.claim_next(pool, repo="acme/app", user_id=owner_id)

    response = await client.post(
        f"/api/demands/{demand_id}/release", headers=_auth(auth_token)
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "not_claim_owner"


@pytest.mark.asyncio
async def test_release_by_owner_returns_to_open(client, auth_token, pool):
    """`release` devolve a demanda para `open` e zera o ownership."""
    await _create_demand(client, auth_token)

    claim = await client.post(
        "/api/claims", json={"repo": "acme/app"}, headers=_auth(auth_token)
    )
    demand_id = claim.json()["demand"]["id"]

    response = await client.post(
        f"/api/demands/{demand_id}/release", headers=_auth(auth_token)
    )

    assert response.status_code == 200
    released = response.json()
    assert released["status"] == "open"
    assert released["claimed_by"] is None
    assert released["claimed_at"] is None


@pytest.mark.asyncio
async def test_block_requires_reason(client, auth_token, pool):
    """Motivo vazio → 400 `reason_required`."""
    user_id = await _user_id(pool)
    repo_id = await pool.fetchval(
        "INSERT INTO repos (owner, name) VALUES ('acme', 'app') RETURNING id"
    )
    demand_id = await _new_demand(pool, str(repo_id), user_id)

    response = await client.post(
        f"/api/demands/{demand_id}/block",
        json={"reason": "   "},
        headers=_auth(auth_token),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "reason_required"


@pytest.mark.asyncio
async def test_block_reason_in_event(client, auth_token, pool):
    """O motivo vai no `payload` do evento `demand.blocked` (spec §4.1)."""
    user_id = await _user_id(pool)
    repo_id = await pool.fetchval(
        "INSERT INTO repos (owner, name) VALUES ('acme', 'app') RETURNING id"
    )
    demand_id = await _new_demand(pool, str(repo_id), user_id)

    response = await client.post(
        f"/api/demands/{demand_id}/block",
        json={"reason": "dependência externa"},
        headers=_auth(auth_token),
    )
    assert response.status_code == 200

    event = await pool.fetchrow(
        "SELECT payload FROM events WHERE demand_id = $1 AND type = 'demand.blocked'",
        uuid.UUID(demand_id),
    )
    assert event is not None
    payload = _payload(event["payload"])
    assert payload["reason"] == "dependência externa"
    assert payload["from"] == "open"
    assert payload["to"] == "blocked"


@pytest.mark.asyncio
async def test_events_recorded(client, auth_token, pool):
    """Uma linha em `events` por transição, com o `type` canônico."""
    user_id = await _user_id(pool)
    repo_id = await pool.fetchval(
        "INSERT INTO repos (owner, name) VALUES ('acme', 'app') RETURNING id"
    )
    demand_id = await _new_demand(pool, str(repo_id), user_id)

    claim = await client.post(
        "/api/claims", json={"repo": "acme/app"}, headers=_auth(auth_token)
    )
    demand_id = claim.json()["demand"]["id"]
    await client.post(f"/api/demands/{demand_id}/start", headers=_auth(auth_token))
    await client.post(
        f"/api/demands/{demand_id}/block",
        json={"reason": "travar"},
        headers=_auth(auth_token),
    )
    await client.post(f"/api/demands/{demand_id}/release", headers=_auth(auth_token))

    types = await pool.fetch(
        "SELECT type FROM events WHERE demand_id = $1 ORDER BY at ASC, id ASC",
        uuid.UUID(demand_id),
    )
    assert [row["type"] for row in types] == [
        "demand.claimed",
        "demand.started",
        "demand.blocked",
        "demand.released",
    ]


@pytest.mark.asyncio
async def test_merge_requires_review(client, auth_token, pool):
    """Sem review → 409 `review_required`; review blocking → 409 `review_blocking`."""
    user_id = await _user_id(pool)
    repo_id = await pool.fetchval(
        "INSERT INTO repos (owner, name) VALUES ('acme', 'app') RETURNING id"
    )
    demand_id = await _new_demand(pool, str(repo_id), user_id)
    await pool.execute(
        "UPDATE demands SET status = 'review' WHERE id = $1", uuid.UUID(demand_id)
    )

    response = await client.post(
        f"/api/demands/{demand_id}/merge", headers=_auth(auth_token)
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "review_required"

    await pool.execute(
        "INSERT INTO reviews (demand_id, verdict) VALUES ($1, 'blocking')",
        uuid.UUID(demand_id),
    )
    response = await client.post(
        f"/api/demands/{demand_id}/merge", headers=_auth(auth_token)
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "review_blocking"


@pytest.mark.asyncio
async def test_merge_with_clean_review(client, auth_token, pool):
    """Review `clean` → `review → merged`."""
    user_id = await _user_id(pool)
    repo_id = await pool.fetchval(
        "INSERT INTO repos (owner, name) VALUES ('acme', 'app') RETURNING id"
    )
    demand_id = await _new_demand(pool, str(repo_id), user_id)
    await pool.execute(
        "UPDATE demands SET status = 'review' WHERE id = $1", uuid.UUID(demand_id)
    )
    await pool.execute(
        "INSERT INTO reviews (demand_id, verdict) VALUES ($1, 'clean')",
        uuid.UUID(demand_id),
    )

    response = await client.post(
        f"/api/demands/{demand_id}/merge", headers=_auth(auth_token)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "merged"


@pytest.mark.asyncio
async def test_illegal_transition_via_api(client, auth_token, pool):
    """`merge` em demanda `open` → 409 `illegal_transition`."""
    user_id = await _user_id(pool)
    repo_id = await pool.fetchval(
        "INSERT INTO repos (owner, name) VALUES ('acme', 'app') RETURNING id"
    )
    demand_id = await _new_demand(pool, str(repo_id), user_id)

    response = await client.post(
        f"/api/demands/{demand_id}/merge", headers=_auth(auth_token)
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "illegal_transition"
    assert error["message"] == "open -> merged"
