"""Ciclo de vida — máquina de estados e transições de demanda (spec §7).

A primeira parte é lógica pura (roda sem banco). A segunda exercita as
transições contra o Postgres real, reaproveitando o harness de
`test_claim.py` (doubles do core do F1 + schema de teste próprio).
"""

from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))


def _load_sibling(name: str):
    """Carrega o módulo irmão pelo caminho — independe de `__init__.py`."""
    path = Path(__file__).with_name(name)
    spec = importlib.util.spec_from_file_location(f"f4_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


harness = _load_sibling("test_claim.py")

pool = harness.pool
new_user = harness.new_user
new_repo = harness.new_repo

from app.services.lifecycle import (  # noqa: E402
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
# Transições — contra o Postgres
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_illegal_transition_via_api(pool):
    """`merge` em demanda `open` → 409 `illegal_transition`."""
    from app.routers import demands as demands_router

    user_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, user_id)

    response = await demands_router.merge_demand(
        demand_id=demand_id,
        user=sys.modules["app.auth"].User(id=user_id),
    )

    assert response.status_code == 409
    assert b'"illegal_transition"' in response.body
    assert b'"open -&gt; merged"' in response.body or b'"open -> merged"' in response.body


@pytest.mark.asyncio
async def test_block_requires_reason(pool):
    """Motivo vazio → 400 `reason_required`."""
    from app.routers import demands as demands_router

    user_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, user_id)

    response = await demands_router.block_demand(
        demand_id=demand_id,
        body=demands_router.BlockDemandBody(reason="   "),
        user=sys.modules["app.auth"].User(id=user_id),
    )

    assert response.status_code == 400
    assert b'"reason_required"' in response.body


@pytest.mark.asyncio
async def test_block_reason_in_event(pool):
    """O motivo vai no `payload` do evento `demand.blocked` (spec §4.1)."""
    from app.services import demands as demands_service

    user_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, user_id)

    await demands_service.block_demand(
        pool, demand_id=demand_id, reason="dependência externa", actor_id=user_id
    )

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
async def test_release_by_non_owner_403(pool):
    """Só o dono do claim libera a demanda (spec §4.1)."""
    from app.services import claims as claims_service
    from app.services import demands as demands_service

    owner_id = await new_user(pool)
    other_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, owner_id)
    await claims_service.claim_next(pool, repo="acme/app", user_id=owner_id)

    with pytest.raises(ApiError) as excinfo:
        await demands_service.release_demand(pool, demand_id=demand_id, actor_id=other_id)

    assert excinfo.value.code == "not_claim_owner"
    assert excinfo.value.status == 403


@pytest.mark.asyncio
async def test_release_by_owner_returns_to_open(pool):
    """`release` devolve a demanda para `open` e zera o ownership."""
    from app.services import claims as claims_service
    from app.services import demands as demands_service

    owner_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, owner_id)
    await claims_service.claim_next(pool, repo="acme/app", user_id=owner_id)

    released = await demands_service.release_demand(
        pool, demand_id=demand_id, actor_id=owner_id
    )

    assert released["status"] == "open"
    assert released["claimed_by"] is None
    assert released["claimed_at"] is None


@pytest.mark.asyncio
async def test_events_recorded(pool):
    """Uma linha em `events` por transição, com o `type` canônico."""
    from app.services import claims as claims_service
    from app.services import demands as demands_service

    user_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, user_id)

    await claims_service.claim_next(pool, repo="acme/app", user_id=user_id)
    await demands_service.start_demand(pool, demand_id=demand_id, actor_id=user_id)
    await demands_service.block_demand(
        pool, demand_id=demand_id, reason="travar", actor_id=user_id
    )
    await demands_service.release_demand(pool, demand_id=demand_id, actor_id=user_id)

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
async def test_merge_requires_review(pool):
    """Sem review → 409 `review_required`; review blocking → 409 `review_blocking`."""
    from app.services import demands as demands_service

    user_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, user_id)
    await pool.execute(
        "UPDATE demands SET status = 'review' WHERE id = $1", uuid.UUID(demand_id)
    )

    with pytest.raises(ApiError) as excinfo:
        await demands_service.merge_demand(pool, demand_id=demand_id, actor_id=user_id)
    assert excinfo.value.code == "review_required"

    await pool.execute(
        "INSERT INTO reviews (demand_id, verdict) VALUES ($1, 'blocking')", uuid.UUID(demand_id)
    )
    with pytest.raises(ApiError) as excinfo:
        await demands_service.merge_demand(pool, demand_id=demand_id, actor_id=user_id)
    assert excinfo.value.code == "review_blocking"


@pytest.mark.asyncio
async def test_merge_with_clean_review(pool):
    """Review `clean` → `review → merged`."""
    from app.services import demands as demands_service

    user_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, user_id)
    await pool.execute(
        "UPDATE demands SET status = 'review' WHERE id = $1", uuid.UUID(demand_id)
    )
    await pool.execute(
        "INSERT INTO reviews (demand_id, verdict) VALUES ($1, 'clean')", uuid.UUID(demand_id)
    )

    merged = await demands_service.merge_demand(pool, demand_id=demand_id, actor_id=user_id)

    assert merged["status"] == "merged"


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


def _payload(value) -> dict:
    import json

    return json.loads(value) if isinstance(value, str) else value


class _Request:
    headers: dict = {}


# --------------------------------------------------------------------------
# Criação e consulta de demanda
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_create_demand_open_and_event(pool):
    """`POST /api/demands` cria a demanda `open` e grava `demand.created`."""
    from app.routers import demands as demands_router

    user_id = await new_user(pool)
    await new_repo(pool)

    response = await demands_router.create_demand(
        request=_Request(),
        body=demands_router.CreateDemandBody(
            repo="acme/app", module="login", title="login", body="preciso de login"
        ),
        user=sys.modules["app.auth"].User(id=user_id),
    )

    assert response["status"] == "open"
    assert response["repo"] == "acme/app"
    assert response["claimed_by"] is None

    event = await pool.fetchrow(
        "SELECT * FROM events WHERE demand_id = $1 AND type = 'demand.created'",
        uuid.UUID(response["id"]),
    )
    assert event is not None


@pytest.mark.asyncio
async def test_create_demand_empty_body_400(pool):
    """Body vazio → 400 `empty_body`."""
    from app.routers import demands as demands_router

    user_id = await new_user(pool)
    await new_repo(pool)

    response = await demands_router.create_demand(
        request=_Request(),
        body=demands_router.CreateDemandBody(
            repo="acme/app", module="login", title="login", body="   "
        ),
        user=sys.modules["app.auth"].User(id=user_id),
    )

    assert response.status_code == 400
    assert b'"empty_body"' in response.body


@pytest.mark.asyncio
async def test_start_demand_by_non_owner_403(pool):
    """`start` por quem não é o dono do claim → 403 `not_claim_owner`."""
    from app.services import claims as claims_service
    from app.services import demands as demands_service

    owner_id = await new_user(pool)
    other_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, owner_id)
    await claims_service.claim_next(pool, repo="acme/app", user_id=owner_id)

    with pytest.raises(ApiError) as excinfo:
        await demands_service.start_demand(pool, demand_id=demand_id, actor_id=other_id)

    assert excinfo.value.code == "not_claim_owner"
    assert excinfo.value.status == 403

    row = await pool.fetchrow("SELECT status FROM demands WHERE id = $1", uuid.UUID(demand_id))
    assert row["status"] == "claimed"


@pytest.mark.asyncio
async def test_start_demand_by_owner(pool):
    """`claimed → in_progress` pelo dono do claim."""
    from app.services import claims as claims_service
    from app.services import demands as demands_service

    owner_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, owner_id)
    await claims_service.claim_next(pool, repo="acme/app", user_id=owner_id)

    started = await demands_service.start_demand(
        pool, demand_id=demand_id, actor_id=owner_id
    )

    assert started["status"] == "in_progress"


@pytest.mark.asyncio
async def test_get_demand_carries_artifacts_and_events(pool):
    """`GET /api/demands/{id}` devolve a demanda + artefatos + eventos."""
    from app.services import demands as demands_service

    user_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, user_id)
    await pool.execute(
        """
        INSERT INTO artifacts (id, demand_id, repo_id, kind, path, status)
        VALUES ('BR-009', $1, $2, 'br', 'docs/BR/login/login.md', 'draft')
        """,
        uuid.UUID(demand_id),
        uuid.UUID(repo_id),
    )

    demand = await demands_service.get_demand(pool, demand_id)

    assert demand["id"] == demand_id
    assert [artifact["id"] for artifact in demand["artifacts"]] == ["BR-009"]
    assert isinstance(demand["events"], list)
