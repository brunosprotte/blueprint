"""Sync repo→servidor, registro de commits e reconcile (spec §5.1–§5.8).

Usa as fixtures reais do F1 (`pool`, `client`, `auth_token`), o linter real do
F2 e os artefatos de fixture do próprio repo (`server/tests/fixtures`).

Cobre os rulings de integração do Contrato Comum §8.4:
D1 (universo sobre o repo do dev, sidecar fora da tabela `artifacts`),
D2 (arquivo de dúvidas renderizado pelo F6), D4 (direção das arestas) e
D6 (lint em lote).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import httpx
import pytest

from app.services import artifacts as artifacts_service
from app.services import claims as claims_service
from app.services import commits as commits_service
from app.services import demands as demands_service
from app.services.lifecycle import ApiError

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BR_VALID = (FIXTURES / "br_valida.md").read_text(encoding="utf-8")
SPEC_VALID = (FIXTURES / "spec_valida.md").read_text(encoding="utf-8")

BR_PATH = "docs/BR/login/autenticacao.md"
SPEC_PATH = "docs/SPEC/login/api-autenticacao.md"
RI_PATH = "docs/RI/login/autenticacao.md"

RI_CONTENT = """---
id: RI-001
module: login
feature: login
type: Implementation Review
title: Plano de teste da autenticação
description: Passos de verificação da autenticação por e-mail e senha.
status: draft
version: 1.0.0
tests: [SPEC-001]
---

# RI-001 — Plano de teste da autenticação

## Objetivo

Verificar a autenticação por e-mail e senha.
"""


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _payload(value) -> dict:
    return json.loads(value) if isinstance(value, str) else value


async def _new_user(pool, login: str = "dev") -> str:
    row = await pool.fetchrow(
        "INSERT INTO users (github_id, login) VALUES ($1, $2) RETURNING id",
        uuid.uuid4().int % 10**12,
        login,
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


async def _sync(pool, docs: list[dict], repo: str = "acme/app") -> dict:
    """Sync repo→servidor: o repo entra pelo conteúdo, nunca pelo filesystem."""
    return await artifacts_service.sync(
        pool,
        repo=repo,
        docs=docs,
        actor_id=None,
    )


async def _actor(pool) -> str:
    """Ator real (o `events.actor` tem FK para `users`)."""
    return await _new_user(pool, "ator")


async def _token_with_repo(pool, owner: str = "acme", name: str = "app") -> str:
    """Token de API preso a um repo (o repo do commit vem do token)."""
    from app.auth import generate_token

    raw, token_hash = generate_token()
    user_id = await _new_user(pool)
    repo_id = await pool.fetchval(
        "INSERT INTO repos (owner, name) VALUES ($1, $2) RETURNING id", owner, name
    )
    await pool.execute(
        "INSERT INTO tokens (user_id, repo_id, token_hash, scopes) "
        "VALUES ($1, $2, $3, $4)",
        uuid.UUID(user_id),
        repo_id,
        token_hash,
        ["demand:claim", "demand:write", "artifact:sync", "artifact:approve", "review:write"],
    )
    return raw


# --------------------------------------------------------------------------
# Sync
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sync_creates_artifact_draft(pool):
    """BR nova nasce `draft`, com o caminho do arquivo de dúvidas (spec §5.2)."""
    result = await _sync(pool, [{"path": BR_PATH, "content": BR_VALID}])

    assert result["summary"]["created"] == 1
    assert result["summary"]["artifacts"] == 1

    row = await pool.fetchrow("SELECT * FROM artifacts WHERE path = $1", BR_PATH)
    assert row["id"] == "BR-001"
    assert row["status"] == "draft"
    assert row["kind"] == "br"
    assert row["module"] == "login"
    assert row["version"] == "1.0.0"
    assert row["doubts_index"] == "docs/implementation-artifacts/duvidas-br/BR-001.md"

    # A tabela `doubts` não recebe linha no nascimento (decisão D6 da spec F4).
    doubts = await pool.fetch("SELECT * FROM doubts WHERE artifact_id = 'BR-001'")
    assert doubts == []


@pytest.mark.asyncio
async def test_sync_doubts_file_rendered_by_f6(pool):
    """O arquivo de dúvidas só existe no formato canônico (renderizado pelo F6).

    Sem o F6 (import tardio falha), **nenhum** arquivo é escrito — nunca um
    arquivo em formato errado (Contrato Comum §8.4 D2).
    """
    await _sync(pool, [{"path": BR_PATH, "content": BR_VALID}])

    row = await pool.fetchrow("SELECT doubts_content FROM artifacts WHERE id = 'BR-001'")
    content = row["doubts_content"]

    if content is None:
        pytest.skip("F6 pendente: renderizador de dúvidas ainda não existe")
    assert "artifactId: BR-001" in content
    assert content.startswith("---")


@pytest.mark.asyncio
async def test_sync_promotes_when_sha_matches(pool):
    """Mesmo sha do servidor → `draft → pending` + evento `artifact.promoted`."""
    docs = [{"path": BR_PATH, "content": BR_VALID}]

    await _sync(pool, docs)
    result = await _sync(pool, docs)

    assert result["summary"]["promoted"] == 1

    row = await pool.fetchrow("SELECT * FROM artifacts WHERE id = 'BR-001'")
    assert row["status"] == "pending"

    event = await pool.fetchrow(
        "SELECT * FROM events WHERE artifact_id = 'BR-001' AND type = 'artifact.promoted'"
    )
    assert event is not None
    payload = _payload(event["payload"])
    assert payload["from"] == "draft"
    assert payload["to"] == "pending"


@pytest.mark.asyncio
async def test_sync_409_on_divergence(pool):
    """Sha divergente em `draft` → 409 e nada persistido (spec §5.6)."""
    await _sync(pool, [{"path": BR_PATH, "content": BR_VALID}])

    other = {"path": SPEC_PATH, "content": SPEC_VALID}
    diverged = {"path": BR_PATH, "content": BR_VALID + "\noutro\n"}

    with pytest.raises(ApiError) as excinfo:
        await _sync(pool, [diverged, other])

    error = excinfo.value
    assert error.code == "content_diverged"
    assert error.status == 409
    assert error.detail["server_sha"] != error.detail["client_sha"]
    assert error.detail["path"] == BR_PATH

    # Nada do lote foi aplicado.
    rows = await pool.fetch("SELECT path FROM artifacts ORDER BY path")
    assert [row["path"] for row in rows] == [BR_PATH]


@pytest.mark.asyncio
async def test_sync_idempotent(pool):
    """Sync repetido → mesma linha, mesma versão, nenhum evento novo."""
    docs = [{"path": BR_PATH, "content": BR_VALID}]

    await _sync(pool, docs)
    await _sync(pool, docs)

    before = await pool.fetchval("SELECT count(*) FROM events")
    version_before = await pool.fetchval("SELECT version FROM artifacts WHERE id = 'BR-001'")

    await _sync(pool, docs)

    after = await pool.fetchval("SELECT count(*) FROM events")
    rows = await pool.fetch("SELECT * FROM artifacts WHERE id = 'BR-001'")
    assert len(rows) == 1
    assert after == before
    assert rows[0]["version"] == version_before
    assert rows[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_sync_lint_error_blocks_promotion(pool):
    """Link quebrado → o artefato fica em `draft` (spec §5.3, decisão D4 da spec F4)."""
    broken = BR_VALID + "\n## Link\n\n[[META-999]]\n"

    await _sync(pool, [{"path": BR_PATH, "content": broken}])
    result = await _sync(pool, [{"path": BR_PATH, "content": broken}])

    assert result["summary"]["promoted"] == 0
    assert result["summary"]["lint_error"] >= 1

    row = await pool.fetchrow("SELECT status FROM artifacts WHERE id = 'BR-001'")
    assert row["status"] == "draft"


@pytest.mark.asyncio
async def test_sync_ignores_non_artifact_paths(pool):
    """Path fora de BR/SPEC/RI → `summary.ignored` (spec §5.1).

    O sidecar de dúvidas (`docs/implementation-artifacts/**`) NUNCA vira linha de
    `artifacts` (Contrato Comum §8.4 D1).
    """
    result = await _sync(
        pool,
        [
            {"path": "README.md", "content": "# repo"},
            {"path": "AGENTS.md", "content": "# agentes"},
            {
                "path": "docs/implementation-artifacts/duvidas-br/BR-001.md",
                "content": "# Dúvidas — BR-001\n",
            },
        ],
    )

    assert result["summary"]["ignored"] == 3
    assert result["summary"]["artifacts"] == 0
    assert result["artifacts"] == []
    assert await pool.fetchval("SELECT count(*) FROM artifacts") == 0


@pytest.mark.asyncio
async def test_sync_status_source_is_db(pool):
    """Frontmatter com `status` diferente não muda `artifacts.status` (spec §5.7)."""
    content = BR_VALID.replace("status: draft", "status: stable")

    await _sync(pool, [{"path": BR_PATH, "content": content}])

    row = await pool.fetchrow("SELECT status FROM artifacts WHERE id = 'BR-001'")
    assert row["status"] == "draft"

    event = await pool.fetchrow(
        "SELECT payload FROM events WHERE artifact_id = 'BR-001' AND type = 'artifact.synced'"
    )
    assert _payload(event["payload"])["frontmatter_status"] == "stable"


@pytest.mark.asyncio
async def test_sync_creates_graph_edges_canonical_direction(pool):
    """Direção canônica das arestas (Contrato Comum §8.4 D4).

    | tipo | parent | child |
    | --- | --- | --- |
    | `derives_from` | a SPEC | a BR |
    | `depends_on` | o dependente | a dependência |
    | `tests` | a SPEC | o RI |
    """
    await _sync(
        pool,
        [
            {"path": BR_PATH, "content": BR_VALID},
            {"path": RI_PATH, "content": RI_CONTENT},
            {"path": SPEC_PATH, "content": SPEC_VALID},
        ],
    )

    edges = await pool.fetch(
        "SELECT parent_id, child_id, type FROM spec_edges ORDER BY type, parent_id"
    )
    assert [
        (row["parent_id"], row["child_id"], row["type"]) for row in edges
    ] == [
        ("SPEC-001", "BR-001", "derives_from"),
        ("SPEC-001", "RI-001", "tests"),
    ]


@pytest.mark.asyncio
async def test_sync_lint_batch_covers_acs(pool):
    """BR + SPEC no mesmo lote: a AC da BR coberta pela SPEC passa (D6)."""
    docs = [
        {"path": BR_PATH, "content": BR_VALID},
        {"path": SPEC_PATH, "content": SPEC_VALID},
    ]

    await _sync(pool, docs)
    result = await _sync(pool, docs)

    assert result["summary"]["lint_error"] == 0
    assert result["summary"]["promoted"] == 2

    rows = await pool.fetch("SELECT id, status FROM artifacts ORDER BY id")
    assert [(row["id"], row["status"]) for row in rows] == [
        ("BR-001", "pending"),
        ("SPEC-001", "pending"),
    ]


@pytest.mark.asyncio
async def test_sync_lint_batch_flags_uncovered_ac(pool):
    """SPEC no lote que não cobre a AC da BR → BR-004 erro (a BR fica em draft)."""
    spec_parcial = SPEC_VALID.replace(
        "- **AC-002** — A autenticação com credenciais inválidas devolve `401` sem\n"
        "  revelar qual credencial falhou.\n",
        "",
    )
    docs = [
        {"path": BR_PATH, "content": BR_VALID},
        {"path": SPEC_PATH, "content": spec_parcial},
    ]

    await _sync(pool, docs)
    result = await _sync(pool, docs)

    assert result["summary"]["lint_error"] >= 1
    assert result["summary"]["promoted"] == 1  # só a SPEC é promovida

    row = await pool.fetchrow("SELECT status FROM artifacts WHERE id = 'BR-001'")
    assert row["status"] == "draft"


@pytest.mark.asyncio
async def test_sync_br_without_spec_is_not_error(pool):
    """BR sozinha no lote → BR-004 não é aplicável (não vira erro)."""
    docs = [{"path": BR_PATH, "content": BR_VALID}]

    await _sync(pool, docs)
    result = await _sync(pool, docs)

    assert result["summary"]["lint_error"] == 0
    assert result["summary"]["promoted"] == 1


# --------------------------------------------------------------------------
# Commits
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_commit_recorded_idempotent(pool):
    """Mesmo `(repo_id, sha)` → mesmo `id`, `created: false`, 1 linha."""
    user_id = await _new_user(pool)
    repo_id = await pool.fetchval(
        "INSERT INTO repos (owner, name) VALUES ('acme', 'app') RETURNING id"
    )
    demand_id = await _new_demand(pool, str(repo_id), user_id)

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
    user_id = await _new_user(pool)
    repo_id = await pool.fetchval(
        "INSERT INTO repos (owner, name) VALUES ('acme', 'app') RETURNING id"
    )
    demand_id = await _new_demand(pool, str(repo_id), user_id)

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
    user_id = await _new_user(pool)
    await pool.execute("INSERT INTO repos (owner, name) VALUES ('acme', 'app')")

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
async def test_commit_route_requires_repo_token(client, auth_token, pool):
    """Token sem repo → 400 `invalid_repo`, com a mensagem dizendo o que fazer."""
    response = await client.post(
        "/api/commits",
        json={
            "sha": "a1b2c3d",
            "message": "feat: login",
            "branch": "main",
            "files": [],
            "demand_id": str(uuid.uuid4()),
        },
        headers=_auth(auth_token),
    )

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "invalid_repo"
    assert "token" in error["message"]
    assert "repo" in error["message"]


@pytest.mark.asyncio
async def test_commit_route_with_repo_token(client, pool):
    """Token preso a um repo → 200 com o commit gravado."""
    token = await _token_with_repo(pool)
    user_id = str(await pool.fetchval("SELECT id FROM users ORDER BY created_at LIMIT 1"))
    repo_id = str(await pool.fetchval("SELECT id FROM repos LIMIT 1"))
    demand_id = await _new_demand(pool, repo_id, user_id)

    response = await client.post(
        "/api/commits",
        json={
            "sha": "a1b2c3d",
            "message": "feat: login",
            "branch": "main",
            "files": [{"path": "src/auth.ts", "additions": 1, "deletions": 0}],
            "demand_id": demand_id,
        },
        headers=_auth(token),
    )

    assert response.status_code == 200
    commit = response.json()
    assert commit["created"] is True
    assert commit["sha"] == "a1b2c3d"
    assert commit["status"] == "present"
    assert commit["files"] == [{"path": "src/auth.ts", "additions": 1, "deletions": 0}]


@pytest.mark.asyncio
async def test_commits_route_by_demand(client, pool):
    """`GET /api/commits/{demand_id}` devolve os commits da demanda."""
    token = await _token_with_repo(pool)
    user_id = str(await pool.fetchval("SELECT id FROM users ORDER BY created_at LIMIT 1"))
    repo_id = str(await pool.fetchval("SELECT id FROM repos LIMIT 1"))
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

    response = await client.get(f"/api/commits/{demand_id}", headers=_auth(token))

    assert response.status_code == 200
    commits = response.json()["commits"]
    assert [commit["sha"] for commit in commits] == ["a1b2c3d"]


@pytest.mark.asyncio
async def test_list_commits_omits_orphaned(pool):
    """`GET /api/commits` omite `orphaned` por padrão (spec §4.4)."""
    user_id = await _new_user(pool)
    repo_id = await pool.fetchval(
        "INSERT INTO repos (owner, name) VALUES ('acme', 'app') RETURNING id"
    )
    demand_id = await _new_demand(pool, str(repo_id), user_id)

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
    user_id = await _new_user(pool)
    repo_id = await pool.fetchval(
        "INSERT INTO repos (owner, name) VALUES ('acme', 'app') RETURNING id"
    )
    demand_id = await _new_demand(pool, str(repo_id), user_id)

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
    user_id = await _new_user(pool)
    repo_id = await pool.fetchval(
        "INSERT INTO repos (owner, name) VALUES ('acme', 'app') RETURNING id"
    )
    demand_id = await _new_demand(pool, str(repo_id), user_id)

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
    docs = [{"path": BR_PATH, "content": BR_VALID}]
    await _sync(pool, docs)
    await _sync(pool, docs)

    await pool.execute(
        "INSERT INTO doubts (artifact_id, question, status, source) "
        "VALUES ('BR-001', 'dúvida aberta', 'pending', 'reviewer')"
    )

    with pytest.raises(ApiError) as excinfo:
        await artifacts_service.request_review(
            pool, artifact_id="BR-001", actor_id=await _actor(pool)
        )

    assert excinfo.value.code == "open_doubts"
    assert excinfo.value.status == 409


@pytest.mark.asyncio
async def test_request_review_promotes(pool):
    """Sem dúvida pendente → `pending → on user review`."""
    docs = [{"path": BR_PATH, "content": BR_VALID}]
    await _sync(pool, docs)
    await _sync(pool, docs)

    result = await artifacts_service.request_review(
        pool, artifact_id="BR-001", actor_id=await _actor(pool)
    )

    assert result["status"] == "on user review"


@pytest.mark.asyncio
async def test_approve_pipeline_unavailable_503(pool):
    """Sem o F6 → 503 `pipeline_unavailable` e o status não muda (contrato §8.1)."""
    docs = [{"path": BR_PATH, "content": BR_VALID}]
    await _sync(pool, docs)
    await _sync(pool, docs)
    await artifacts_service.request_review(
        pool, artifact_id="BR-001", actor_id=await _actor(pool)
    )

    with pytest.raises(ApiError) as excinfo:
        await artifacts_service.approve(pool, artifact_id="BR-001", actor_id=await _actor(pool))

    assert excinfo.value.code == "pipeline_unavailable"
    assert excinfo.value.status == 503

    row = await pool.fetchrow("SELECT status FROM artifacts WHERE id = 'BR-001'")
    assert row["status"] == "on user review"


@pytest.mark.asyncio
async def test_stabilize_ri_required_409(pool):
    """Sem RI ligado por `tests` → 409 `ri_required` (spec §4.3, decisão D2)."""
    await _sync(pool, [{"path": BR_PATH, "content": BR_VALID}])

    with pytest.raises(ApiError) as excinfo:
        await artifacts_service.stabilize(pool, artifact_id="BR-001", actor_id=await _actor(pool))

    assert excinfo.value.code == "ri_required"
    assert excinfo.value.status == 409


# --------------------------------------------------------------------------
# GET /api/artifacts/pending — a rota que o kit (F8) consome
# --------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pending_route_lists_artifacts(client, auth_token, pool):
    """`GET /api/artifacts/pending` devolve os artefatos não estáveis do repo."""
    await _sync(pool, [{"path": BR_PATH, "content": BR_VALID}])

    response = await client.get(
        "/api/artifacts/pending", params={"repo": "acme/app"}, headers=_auth(auth_token)
    )

    assert response.status_code == 200
    artifacts = response.json()["artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0]["id"] == "BR-001"
    assert artifacts[0]["status"] == "draft"
    assert "# BR-001" in artifacts[0]["content"]


@pytest.mark.asyncio
async def test_pending_route_requires_repo(client, auth_token):
    """`repo` ausente → 400 `invalid_request` (spec §4.3)."""
    response = await client.get("/api/artifacts/pending", headers=_auth(auth_token))

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


@pytest.mark.asyncio
async def test_pending_route_delivers_doubts_sidecar(client, auth_token, pool):
    """O `pull` entrega o arquivo de dúvidas publicado no evento (D1 revisado).

    O sidecar nunca vira linha de `artifacts`: o canal de publicação é o evento
    `doubts_file_rendered` (F5/F6), com path, content e sha.
    """
    await _sync(pool, [{"path": BR_PATH, "content": BR_VALID}])
    await pool.execute(
        "INSERT INTO events (artifact_id, type, payload) "
        "VALUES ('BR-001', 'doubts_file_rendered', $1::jsonb)",
        json.dumps(
            {
                "artifact_id": "BR-001",
                "path": "docs/implementation-artifacts/duvidas-br/BR-001.md",
                "content": "---\nid: BR-001\n---\n\n# Dúvidas — BR-001\n",
                "sha": "abc",
            }
        ),
    )

    response = await client.get(
        "/api/artifacts/pending", params={"repo": "acme/app"}, headers=_auth(auth_token)
    )

    assert response.status_code == 200
    artifacts = response.json()["artifacts"]
    sidecars = [item for item in artifacts if item["kind"] == "doubts"]
    assert len(sidecars) == 1
    assert sidecars[0]["path"] == "docs/implementation-artifacts/duvidas-br/BR-001.md"
    assert "# Dúvidas — BR-001" in sidecars[0]["content"]

    # O sidecar não é linha de `artifacts`.
    assert await pool.fetchval("SELECT count(*) FROM artifacts WHERE kind = 'doubts'") == 0


@pytest.mark.asyncio
async def test_pending_route_empty_is_200(client, auth_token, pool):
    """Fila vazia → 200 com `artifacts: []` (não 404)."""
    await pool.execute("INSERT INTO repos (owner, name) VALUES ('acme', 'app')")

    response = await client.get(
        "/api/artifacts/pending", params={"repo": "acme/app"}, headers=_auth(auth_token)
    )

    assert response.status_code == 200
    assert response.json() == {"artifacts": []}
