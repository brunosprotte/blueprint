"""Claim atômico da fila — o teste mais importante da F4 (design master §20).

N corrotinas disputando a mesma demanda: exatamente uma vence.

Este arquivo carrega também o **harness** usado por `test_lifecycle.py` e
`test_sync.py`: o core do F1 (`app/db.py`, `app/auth.py`) e o linter do F2
(`app/lint/runner.py`) ainda não existem neste worktree, então o harness
injeta doubles mínimos desses módulos e fala com o Postgres real num schema
próprio (`f4_test`), com o bootstrap do F1 copiado de `public` e as migrations
002/003/004 da F4 aplicadas.

ponytail: quando o core do F1 e o linter do F2 existirem, trocar os doubles
pela fixture `pool` do `conftest.py` do F1 e pelo linter real.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import types
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

DSN = os.environ.get("SDD_DATABASE_URL", "postgresql://sdd:sdd@localhost:5432/sdd")
MIGRATIONS_DIR = SERVER_ROOT / "migrations"
SCHEMA = "f4_test"

# Tabelas do bootstrap do F1 (design master §8).
BOOTSTRAP_TABLES = (
    "users",
    "tokens",
    "repos",
    "demands",
    "artifacts",
    "spec_edges",
    "doubts",
    "commits",
    "reviews",
    "chunks",
    "events",
    "sessions",
)


# --------------------------------------------------------------------------
# Doubles do core (F1) e do linter (F2)
# --------------------------------------------------------------------------
def install_core_doubles() -> None:
    """Double de `app.db` + `app.auth` — o core do F1 ainda não existe."""
    if getattr(sys.modules.get("app.db"), "_f4_double", False):
        return

    db = types.ModuleType("app.db")
    db._f4_double = True
    db.POOL = None

    async def get_pool():
        return db.POOL

    async def fetch(pool, query, *args):
        return await pool.fetch(query, *args)

    async def fetchrow(pool, query, *args):
        return await pool.fetchrow(query, *args)

    async def fetchval(pool, query, *args):
        return await pool.fetchval(query, *args)

    async def execute(pool, query, *args):
        return await pool.execute(query, *args)

    db.get_pool = get_pool
    db.fetch = fetch
    db.fetchrow = fetchrow
    db.fetchval = fetchval
    db.execute = execute
    sys.modules["app.db"] = db

    auth = types.ModuleType("app.auth")
    auth._f4_double = True

    @dataclass(frozen=True)
    class User:
        id: str
        github_id: int = 0
        login: str = "dev"
        email: str | None = None
        avatar_url: str | None = None

    @dataclass(frozen=True)
    class Token:
        id: str = ""
        user_id: str = ""
        repo_id: str | None = None
        scopes: tuple[str, ...] = ()

    async def require_user(request):
        return User(id=str(uuid.uuid4()))

    def require_scope(scope: str):
        async def dependency(request):
            return None

        return dependency

    async def current_repo(request):
        return None

    auth.User = User
    auth.Token = Token
    auth.require_user = require_user
    auth.require_scope = require_scope
    auth.current_repo = current_repo
    sys.modules["app.auth"] = auth


LINT_BEHAVIOUR: dict = {"findings": ()}


def install_lint_double() -> None:
    """Double do linter do F2 — os findings saem de `runner.LINT_BEHAVIOUR`."""
    if getattr(sys.modules.get("app.lint.runner"), "_f4_double", False):
        return

    lint_pkg = types.ModuleType("app.lint")
    lint_pkg.__path__ = []
    runner = types.ModuleType("app.lint.runner")
    runner._f4_double = True

    @dataclass
    class Finding:
        rule: str
        severity: str
        message: str
        path: str | None = None
        line: int | None = None
        detail: dict = field(default_factory=dict)

    @dataclass
    class ArtifactDoc:
        path: str
        content: str
        frontmatter: dict
        body: str
        kind: str | None = None
        repo_id: str | None = None

    class MethodCorpus:
        def __init__(self, root):
            self.root = root

        def exists(self, ref):
            return False

        def resolve(self, ref):
            return None

    class SyncedArtifacts:
        def __init__(self, pool):
            self.pool = pool

        def exists(self, ref):
            return False

        def resolve(self, ref):
            return None

    class CompositeUniverse:
        def __init__(self, *parts):
            self.parts = parts

        def exists(self, ref):
            return any(part.exists(ref) for part in self.parts)

        def resolve(self, ref):
            for part in self.parts:
                resolved = part.resolve(ref)
                if resolved:
                    return resolved
            return None

    def lint_document(doc, universe):
        findings = runner.LINT_BEHAVIOUR["findings"]
        return list(findings(doc) if callable(findings) else findings)

    runner.Finding = Finding
    runner.ArtifactDoc = ArtifactDoc
    runner.MethodCorpus = MethodCorpus
    runner.SyncedArtifacts = SyncedArtifacts
    runner.CompositeUniverse = CompositeUniverse
    runner.lint_document = lint_document
    runner.LINT_BEHAVIOUR = LINT_BEHAVIOUR
    lint_pkg.runner = runner
    sys.modules["app.lint"] = lint_pkg
    sys.modules["app.lint.runner"] = runner


install_core_doubles()
install_lint_double()

from app.services import claims as claims_service  # noqa: E402
from app.services.lifecycle import ApiError  # noqa: E402


# --------------------------------------------------------------------------
# Banco
# --------------------------------------------------------------------------
@pytest_asyncio.fixture
async def pool():
    """Postgres real, schema próprio, bootstrap do F1 + migrations da F4."""
    try:
        admin = await asyncpg.connect(DSN)
    except Exception as exc:  # pragma: no cover - depende do ambiente
        pytest.skip(f"postgres indisponível: {exc}")

    try:
        missing = [
            table
            for table in BOOTSTRAP_TABLES
            if not await admin.fetchval(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = $1",
                table,
            )
        ]
        if missing:
            pytest.skip(f"bootstrap do F1 ausente no schema public: {missing}")

        await admin.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        await admin.execute(f'CREATE SCHEMA "{SCHEMA}"')
        for table in BOOTSTRAP_TABLES:
            await admin.execute(
                f'CREATE TABLE "{SCHEMA}"."{table}" '
                f'(LIKE public."{table}" INCLUDING ALL)'
            )
    finally:
        await admin.close()

    test_pool = await asyncpg.create_pool(
        DSN,
        server_settings={"search_path": SCHEMA},
        min_size=1,
        max_size=16,
    )
    try:
        for path in sorted(MIGRATIONS_DIR.glob("00[234]_*.sql")):
            await test_pool.execute(path.read_text(encoding="utf-8"))
        sys.modules["app.db"].POOL = test_pool
        yield test_pool
    finally:
        await test_pool.close()
        cleanup = await asyncpg.connect(DSN)
        await cleanup.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}" CASCADE')
        await cleanup.close()


async def new_user(pool, login: str = "dev") -> str:
    row = await pool.fetchrow(
        "INSERT INTO users (github_id, login) VALUES ($1, $2) RETURNING id",
        uuid.uuid4().int % 10**12,
        login,
    )
    return str(row["id"])


async def new_repo(pool, owner: str = "acme", name: str = "app") -> str:
    row = await pool.fetchrow(
        "INSERT INTO repos (owner, name) VALUES ($1, $2) RETURNING id",
        owner,
        name,
    )
    return str(row["id"])


async def new_demand(pool, repo_id: str, created_by: str, title: str = "demanda") -> str:
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


# --------------------------------------------------------------------------
# Testes
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_claim_single_winner(pool):
    """8 corrotinas disputando 1 demanda → 1 vencedora, 7 com fila vazia."""
    creator = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await new_demand(pool, repo_id, creator)

    users = [await new_user(pool, f"agente-{index}") for index in range(8)]

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
    user_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await new_demand(pool, repo_id, user_id)

    claimed = await claims_service.claim_next(pool, repo="acme/app", user_id=user_id)

    assert claimed["id"] == demand_id
    assert claimed["status"] == "claimed"
    assert claimed["claimed_by"] == user_id
    assert claimed["claimed_at"] is not None


@pytest.mark.asyncio
async def test_claim_event(pool):
    user_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await new_demand(pool, repo_id, user_id)

    await claims_service.claim_next(pool, repo="acme/app", user_id=user_id)

    event = await pool.fetchrow(
        "SELECT * FROM events WHERE demand_id = $1 AND type = 'demand.claimed'",
        uuid.UUID(demand_id),
    )
    assert event is not None
    payload = json.loads(event["payload"]) if isinstance(event["payload"], str) else event["payload"]
    assert payload["repo"] == "acme/app"
    assert payload["claimed_by"] == user_id


@pytest.mark.asyncio
async def test_claim_empty_queue(pool):
    user_id = await new_user(pool)
    await new_repo(pool)

    assert await claims_service.claim_next(pool, repo="acme/app", user_id=user_id) is None


@pytest.mark.asyncio
async def test_claim_skips_locked_row(pool):
    """Linha travada por outra transação → o claim pega a próxima."""
    user_id = await new_user(pool)
    repo_id = await new_repo(pool)
    first = await new_demand(pool, repo_id, user_id, title="primeira")
    second = await new_demand(pool, repo_id, user_id, title="segunda")

    async with pool.acquire() as locker:
        async with locker.transaction():
            await locker.execute(
                "SELECT id FROM demands WHERE id = $1 FOR UPDATE", uuid.UUID(first)
            )
            claimed = await claims_service.claim_next(pool, repo="acme/app", user_id=user_id)

    assert claimed["id"] == second
    assert claimed["id"] != first


@pytest.mark.asyncio
async def test_claims_route_release_absent(pool):
    """`POST /api/claims/{id}/release` não existe (contrato §8.2)."""
    from app.routers import claims as claims_router

    paths = {route.path for route in claims_router.router.routes}
    assert "/claims" in paths
    assert not any("release" in path for path in paths), paths


@pytest.mark.asyncio
async def test_current_claim(pool):
    user_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await new_demand(pool, repo_id, user_id)

    assert await claims_service.current_claim(pool, user_id=user_id, repo="acme/app") is None

    await claims_service.claim_next(pool, repo="acme/app", user_id=user_id)

    current = await claims_service.current_claim(pool, user_id=user_id, repo="acme/app")
    assert current["id"] == demand_id
    assert current["status"] == "claimed"


@pytest.mark.asyncio
async def test_claim_empty_queue_is_404_empty(pool):
    """A fila vazia vira 404 `empty` no router (contrato §3)."""
    from app.routers import claims as claims_router

    user_id = await new_user(pool)
    await new_repo(pool)

    class _Request:
        headers: dict = {}

    response = await claims_router.claim(
        request=_Request(),
        body=claims_router.ClaimBody(repo="acme/app"),
        user=sys.modules["app.auth"].User(id=user_id),
    )

    assert response.status_code == 404
    assert b'"empty"' in response.body


@pytest.mark.asyncio
async def test_claim_invalid_repo_400(pool):
    """Repo malformado → 400 `invalid_repo`."""
    with pytest.raises(ApiError) as excinfo:
        await claims_service.claim_next(pool, repo="sem-slash", user_id=str(uuid.uuid4()))

    assert excinfo.value.code == "invalid_repo"
    assert excinfo.value.status == 400
