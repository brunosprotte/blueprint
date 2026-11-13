"""Testes da fase F7 — dossiê da demanda.

Dependem do F1 (banco) e da migration 004 do F4 (`commits.status`); marcados com
`@pytest.mark.skip(reason="F1 pendente")` enquanto essas fases não existem.
"""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

# `server/` no sys.path para `app.*` ser importável enquanto o F1 não existe.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.retriever import build_dossier  # noqa: E402

BR_CONTENT = """---
id: BR-013
title: Login de alunos
module: login
---

## Acceptance Criteria

- AC-001: Aluno entra com e-mail e senha
- AC-002: Erro de senha mostra mensagem genérica
- AC-003: Sessão expira após 30 minutos
"""

SPEC_002_CONTENT = """---
id: SPEC-002
title: Login API
module: login
---

## Acceptance Criteria atendidos

- AC-001
"""

SPEC_003_CONTENT = """---
id: SPEC-003
title: Login UI
module: login
---

## Acceptance Criteria atendidos

- AC-002
"""

SHA_1 = "9f3a1c2b8e5d4c7a9b0c1d2e3f4a5b6c7d8e9f0a"
SHA_2 = "1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d"


async def _seed(pool) -> dict:
    """Demanda, BR, 2 SPECs, spec_edges, 2 commits e 2 reviews direto no banco."""
    user_id = uuid.uuid4()
    await pool.execute(
        "INSERT INTO users (id, github_id, login, email) VALUES ($1, $2, $3, $4)",
        user_id,
        uuid.uuid4().int % 10**12,
        "tester",
        "tester@example.com",
    )

    repo_id = uuid.uuid4()
    await pool.execute(
        "INSERT INTO repos (id, owner, name, default_branch) VALUES ($1, $2, $3, $4)",
        repo_id,
        "acme",
        "app",
        "main",
    )

    demand_id = uuid.uuid4()
    await pool.execute(
        "INSERT INTO demands (id, repo_id, module, title, body, created_by) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        demand_id,
        repo_id,
        "login",
        "Login de alunos",
        "body",
        user_id,
    )

    for artifact_id, kind, path, content in (
        ("BR-013", "br", "docs/BR/login/login.md", BR_CONTENT),
        ("SPEC-002", "spec", "docs/SPEC/login/login-api.md", SPEC_002_CONTENT),
        ("SPEC-003", "spec", "docs/SPEC/login/login-ui.md", SPEC_003_CONTENT),
    ):
        await pool.execute(
            "INSERT INTO artifacts (id, demand_id, repo_id, kind, module, feature, path, "
            "sha, status, version, content) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
            artifact_id,
            demand_id,
            repo_id,
            kind,
            "login",
            "login",
            path,
            "sha-" + artifact_id,
            "approved",
            "1",
            content,
        )

    await pool.execute(
        "INSERT INTO spec_edges (parent_id, child_id, type) VALUES ($1, $2, $3)",
        "SPEC-002",
        "SPEC-003",
        "depends_on",
    )

    commit_1 = uuid.uuid4()
    await pool.execute(
        "INSERT INTO commits (id, demand_id, repo_id, sha, message, branch, author, files) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)",
        commit_1,
        demand_id,
        repo_id,
        SHA_1,
        "feat(login): endpoint de autenticacao (AC-001)",
        "feat/login",
        "Bruno",
        json.dumps(["src/api/login/route.ts"]),
    )

    commit_2 = uuid.uuid4()
    await pool.execute(
        "INSERT INTO commits (id, demand_id, repo_id, sha, message, branch, author, files, status) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9)",
        commit_2,
        demand_id,
        repo_id,
        SHA_2,
        "chore: ajustes",
        "feat/login",
        "Bruno",
        json.dumps(["package.json"]),
        "orphaned",
    )

    await pool.execute(
        "INSERT INTO reviews (id, commit_id, demand_id, verdict, findings) "
        "VALUES ($1, $2, $3, $4, $5::jsonb)",
        uuid.uuid4(),
        commit_1,
        demand_id,
        "clean",
        json.dumps([]),
    )
    await pool.execute(
        "INSERT INTO reviews (id, commit_id, demand_id, verdict, findings) "
        "VALUES ($1, $2, $3, $4, $5::jsonb)",
        uuid.uuid4(),
        commit_1,
        demand_id,
        "blocking",
        json.dumps(
            [
                {
                    "severity": "blocking",
                    "title": "Erro de senha",
                    "detail": "Mensagem revela se o e-mail existe",
                    "ac": "AC-002",
                    "suggestion": "Mensagem generica",
                }
            ]
        ),
    )

    await pool.execute(
        "INSERT INTO doubts (id, artifact_id, question, status, source) "
        "VALUES ($1, $2, $3, $4, $5)",
        uuid.uuid4(),
        "SPEC-003",
        "[AC-002] Erro de senha — mensagem revela se o e-mail existe",
        "pending",
        "reviewer",
    )
    await pool.execute(
        "INSERT INTO doubts (id, artifact_id, question, status, source) "
        "VALUES ($1, $2, $3, $4, $5)",
        uuid.uuid4(),
        "SPEC-002",
        "[AC-001] Digitais — duvida ja tratada",
        "cleaned",
        "reviewer",
    )

    return {"demand_id": demand_id, "commit_1": commit_1, "commit_2": commit_2}


@pytest.mark.asyncio
@pytest.mark.skip(reason="F1 pendente")
async def test_dossier_shape(pool):
    seeded = await _seed(pool)
    dossier = await build_dossier(pool, seeded["demand_id"])

    assert set(dossier) == {"necessidade", "proposta", "implementacao", "desvios"}
    assert set(dossier["necessidade"]) == {"br", "acs"}
    assert set(dossier["proposta"]) == {"specs", "grafo"}
    assert set(dossier["implementacao"]) == {"commits", "reviews"}
    assert isinstance(dossier["desvios"], list)


@pytest.mark.asyncio
@pytest.mark.skip(reason="F1 pendente")
async def test_dossier_necessidade(pool):
    seeded = await _seed(pool)
    dossier = await build_dossier(pool, seeded["demand_id"])

    br = dossier["necessidade"]["br"]
    assert len(br) == 1
    assert br[0]["id"] == "BR-013"
    assert br[0]["path"] == "docs/BR/login/login.md"
    assert br[0]["title"] == "Login de alunos"
    assert br[0]["module"] == "login"

    acs = dossier["necessidade"]["acs"]
    assert [ac["id"] for ac in acs] == ["AC-001", "AC-002", "AC-003"]
    assert acs[0]["title"] == "Aluno entra com e-mail e senha"


@pytest.mark.asyncio
@pytest.mark.skip(reason="F1 pendente")
async def test_dossier_ac_coverage(pool):
    seeded = await _seed(pool)
    dossier = await build_dossier(pool, seeded["demand_id"])

    acs = {ac["id"]: ac for ac in dossier["necessidade"]["acs"]}
    assert acs["AC-001"]["specs"] == ["SPEC-002"]
    assert acs["AC-002"]["specs"] == ["SPEC-003"]
    assert acs["AC-003"]["specs"] == []
    assert acs["AC-001"]["commits"] == [SHA_1[:7]]


@pytest.mark.asyncio
@pytest.mark.skip(reason="F1 pendente")
async def test_dossier_proposta_grafo(pool):
    seeded = await _seed(pool)
    dossier = await build_dossier(pool, seeded["demand_id"])

    specs = dossier["proposta"]["specs"]
    assert [spec["id"] for spec in specs] == ["SPEC-002", "SPEC-003"]
    assert specs[0]["title"] == "Login API"

    assert dossier["proposta"]["grafo"] == [
        {"parent": "SPEC-002", "child": "SPEC-003", "type": "depends_on"}
    ]


@pytest.mark.asyncio
@pytest.mark.skip(reason="F1 pendente")
async def test_dossier_implementacao(pool):
    seeded = await _seed(pool)
    dossier = await build_dossier(pool, seeded["demand_id"])

    commits = dossier["implementacao"]["commits"]
    assert commits[0]["sha"] == SHA_1
    assert commits[0]["branch"] == "feat/login"
    assert commits[0]["files"] == ["src/api/login/route.ts"]
    assert commits[0]["status"] == "present"

    reviews = dossier["implementacao"]["reviews"]
    assert len(reviews) == 2
    assert reviews[0]["commit_sha"] == SHA_1
    assert reviews[0]["verdict"] == "clean"
    assert reviews[0]["findings"] == []


@pytest.mark.asyncio
@pytest.mark.skip(reason="F1 pendente")
async def test_dossier_excludes_orphaned(pool):
    seeded = await _seed(pool)
    dossier = await build_dossier(pool, seeded["demand_id"])

    shas = [commit["sha"] for commit in dossier["implementacao"]["commits"]]
    assert SHA_2 not in shas
    assert SHA_1 in shas


@pytest.mark.asyncio
@pytest.mark.skip(reason="F1 pendente")
async def test_dossier_desvio_ac_sem_spec(pool):
    seeded = await _seed(pool)
    dossier = await build_dossier(pool, seeded["demand_id"])

    desvios = [d for d in dossier["desvios"] if d["kind"] == "ac_sem_spec"]
    assert len(desvios) == 1
    assert desvios[0]["ac"] == "AC-003"
    assert desvios[0]["specs"] == []
    assert desvios[0]["detail"]


@pytest.mark.asyncio
@pytest.mark.skip(reason="F1 pendente")
async def test_dossier_desvio_ac_sem_commit(pool):
    seeded = await _seed(pool)
    dossier = await build_dossier(pool, seeded["demand_id"])

    desvios = [d for d in dossier["desvios"] if d["kind"] == "ac_sem_commit"]
    assert len(desvios) == 1
    assert desvios[0]["ac"] == "AC-002"
    assert desvios[0]["specs"] == ["SPEC-003"]


@pytest.mark.asyncio
@pytest.mark.skip(reason="F1 pendente")
async def test_dossier_desvio_finding_bloqueante(pool):
    seeded = await _seed(pool)
    dossier = await build_dossier(pool, seeded["demand_id"])

    desvios = [d for d in dossier["desvios"] if d["kind"] == "finding_bloqueante"]
    assert len(desvios) == 1
    assert desvios[0]["ac"] == "AC-002"
    assert desvios[0]["severity"] == "blocking"
    assert desvios[0]["artifact_id"] == "SPEC-003"
    assert desvios[0]["commit_sha"] == SHA_1
    assert desvios[0]["doubt_status"] == "pending"
    assert desvios[0]["suggestion"]


@pytest.mark.asyncio
@pytest.mark.skip(reason="F1 pendente")
async def test_dossier_finding_tratado(pool):
    seeded = await _seed(pool)
    dossier = await build_dossier(pool, seeded["demand_id"])

    bloqueantes = [
        d for d in dossier["desvios"] if d["kind"] == "finding_bloqueante" and d["ac"] == "AC-001"
    ]
    assert bloqueantes == []


@pytest.mark.asyncio
@pytest.mark.skip(reason="F1 pendente")
async def test_dossier_unknown_demand(client, auth_token):
    response = await client.get(
        f"/api/knowledge/dossier/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "demand_not_found"
