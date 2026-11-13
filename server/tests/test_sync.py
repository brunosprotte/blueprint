"""Sync repo→servidor, registro de commits e reconcile (spec §5.1–§5.8).

Reaproveita o harness de `test_claim.py` (doubles do core do F1 + schema de
teste próprio). O linter do F2 é um double: os findings saem de
`harness.LINT_BEHAVIOUR`.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
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

from app.services import artifacts as artifacts_service  # noqa: E402
from app.services import claims as claims_service  # noqa: E402
from app.services import commits as commits_service  # noqa: E402
from app.services import demands as demands_service  # noqa: E402
from app.services.lifecycle import ApiError  # noqa: E402

BR_CONTENT = """---
id: BR-001
module: login
feature: login
status: draft
version: 1.0.0
---

# Login

Requisito de login.
"""

RI_CONTENT = """---
id: RI-001
module: login
feature: login
status: draft
version: 1.0.0
---

# RI — Login

Plano de teste.
"""

SPEC_CONTENT = """---
id: SPEC-001
module: login
feature: login
status: draft
version: 1.0.0
createdFrom: BR-001
dependsOn: [BR-001]
tests: [RI-001]
---

# SPEC — Login

Especificação.
"""


@dataclass
class _Finding:
    rule: str
    severity: str
    message: str


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
    return json.loads(value) if isinstance(value, str) else value


# --------------------------------------------------------------------------
# Sync
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sync_creates_artifact_draft(pool):
    """BR nova nasce `draft`, com arquivo de dúvidas espelhado (spec §5.2)."""
    await new_repo(pool)

    result = await artifacts_service.sync(
        pool,
        repo="acme/app",
        docs=[{"path": "docs/BR/login/login.md", "content": BR_CONTENT}],
        actor_id=None,
    )

    assert result["summary"]["created"] == 1
    assert result["summary"]["artifacts"] == 1

    row = await pool.fetchrow(
        "SELECT * FROM artifacts WHERE path = 'docs/BR/login/login.md'"
    )
    assert row["id"] == "BR-001"
    assert row["status"] == "draft"
    assert row["kind"] == "br"
    assert row["module"] == "login"
    assert row["version"] == "1.0.0"
    assert row["doubts_index"] == "docs/implementation-artifacts/duvidas-br/BR-001.md"
    assert "Nenhuma pendência registrada" in row["doubts_content"]

    # A tabela `doubts` não recebe linha no nascimento (decisão D6).
    doubts = await pool.fetch("SELECT * FROM doubts WHERE artifact_id = 'BR-001'")
    assert doubts == []


@pytest.mark.asyncio
async def test_sync_promotes_when_sha_matches(pool):
    """Mesmo sha do servidor → `draft → pending` + evento `artifact.promoted`."""
    await new_repo(pool)
    docs = [{"path": "docs/BR/login/login.md", "content": BR_CONTENT}]

    await artifacts_service.sync(pool, repo="acme/app", docs=docs, actor_id=None)
    result = await artifacts_service.sync(pool, repo="acme/app", docs=docs, actor_id=None)

    assert result["summary"]["promoted"] == 1

    row = await pool.fetchrow("SELECT * FROM artifacts WHERE id = 'BR-001'")
    assert row["status"] == "pending"

    event = await pool.fetchrow(
        "SELECT * FROM events WHERE artifact_id = 'BR-001' AND type = 'artifact.promoted'"
    )
    assert event is not None
    assert _payload(event["payload"])["from"] == "draft"
    assert _payload(event["payload"])["to"] == "pending"


@pytest.mark.asyncio
async def test_sync_409_on_divergence(pool):
    """Sha divergente em `draft` → 409 e nada persistido (spec §5.6)."""
    await new_repo(pool)
    await artifacts_service.sync(
        pool,
        repo="acme/app",
        docs=[{"path": "docs/BR/login/login.md", "content": BR_CONTENT}],
        actor_id=None,
    )

    other = {"path": "docs/BR/login/outra.md", "content": RI_CONTENT}
    diverged = {"path": "docs/BR/login/login.md", "content": BR_CONTENT + "\noutro\n"}

    with pytest.raises(ApiError) as excinfo:
        await artifacts_service.sync(
            pool, repo="acme/app", docs=[diverged, other], actor_id=None
        )

    error = excinfo.value
    assert error.code == "content_diverged"
    assert error.status == 409
    assert error.detail["server_sha"] != error.detail["client_sha"]
    assert error.detail["path"] == "docs/BR/login/login.md"

    # Nada do lote foi aplicado.
    rows = await pool.fetch("SELECT path FROM artifacts ORDER BY path")
    assert [row["path"] for row in rows] == ["docs/BR/login/login.md"]


@pytest.mark.asyncio
async def test_sync_idempotent(pool):
    """Sync repetido → mesma linha, mesma versão, nenhum evento novo."""
    await new_repo(pool)
    docs = [{"path": "docs/BR/login/login.md", "content": BR_CONTENT}]

    await artifacts_service.sync(pool, repo="acme/app", docs=docs, actor_id=None)
    await artifacts_service.sync(pool, repo="acme/app", docs=docs, actor_id=None)

    before = await pool.fetchval("SELECT count(*) FROM events")
    version_before = await pool.fetchval("SELECT version FROM artifacts WHERE id = 'BR-001'")

    await artifacts_service.sync(pool, repo="acme/app", docs=docs, actor_id=None)

    after = await pool.fetchval("SELECT count(*) FROM events")
    rows = await pool.fetch("SELECT * FROM artifacts WHERE id = 'BR-001'")
    assert len(rows) == 1
    assert after == before
    assert rows[0]["version"] == version_before
    assert rows[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_sync_lint_error_blocks_promotion(pool, monkeypatch):
    """Finding `error` → o artefato fica em `draft` (spec §5.3, decisão D4)."""
    await new_repo(pool)
    monkeypatch.setitem(
        sys.modules["app.lint.runner"].LINT_BEHAVIOUR,
        "findings",
        lambda doc: [_Finding("LINK-001", "error", "link quebrado")],
    )

    docs = [{"path": "docs/BR/login/login.md", "content": BR_CONTENT}]
    await artifacts_service.sync(pool, repo="acme/app", docs=docs, actor_id=None)
    result = await artifacts_service.sync(pool, repo="acme/app", docs=docs, actor_id=None)

    assert result["summary"]["promoted"] == 0
    assert result["summary"]["lint_error"] == 1

    row = await pool.fetchrow("SELECT status FROM artifacts WHERE id = 'BR-001'")
    assert row["status"] == "draft"


@pytest.mark.asyncio
async def test_sync_ignores_non_artifact_paths(pool):
    """Path fora de BR/SPEC/RI → `summary.ignored` (spec §5.1)."""
    await new_repo(pool)

    result = await artifacts_service.sync(
        pool,
        repo="acme/app",
        docs=[
            {"path": "README.md", "content": "# repo"},
            {"path": "AGENTS.md", "content": "# agentes"},
        ],
        actor_id=None,
    )

    assert result["summary"]["ignored"] == 2
    assert result["summary"]["artifacts"] == 0
    assert result["artifacts"] == []


@pytest.mark.asyncio
async def test_sync_status_source_is_db(pool):
    """Frontmatter com `status` diferente não muda `artifacts.status` (spec §5.7)."""
    await new_repo(pool)
    content = BR_CONTENT.replace("status: draft", "status: stable")

    await artifacts_service.sync(
        pool,
        repo="acme/app",
        docs=[{"path": "docs/BR/login/login.md", "content": content}],
        actor_id=None,
    )

    row = await pool.fetchrow("SELECT status FROM artifacts WHERE id = 'BR-001'")
    assert row["status"] == "draft"

    event = await pool.fetchrow(
        "SELECT payload FROM events WHERE artifact_id = 'BR-001' AND type = 'artifact.synced'"
    )
    assert _payload(event["payload"])["frontmatter_status"] == "stable"


@pytest.mark.asyncio
async def test_sync_creates_graph_edges(pool):
    """`createdFrom`/`dependsOn`/`tests` viram arestas em `spec_edges` (spec §5.8)."""
    await new_repo(pool)

    await artifacts_service.sync(
        pool,
        repo="acme/app",
        docs=[
            {"path": "docs/BR/login/login.md", "content": BR_CONTENT},
            {"path": "docs/RI/login/login.md", "content": RI_CONTENT},
            {"path": "docs/SPEC/login/login.md", "content": SPEC_CONTENT},
        ],
        actor_id=None,
    )

    edges = await pool.fetch(
        "SELECT child_id, type FROM spec_edges WHERE parent_id = 'SPEC-001' ORDER BY type"
    )
    assert [(row["child_id"], row["type"]) for row in edges] == [
        ("BR-001", "depends_on"),
        ("BR-001", "derives_from"),
        ("RI-001", "tests"),
    ]


@pytest.mark.asyncio
async def test_sync_creates_doubts_file_on_birth(pool):
    """O arquivo de dúvidas é criado no nascimento, espelhado no banco."""
    await new_repo(pool)

    await artifacts_service.sync(
        pool,
        repo="acme/app",
        docs=[{"path": "docs/BR/login/login.md", "content": BR_CONTENT}],
        actor_id=None,
    )

    row = await pool.fetchrow("SELECT doubts_content FROM artifacts WHERE id = 'BR-001'")
    assert "artifact: BR-001" in row["doubts_content"]
    assert "artifactStatus: draft" in row["doubts_content"]


# --------------------------------------------------------------------------
# Commits
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_commit_recorded_idempotent(pool):
    """Mesmo `(repo_id, sha)` → mesmo `id`, `created: false`, 1 linha."""
    user_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, user_id)

    first = await commits_service.record_commit(
        pool,
        repo="acme/app",
        sha="a1b2c3d",
        message="feat: login",
        branch="main",
        files=[{"path": "src/auth.ts", "additions": 12, "deletions": 3}],
        demand_id=demand_id,
        actor_id=user_id,
    )
    second = await commits_service.record_commit(
        pool,
        repo="acme/app",
        sha="a1b2c3d",
        message="feat: login",
        branch="main",
        files=[{"path": "src/auth.ts", "additions": 12, "deletions": 3}],
        demand_id=demand_id,
        actor_id=user_id,
    )

    assert first["created"] is True
    assert second["created"] is False
    assert first["id"] == second["id"]
    assert first["files"] == [{"path": "src/auth.ts", "additions": 12, "deletions": 3}]
    assert first["status"] == "present"

    count = await pool.fetchval("SELECT count(*) FROM commits WHERE sha = 'a1b2c3d'")
    assert count == 1

    events = await pool.fetch(
        "SELECT * FROM events WHERE demand_id = $1 AND type = 'commit.recorded'",
        uuid.UUID(demand_id),
    )
    assert len(events) == 1


@pytest.mark.asyncio
async def test_commit_invalid_sha_400(pool):
    """Sha fora de `^[0-9a-f]{7,40}$` → 400 `invalid_sha`."""
    user_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, user_id)

    with pytest.raises(ApiError) as excinfo:
        await commits_service.record_commit(
            pool,
            repo="acme/app",
            sha="ZZZZ",
            message="x",
            branch="main",
            files=[],
            demand_id=demand_id,
            actor_id=user_id,
        )

    assert excinfo.value.code == "invalid_sha"
    assert excinfo.value.status == 400


@pytest.mark.asyncio
async def test_commit_unknown_demand_404(pool):
    """Demanda inexistente → 404 `demand_not_found`."""
    user_id = await new_user(pool)
    await new_repo(pool)

    with pytest.raises(ApiError) as excinfo:
        await commits_service.record_commit(
            pool,
            repo="acme/app",
            sha="a1b2c3d",
            message="x",
            branch="main",
            files=[],
            demand_id=str(uuid.uuid4()),
            actor_id=user_id,
        )

    assert excinfo.value.code == "demand_not_found"
    assert excinfo.value.status == 404


@pytest.mark.asyncio
async def test_list_commits_omits_orphaned(pool):
    """`GET /api/commits` omite `orphaned` por padrão (spec §4.4)."""
    user_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, user_id)

    await commits_service.record_commit(
        pool,
        repo="acme/app",
        sha="a1b2c3d",
        message="feat: login",
        branch="main",
        files=[],
        demand_id=demand_id,
        actor_id=user_id,
    )
    await pool.execute("UPDATE commits SET status = 'orphaned' WHERE sha = 'a1b2c3d'")

    visible = await commits_service.list_commits(pool, demand_id=demand_id, repo=None)
    assert visible == []

    everything = await commits_service.list_commits(
        pool, demand_id=demand_id, repo=None, include_orphaned=True
    )
    assert len(everything) == 1
    assert everything[0]["status"] == "orphaned"


# --------------------------------------------------------------------------
# Reconcile
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_reconcile_marks_orphaned(pool, monkeypatch):
    """Sha ausente do remoto → `status='orphaned'` (spec §5.5)."""
    user_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, user_id)

    await commits_service.record_commit(
        pool,
        repo="acme/app",
        sha="a1b2c3d",
        message="feat: login",
        branch="main",
        files=[],
        demand_id=demand_id,
        actor_id=user_id,
    )

    async def fake_shas(owner, name, branch):
        return ["9999999"]

    monkeypatch.setattr(demands_service, "_github_shas", fake_shas)

    result = await demands_service.reconcile_demand(
        pool, demand_id=demand_id, branch="main", actor_id=user_id
    )

    assert result["orphaned"] == ["a1b2c3d"]
    assert result["kept"] == []

    row = await pool.fetchrow("SELECT status FROM commits WHERE sha = 'a1b2c3d'")
    assert row["status"] == "orphaned"

    event = await pool.fetchrow(
        "SELECT * FROM events WHERE demand_id = $1 AND type = 'demand.reconciled'",
        uuid.UUID(demand_id),
    )
    assert event is not None


@pytest.mark.asyncio
async def test_reconcile_github_down_503(pool, monkeypatch):
    """GitHub fora → 503 `github_unavailable` + evento, sem marcar orphaned."""
    user_id = await new_user(pool)
    repo_id = await new_repo(pool)
    demand_id = await _new_demand(pool, repo_id, user_id)

    await commits_service.record_commit(
        pool,
        repo="acme/app",
        sha="a1b2c3d",
        message="feat: login",
        branch="main",
        files=[],
        demand_id=demand_id,
        actor_id=user_id,
    )

    async def broken(owner, name, branch):
        raise httpx.ConnectError("sem rede")

    monkeypatch.setattr(demands_service, "_github_shas", broken)

    with pytest.raises(ApiError) as excinfo:
        await demands_service.reconcile_demand(
            pool, demand_id=demand_id, branch="main", actor_id=user_id
        )

    assert excinfo.value.code == "github_unavailable"
    assert excinfo.value.status == 503

    row = await pool.fetchrow("SELECT status FROM commits WHERE sha = 'a1b2c3d'")
    assert row["status"] == "present"

    event = await pool.fetchrow(
        "SELECT * FROM events WHERE demand_id = $1 AND type = 'demand.reconcile_failed'",
        uuid.UUID(demand_id),
    )
    assert event is not None


# --------------------------------------------------------------------------
# Transições de artefato
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_request_review_open_doubts_409(pool):
    """Dúvida `pending` → 409 `open_doubts` (spec §4.3)."""
    await new_repo(pool)
    docs = [{"path": "docs/BR/login/login.md", "content": BR_CONTENT}]
    await artifacts_service.sync(pool, repo="acme/app", docs=docs, actor_id=None)
    await artifacts_service.sync(pool, repo="acme/app", docs=docs, actor_id=None)

    await pool.execute(
        "INSERT INTO doubts (artifact_id, question, status, source) "
        "VALUES ('BR-001', 'dúvida aberta', 'pending', 'reviewer')"
    )

    with pytest.raises(ApiError) as excinfo:
        await artifacts_service.request_review(
            pool, artifact_id="BR-001", actor_id=str(uuid.uuid4())
        )

    assert excinfo.value.code == "open_doubts"
    assert excinfo.value.status == 409


@pytest.mark.asyncio
async def test_request_review_promotes(pool):
    """Sem dúvida pendente → `pending → on user review`."""
    await new_repo(pool)
    docs = [{"path": "docs/BR/login/login.md", "content": BR_CONTENT}]
    await artifacts_service.sync(pool, repo="acme/app", docs=docs, actor_id=None)
    await artifacts_service.sync(pool, repo="acme/app", docs=docs, actor_id=None)

    result = await artifacts_service.request_review(
        pool, artifact_id="BR-001", actor_id=str(uuid.uuid4())
    )

    assert result["status"] == "on user review"


@pytest.mark.asyncio
async def test_approve_pipeline_unavailable_503(pool):
    """Sem o F6 → 503 `pipeline_unavailable` e o status não muda (contrato §8.1)."""
    await new_repo(pool)
    docs = [{"path": "docs/BR/login/login.md", "content": BR_CONTENT}]
    await artifacts_service.sync(pool, repo="acme/app", docs=docs, actor_id=None)
    await artifacts_service.sync(pool, repo="acme/app", docs=docs, actor_id=None)
    await artifacts_service.request_review(
        pool, artifact_id="BR-001", actor_id=str(uuid.uuid4())
    )

    with pytest.raises(ApiError) as excinfo:
        await artifacts_service.approve(pool, artifact_id="BR-001", actor_id=str(uuid.uuid4()))

    assert excinfo.value.code == "pipeline_unavailable"
    assert excinfo.value.status == 503

    row = await pool.fetchrow("SELECT status FROM artifacts WHERE id = 'BR-001'")
    assert row["status"] == "on user review"


@pytest.mark.asyncio
async def test_stabilize_ri_required_409(pool):
    """Sem RI ligado por `tests` → 409 `ri_required` (spec §4.3, decisão D2)."""
    await new_repo(pool)
    docs = [{"path": "docs/BR/login/login.md", "content": BR_CONTENT}]
    await artifacts_service.sync(pool, repo="acme/app", docs=docs, actor_id=None)

    row = await pool.fetchrow("SELECT status FROM artifacts WHERE id = 'BR-001'")
    assert row["status"] == "draft"

    with pytest.raises(ApiError) as excinfo:
        await artifacts_service.stabilize(pool, artifact_id="BR-001", actor_id=str(uuid.uuid4()))

    assert excinfo.value.code == "ri_required"
    assert excinfo.value.status == 409


# --------------------------------------------------------------------------
# GET /api/artifacts/pending — a rota que o kit (F8) consome
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pending_route_lists_artifacts(pool):
    """`GET /api/artifacts/pending` devolve os artefatos não estáveis do repo."""
    from app.routers import artifacts as artifacts_router

    await new_repo(pool)
    await artifacts_service.sync(
        pool,
        repo="acme/app",
        docs=[{"path": "docs/BR/login/login.md", "content": BR_CONTENT}],
        actor_id=None,
    )

    class _Request:
        headers: dict = {}

    response = await artifacts_router.list_pending(
        request=_Request(),
        repo="acme/app",
        demand=None,
        user=sys.modules["app.auth"].User(id=str(uuid.uuid4())),
    )

    assert len(response["artifacts"]) == 1
    assert response["artifacts"][0]["id"] == "BR-001"
    assert response["artifacts"][0]["status"] == "draft"
    assert "# Login" in response["artifacts"][0]["content"]


@pytest.mark.asyncio
async def test_pending_route_requires_repo(pool):
    """`repo` ausente → 400 `invalid_request` (spec §4.3)."""
    from app.routers import artifacts as artifacts_router

    class _Request:
        headers: dict = {}

    response = await artifacts_router.list_pending(
        request=_Request(),
        repo=None,
        demand=None,
        user=sys.modules["app.auth"].User(id=str(uuid.uuid4())),
    )

    assert response.status_code == 400
    assert b'"invalid_request"' in response.body


@pytest.mark.asyncio
async def test_pending_route_empty_is_200(pool):
    """Fila vazia → 200 com `artifacts: []` (não 404)."""
    from app.routers import artifacts as artifacts_router

    await new_repo(pool)

    class _Request:
        headers: dict = {}

    response = await artifacts_router.list_pending(
        request=_Request(),
        repo="acme/app",
        demand=None,
        user=sys.modules["app.auth"].User(id=str(uuid.uuid4())),
    )

    assert response == {"artifacts": []}
