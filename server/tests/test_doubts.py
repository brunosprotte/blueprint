"""Testes do serviço de dúvidas (META-006) — fase F6.

Usa as fixtures reais do F1 (`pool`) e o F4 real (sync + ciclo de vida).
Nenhum dublê em `sys.modules`.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.services import artifacts as artifacts_service
from app.services import doubts as doubts_service
from app.services import reviewers as reviewers_service
from app.services.lifecycle import apply_artifact_transition

try:  # pytest importa como pacote quando existe `server/tests/__init__.py` (F1)
    from tests import test_pipeline as harness
except ImportError:  # pragma: no cover - sem `__init__.py`
    import test_pipeline as harness

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest_asyncio.fixture
async def scenario(pool):
    """Demanda + BR + SPEC (F4 real), SPEC em `on agents review`."""
    user_id = await harness._new_user(pool, "ator")
    repo_id = await artifacts_service.ensure_repo(pool, harness.REPO)
    demand_id = await harness._new_demand(pool, repo_id, user_id)
    docs = [
        {"path": harness.BR_PATH, "content": harness.BR_VALID},
        {"path": harness.SPEC_PATH, "content": harness.SPEC_VALID},
    ]
    for _ in range(2):
        await artifacts_service.sync(pool, repo=harness.REPO, docs=docs, actor_id=None)
    await pool.execute("UPDATE artifacts SET demand_id = $1", uuid.UUID(demand_id))
    for target in ("on user review", "on agents review"):
        await apply_artifact_transition(pool, "SPEC-001", target)
    artifact = await artifacts_service.get_artifact(pool, "SPEC-001")
    assert artifact is not None
    return SimpleNamespace(pool=pool, artifact=artifact, demand_id=demand_id)


@pytest.mark.asyncio
async def test_raise_doubt_inserts_pending(scenario):
    doubt = await doubts_service.raise_doubt(
        "SPEC-001", "[AC-001] Regra sem critério", "reviewer"
    )

    assert doubt.status == "pending"
    assert doubt.source == "reviewer"
    assert doubt.artifact_id == "SPEC-001"
    rows = await scenario.pool.fetch(
        "SELECT status, source, question FROM doubts WHERE artifact_id = 'SPEC-001'"
    )
    assert len(rows) == 1
    assert rows[0]["question"] == "[AC-001] Regra sem critério"


@pytest.mark.asyncio
async def test_raise_doubt_rejects_invalid_source(scenario):
    with pytest.raises(ValueError) as excinfo:
        await doubts_service.raise_doubt("SPEC-001", "pergunta", "foo")

    assert "foo" in str(excinfo.value)
    assert await scenario.pool.fetch("SELECT id FROM doubts") == []


@pytest.mark.asyncio
async def test_resolve_doubt_sets_cleaned(scenario):
    doubt = await doubts_service.raise_doubt("SPEC-001", "pergunta", "user")

    resolved = await doubts_service.resolve_doubt(doubt.id)

    assert resolved.status == "cleaned"
    assert resolved.resolved_at is not None
    rows = await scenario.pool.fetch("SELECT status FROM doubts WHERE id = $1", uuid.UUID(doubt.id))
    assert rows[0]["status"] == "cleaned"


@pytest.mark.asyncio
async def test_resolve_doubt_unknown_id(scenario):
    with pytest.raises(doubts_service.DoubtNotFound):
        await doubts_service.resolve_doubt("6f1d2c8e-0a3b-4f5d-9e77-2b1c0a9d4e55")


def test_render_doubts_file_format(scenario):
    doubts = [
        doubts_service._doubt_from_row(
            {
                "id": "6f1d2c8e-0a3b-4f5d-9e77-2b1c0a9d4e55",
                "artifact_id": "BR-001",
                "question": "[AC-003] Regra de bloqueio sem critério verificável",
                "status": "pending",
                "source": "reviewer",
                "raised_at": datetime(2026, 11, 10, 12, 34, 56, tzinfo=timezone.utc),
                "resolved_at": None,
            }
        )
    ]

    content = doubts_service.render_doubts_file("BR-001", doubts, "on agents review")

    lines = content.splitlines()
    assert lines[0] == "---"
    assert lines[1] == "id: BR-001"
    assert lines[2] == "artifactId: BR-001"
    assert lines[3] == "status: pending"
    assert lines[4].startswith('updatedAt: "')
    assert lines[5] == "---"
    assert "# Dúvidas — BR-001" in lines
    assert "Pendências: 1" in lines
    assert (
        "| 6f1d2c8e-0a3b-4f5d-9e77-2b1c0a9d4e55 | pending | reviewer | "
        "[AC-003] Regra de bloqueio sem critério verificável | "
        "2026-11-10T12:34:56Z | — |" in lines
    )


def test_render_doubts_file_all_cleaned(scenario):
    doubt = doubts_service._doubt_from_row(
        {
            "id": "d1",
            "artifact_id": "BR-001",
            "question": "já resolvida",
            "status": "cleaned",
            "source": "user",
            "raised_at": datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc),
            "resolved_at": datetime(2026, 11, 10, 12, 20, 10, tzinfo=timezone.utc),
        }
    )

    content = doubts_service.render_doubts_file("BR-001", [doubt], "approved")

    assert "Pendências: 0" in content
    assert "status: approved" in content
    assert "2026-11-10T12:20:10Z" in content


@pytest.mark.asyncio
async def test_render_catalog_only_open(scenario):
    await doubts_service.raise_doubt("SPEC-001", "aberta", "reviewer")
    cleaned = await doubts_service.raise_doubt("SPEC-001", "já resolvida", "user")
    await doubts_service.resolve_doubt(cleaned.id)

    content = await doubts_service.render_catalog("spec")

    assert content.startswith("# Dúvidas de SPEC — pendências abertas")
    assert "| artifact_id | path | abertas | atualizado_em |" in content
    assert "SPEC-001" in content
    assert "docs/SPEC/login/api-autenticacao.md" in content
    # só a pendência aberta entra na contagem
    assert "| SPEC-001 | docs/SPEC/login/api-autenticacao.md | 1 |" in content


@pytest.mark.asyncio
async def test_doubts_survive_pipeline_roundtrip(scenario):
    """Pipeline -> dúvida -> resolve -> arquivo re-renderizado."""
    client = harness.FakeClient(
        {"blind-hunter": {"payload": {"findings": [harness.finding("blocking")]}}}
    )

    result = await reviewers_service.run_pipeline(scenario.artifact, client=client)
    assert result.doubts_written == 1
    assert result.approval_ready is False

    rows = await scenario.pool.fetch(
        "SELECT id FROM doubts WHERE artifact_id = 'SPEC-001'"
    )
    resolved = await doubts_service.resolve_doubt(str(rows[0]["id"]))
    assert resolved.status == "cleaned"

    content = doubts_service.render_doubts_file(
        "SPEC-001", await doubts_service.list_doubts("SPEC-001"), "on agents review"
    )
    assert "Pendências: 0" in content
    assert "| cleaned |" in content

    # o resolve republica o arquivo (evento `doubts_file_rendered`)
    rows = await scenario.pool.fetch(
        "SELECT payload FROM events WHERE type = 'doubts_file_rendered' ORDER BY id"
    )
    assert len(rows) >= 2
    payload = rows[-1]["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    assert "Pendências: 0" in payload["content"]
