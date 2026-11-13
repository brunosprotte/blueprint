"""Testes do serviço de dúvidas (META-006) — fase F6.

Reusa os dublês de F1/F2/F4/F5 definidos em `test_pipeline.py`.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

try:  # pytest importa como pacote quando existe `server/tests/__init__.py` (F1)
    from tests import test_pipeline as harness
except ImportError:  # pragma: no cover - sem `__init__.py`
    import test_pipeline as harness

from app.services import doubts as doubts_service

NOW = harness.NOW
FakeClient = harness.FakeClient
finding = harness.finding


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    """Ambiente com dublês instalados e um artefato de SPEC no pool."""
    state = {"pool": harness.FakePool(), "lint_findings": []}
    harness._install_doubles(monkeypatch, state)
    pool = state["pool"]
    artifact = harness._make_artifact(pool)
    from app.services import reviewers

    return SimpleNamespace(
        pool=pool,
        state=state,
        artifact=artifact,
        reviewers=reviewers,
        events=lambda event_type: [
            e for e in pool.events if e["type"] == event_type
        ],
    )


@pytest.mark.asyncio
async def test_raise_doubt_inserts_pending(env):
    doubt = await doubts_service.raise_doubt(
        "SPEC-024", "[AC-001] Regra sem critério", "reviewer"
    )

    assert doubt.status == "pending"
    assert doubt.source == "reviewer"
    assert doubt.artifact_id == "SPEC-024"
    assert len(env.pool.doubts) == 1
    assert env.pool.doubts[0]["question"] == "[AC-001] Regra sem critério"


@pytest.mark.asyncio
async def test_raise_doubt_rejects_invalid_source(env):
    with pytest.raises(ValueError) as excinfo:
        await doubts_service.raise_doubt("SPEC-024", "pergunta", "foo")

    assert "foo" in str(excinfo.value)
    assert env.pool.doubts == []


@pytest.mark.asyncio
async def test_resolve_doubt_sets_cleaned(env):
    doubt = await doubts_service.raise_doubt("SPEC-024", "pergunta", "user")

    resolved = await doubts_service.resolve_doubt(doubt.id)

    assert resolved.status == "cleaned"
    assert resolved.resolved_at is not None
    assert env.pool.doubts[0]["status"] == "cleaned"


@pytest.mark.asyncio
async def test_resolve_doubt_unknown_id(env):
    with pytest.raises(doubts_service.DoubtNotFound):
        await doubts_service.resolve_doubt("nao-existe")


def test_render_doubts_file_format(env):
    doubts = [
        doubts_service._doubt_from_row(
            {
                "id": "6f1d2c8e-0a3b-4f5d-9e77-2b1c0a9d4e55",
                "artifact_id": "BR-013",
                "question": "[AC-003] Regra de bloqueio sem critério verificável",
                "status": "pending",
                "source": "reviewer",
                "raised_at": datetime(2026, 11, 10, 12, 34, 56, tzinfo=timezone.utc),
                "resolved_at": None,
            }
        )
    ]

    content = doubts_service.render_doubts_file("BR-013", doubts, "on agents review")

    lines = content.splitlines()
    assert lines[0] == "---"
    assert lines[1] == "id: BR-013"
    assert lines[2] == "artifactId: BR-013"
    assert lines[3] == "status: pending"
    assert lines[4].startswith('updatedAt: "')
    assert lines[5] == "---"
    assert "# Dúvidas — BR-013" in lines
    assert "Pendências: 1" in lines
    assert (
        "| 6f1d2c8e-0a3b-4f5d-9e77-2b1c0a9d4e55 | pending | reviewer | "
        "[AC-003] Regra de bloqueio sem critério verificável | "
        "2026-11-10T12:34:56Z | — |" in lines
    )


def test_render_doubts_file_all_cleaned(env):
    doubt = doubts_service._doubt_from_row(
        {
            "id": "d1",
            "artifact_id": "BR-013",
            "question": "já resolvida",
            "status": "cleaned",
            "source": "user",
            "raised_at": datetime(2026, 11, 10, 12, 0, 0, tzinfo=timezone.utc),
            "resolved_at": datetime(2026, 11, 10, 12, 20, 10, tzinfo=timezone.utc),
        }
    )

    content = doubts_service.render_doubts_file("BR-013", [doubt], "approved")

    assert "Pendências: 0" in content
    assert "status: approved" in content
    assert "2026-11-10T12:20:10Z" in content


@pytest.mark.asyncio
async def test_render_catalog_only_open(env):
    await doubts_service.raise_doubt("SPEC-024", "aberta", "reviewer")
    cleaned = await doubts_service.raise_doubt("SPEC-024", "já resolvida", "user")
    await doubts_service.resolve_doubt(cleaned.id)

    content = await doubts_service.render_catalog("spec")

    assert content.startswith("# Dúvidas de SPEC — pendências abertas")
    assert "| artifact_id | path | abertas | atualizado_em |" in content
    assert "SPEC-024" in content
    assert "docs/SPEC/login/login-api.md" in content
    # só a pendência aberta entra na contagem
    assert "| SPEC-024 | docs/SPEC/login/login-api.md | 1 |" in content


@pytest.mark.asyncio
async def test_doubts_survive_pipeline_roundtrip(env):
    """Pipeline -> dúvida -> resolve -> arquivo re-renderizado."""
    client = FakeClient(
        {"blind-hunter": {"payload": {"findings": [finding("blocking")]}}}
    )

    result = await env.reviewers.run_pipeline(env.artifact, client=client)
    assert result.doubts_written == 1
    assert result.approval_ready is False

    doubt_id = env.pool.doubts[0]["id"]
    resolved = await doubts_service.resolve_doubt(doubt_id)
    assert resolved.status == "cleaned"

    content = doubts_service.render_doubts_file(
        "SPEC-024", await doubts_service.list_doubts("SPEC-024"), "on agents review"
    )
    assert "Pendências: 0" in content
    assert "| cleaned |" in content

    # o resolve republica o arquivo (evento `doubts_file_rendered`)
    rendered = env.events("doubts_file_rendered")
    assert len(rendered) >= 2
    assert "Pendências: 0" in rendered[-1]["payload"]["content"]
