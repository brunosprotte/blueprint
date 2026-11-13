"""Testes do pipeline de aprovação — fase F6.

Usa as fixtures **reais** do F1 (`pool`, `client`, `auth_token`), o linter real
do F2, o ciclo de vida real do F4 e o Postgres de teste. A única coisa falsa
é o cliente da Anthropic — nenhuma chamada de LLM sai da máquina.

Nada aqui instala dublê em `sys.modules`: os módulos já importados (o `app.main`
do conftest importa todos os routers) não enxergariam o dublê, e a
substituição vazava para as outras fases.
"""

from __future__ import annotations

import json
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio

from app.services import artifacts as artifacts_service
from app.services import reviewers as reviewers_service
from app.services.lifecycle import apply_artifact_transition

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BR_VALID = (FIXTURES / "br_valida.md").read_text(encoding="utf-8")
SPEC_VALID = (FIXTURES / "spec_valida.md").read_text(encoding="utf-8")

BR_PATH = "docs/BR/login/autenticacao.md"
SPEC_PATH = "docs/SPEC/login/api-autenticacao.md"
REPO = "acme/app"

#: SPEC com frontmatter incompleto — o linter do F2 reprova (SPEC-001).
SPEC_INVALID_PATH = "docs/SPEC/login/api-quebrada.md"
SPEC_INVALID = """---
id: SPEC-002
module: login
feature: quebrada
type: Functional Specification
title: API quebrada
---

# Objetivo

Sem as seções obrigatórias.
"""


# --------------------------------------------------------------------------
# Helpers de banco (o F4 real, sem dublê)
# --------------------------------------------------------------------------


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _new_user(pool, login: str = "dev") -> str:
    row = await pool.fetchrow(
        "INSERT INTO users (github_id, login) VALUES ($1, $2) RETURNING id",
        uuid.uuid4().int % 10**12,
        login,
    )
    return str(row["id"])


async def _new_demand(pool, repo_id: str, user_id: str, status: str = "in_progress") -> str:
    row = await pool.fetchrow(
        """
        INSERT INTO demands (repo_id, module, title, body, status, created_by)
        VALUES ($1, 'login', 'demanda', 'corpo', $2, $3)
        RETURNING id
        """,
        uuid.UUID(repo_id),
        status,
        uuid.UUID(user_id),
    )
    return str(row["id"])


async def _token_with_scopes(pool, user_id: str, scopes: list[str]) -> str:
    """Token de API com escopos limitados — o 403 de escopo precisa dele."""
    from app.auth import generate_token

    raw, token_hash = generate_token()
    await pool.execute(
        "INSERT INTO tokens (user_id, token_hash, scopes) VALUES ($1, $2, $3)",
        uuid.UUID(user_id),
        token_hash,
        scopes,
    )
    return raw


async def _sync(pool, docs: list[dict]) -> dict:
    """Sync repo→servidor pelo serviço real do F4."""
    return await artifacts_service.sync(
        pool, repo=REPO, docs=docs, actor_id=None
    )


async def _events(pool, event_type: str) -> list[dict]:
    rows = await pool.fetch(
        "SELECT id, type, payload FROM events WHERE type = $1 ORDER BY id", event_type
    )
    return [
        {
            "id": row["id"],
            "payload": json.loads(row["payload"])
            if isinstance(row["payload"], str)
            else row["payload"],
        }
        for row in rows
    ]


# --------------------------------------------------------------------------
# Cliente Anthropic falso (único dublê da suíte)
# --------------------------------------------------------------------------


@dataclass
class _Block:
    type: str
    text: str = ""


@dataclass
class _Final:
    stop_reason: str
    content: list


_TITLES = {
    "blind-hunter": "Blind Hunter",
    "edge-case-hunter": "Edge Case Hunter",
    "acceptance-auditor": "Acceptance Auditor",
}


class _FakeStream:
    def __init__(self, response: Any):
        self._response = response

    async def __aenter__(self) -> "_FakeStream":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def get_final_message(self) -> _Final:
        response = self._response
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, dict) and "error" in response:
            raise response["error"]
        payload = response.get("payload", {"findings": []})
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return _Final(
            stop_reason=response.get("stop_reason", "end_turn"),
            content=[_Block("text", text)],
        )


class _FakeMessages:
    def __init__(self, client: "FakeClient"):
        self._client = client

    def stream(self, **kwargs: Any) -> _FakeStream:
        self._client.calls.append(kwargs)
        system = kwargs.get("system", "")
        response = self._client.default
        for slug, title in _TITLES.items():
            if title in system:
                response = self._client.responses.get(slug, self._client.default)
                break
        return _FakeStream(response)


class FakeClient:
    """Cliente Anthropic falso: registra as chamadas e devolve payloads."""

    def __init__(self, responses: dict[str, Any] | None = None, default: Any = None):
        self.responses = responses or {}
        self.default = default if default is not None else {"payload": {"findings": []}}
        self.calls: list[dict] = []
        self.messages = _FakeMessages(self)


def finding(severity: str, title: str = "Achado", ac: str = "AC-001") -> dict:
    return {
        "severity": severity,
        "title": title,
        "detail": "detalhe do achado",
        "ac": ac,
        "suggestion": "sugestão do revisor",
    }


# --------------------------------------------------------------------------
# Cenário
# --------------------------------------------------------------------------


async def _seed(pool, targets: tuple[str, ...]):
    """Demanda + BR + SPEC sincronizados pelo F4, com o status pedido.

    O sync roda **duas vezes**: na primeira o artefato nasce `draft` (o
    sidecar de dúvidas ainda não existe no banco); na segunda o linter roda
    com o universo completo e o artefato é promovido.
    """
    user_id = await _new_user(pool, "ator")
    repo_id = await artifacts_service.ensure_repo(pool, REPO)
    demand_id = await _new_demand(pool, repo_id, user_id)
    docs = [
        {"path": BR_PATH, "content": BR_VALID},
        {"path": SPEC_PATH, "content": SPEC_VALID},
    ]
    await _sync(pool, docs)
    await _sync(pool, docs)
    await pool.execute("UPDATE artifacts SET demand_id = $1", uuid.UUID(demand_id))
    for target in targets:
        await apply_artifact_transition(pool, "SPEC-001", target)
    artifact = await artifacts_service.get_artifact(pool, "SPEC-001")
    assert artifact is not None
    return SimpleNamespace(
        pool=pool,
        user_id=user_id,
        repo_id=repo_id,
        demand_id=demand_id,
        artifact=artifact,
        events=lambda event_type: _events(pool, event_type),
    )


@pytest_asyncio.fixture
async def scenario(pool):
    """SPEC em `on agents review` — o estado de entrada do pipeline."""
    return await _seed(pool, ("on user review", "on agents review"))


@pytest_asyncio.fixture
async def scenario_user_review(pool):
    """SPEC em `on user review` — o estado de entrada do `approve` do F4."""
    return await _seed(pool, ("on user review",))


@pytest_asyncio.fixture
async def broken_scenario(pool):
    """SPEC com frontmatter quebrado, promoado pelo lifecycle real do F4."""
    user_id = await _new_user(pool, "ator")
    repo_id = await artifacts_service.ensure_repo(pool, REPO)
    demand_id = await _new_demand(pool, repo_id, user_id)
    await _sync(pool, [{"path": SPEC_INVALID_PATH, "content": SPEC_INVALID}])
    await pool.execute(
        "UPDATE artifacts SET demand_id = $1", uuid.UUID(demand_id)
    )
    for target in ("pending", "on user review", "on agents review"):
        await apply_artifact_transition(pool, "SPEC-002", target)
    artifact = await artifacts_service.get_artifact(pool, "SPEC-002")
    assert artifact is not None
    return SimpleNamespace(pool=pool, artifact=artifact, demand_id=demand_id)


# --------------------------------------------------------------------------
# Testes — pipeline
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_linter_error_stops_pipeline_before_llm(broken_scenario):
    """Linter com `error` barra: nenhum LLM é chamado (spec D3)."""
    client = FakeClient()

    result = await reviewers_service.run_pipeline(broken_scenario.artifact, client=client)

    assert client.calls == []
    assert result.verdict == "blocking"
    assert result.llm_available is True
    assert result.approval_ready is False
    assert [s["stage"] for s in result.stages] == ["linter"]
    assert result.linter_findings
    assert any(r.startswith("linter: SPEC-001") for r in result.blocking_reasons)


@pytest.mark.asyncio
async def test_linter_uses_f4_universe_without_path002_false_positive(scenario):
    """O universo do F4 (com os sidecars de dúvidas) não gera PATH-002 falso.

    Sem `build_universe` do F4, o `doubtsIndex` de todo artefato seria
    "inexistente" e nada passaria no gate.
    """
    result = await reviewers_service.run_pipeline(scenario.artifact, client=FakeClient())

    rules = {f["rule"] for f in result.linter_findings}
    assert "PATH-002" not in rules
    assert result.linter_findings == []
    assert result.verdict == "clean"


@pytest.mark.asyncio
async def test_linter_warning_becomes_deferred_doubt(scenario, monkeypatch):
    """`warning` do linter vira dúvida `deferred` com `source='linter'`.

    O linter do F2 só emite `error` — o `warning` é injetado no estágio do
    linter do próprio F6 (o resto do pipeline é o real).
    """

    async def fake_linter(artifact: Any):
        return (
            [
                {
                    "rule": "BR-004",
                    "severity": "warning",
                    "message": "AC-002 sem cobertura",
                    "path": None,
                    "line": None,
                    "detail": {},
                }
            ],
            None,
        )

    monkeypatch.setattr(reviewers_service, "_run_linter", fake_linter)

    result = await reviewers_service.run_pipeline(scenario.artifact, client=FakeClient())

    rows = await scenario.pool.fetch(
        "SELECT status, source, question FROM doubts WHERE artifact_id = 'SPEC-001'"
    )
    linter_doubts = [row for row in rows if row["source"] == "linter"]
    assert len(linter_doubts) == 1
    assert linter_doubts[0]["status"] == "deferred"
    assert linter_doubts[0]["question"] == "[BR-004] AC-002 sem cobertura"
    assert result.doubts_written == 1
    # o linter não bloqueia o pipeline: os 3 revisores rodaram
    assert [s["stage"] for s in result.stages] == [
        "linter",
        "blind-hunter",
        "edge-case-hunter",
        "acceptance-auditor",
    ]


@pytest.mark.asyncio
async def test_reviewer_order_is_fixed(scenario):
    """Ordem Blind -> Edge -> Acceptance, registrada em `pipeline_stage`."""
    client = FakeClient(
        {
            "blind-hunter": {"payload": {"findings": [finding("suggestion", "B")]}},
            "edge-case-hunter": {"payload": {"findings": [finding("suggestion", "E")]}},
            "acceptance-auditor": {"payload": {"findings": [finding("suggestion", "A")]}},
        }
    )

    result = await reviewers_service.run_pipeline(scenario.artifact, client=client)

    stages = [e["payload"]["stage"] for e in await scenario.events("pipeline_stage")]
    assert stages == ["linter", "blind-hunter", "edge-case-hunter", "acceptance-auditor"]
    assert [f["title"] for f in result.findings] == ["B", "E", "A"]
    assert [r["reviewer"] for r in result.review_artifacts] == [
        "blind-hunter",
        "edge-case-hunter",
        "acceptance-auditor",
    ]


@pytest.mark.asyncio
async def test_reviewer_output_schema_rejected_when_invalid(scenario):
    """Payload fora do schema -> LLM indisponível -> verdict `pending`."""
    client = FakeClient(
        {
            "blind-hunter": {
                "payload": {
                    "findings": [
                        {"severity": "blocking", "title": "sem ac", "detail": "d"}
                    ]
                }
            }
        }
    )

    result = await reviewers_service.run_pipeline(scenario.artifact, client=client)

    assert result.verdict == "pending"
    assert result.llm_available is False
    assert result.findings == []
    assert result.doubts_written == 0


@pytest.mark.asyncio
async def test_findings_have_contract_shape(scenario):
    """Todo achado tem as 5 chaves do contrato §7.4."""
    client = FakeClient(
        {
            "blind-hunter": {"payload": {"findings": [finding("blocking", "X")]}},
        }
    )

    result = await reviewers_service.run_pipeline(scenario.artifact, client=client)

    assert result.findings
    for item in result.findings:
        assert set(item) == {"severity", "title", "detail", "ac", "suggestion"}
        assert item["severity"] in {"blocking", "suggestion", "deferred"}
        assert isinstance(item["ac"], str)


@pytest.mark.asyncio
async def test_blocking_finding_creates_pending_doubt(scenario):
    client = FakeClient(
        {"blind-hunter": {"payload": {"findings": [finding("blocking")]}}}
    )

    await reviewers_service.run_pipeline(scenario.artifact, client=client)

    rows = await scenario.pool.fetch(
        "SELECT status, source, question FROM doubts WHERE artifact_id = 'SPEC-001'"
    )
    reviewer_doubts = [row for row in rows if row["source"] == "reviewer"]
    assert reviewer_doubts and reviewer_doubts[0]["status"] == "pending"
    assert reviewer_doubts[0]["question"] == "[AC-001] Achado — detalhe do achado"


@pytest.mark.asyncio
async def test_suggestion_finding_creates_deferred_doubt(scenario):
    client = FakeClient(
        {"blind-hunter": {"payload": {"findings": [finding("suggestion")]}}}
    )

    await reviewers_service.run_pipeline(scenario.artifact, client=client)

    rows = await scenario.pool.fetch(
        "SELECT status, source FROM doubts WHERE artifact_id = 'SPEC-001'"
    )
    reviewer_doubts = [row for row in rows if row["source"] == "reviewer"]
    assert reviewer_doubts and reviewer_doubts[0]["status"] == "deferred"


@pytest.mark.asyncio
async def test_verdict_clean(scenario):
    result = await reviewers_service.run_pipeline(scenario.artifact, client=FakeClient())

    assert result.verdict == "clean"
    assert result.findings == []
    assert result.doubts_written == 0


@pytest.mark.asyncio
async def test_verdict_suggestions(scenario):
    client = FakeClient(
        {"blind-hunter": {"payload": {"findings": [finding("suggestion")]}}}
    )

    result = await reviewers_service.run_pipeline(scenario.artifact, client=client)

    assert result.verdict == "suggestions"


@pytest.mark.asyncio
async def test_verdict_blocking(scenario):
    client = FakeClient(
        {"blind-hunter": {"payload": {"findings": [finding("blocking")]}}}
    )

    result = await reviewers_service.run_pipeline(scenario.artifact, client=client)

    assert result.verdict == "blocking"
    assert any(r.startswith("achado blocking:") for r in result.blocking_reasons)


@pytest.mark.asyncio
async def test_llm_failure_returns_pending_and_blocks_nothing(scenario):
    """Falha de LLM: `pending`, nada promovido, duvidas só dos revisores que rodaram."""
    from app.services.generator import LLMUnavailable

    client = FakeClient(
        {
            "blind-hunter": {"payload": {"findings": [finding("suggestion", "B")]}},
            "edge-case-hunter": {"error": LLMUnavailable("proxy fora")},
        }
    )

    result = await reviewers_service.run_pipeline(scenario.artifact, client=client)

    assert result.verdict == "pending"
    assert result.llm_available is False
    assert result.approval_ready is False
    assert result.artifact_status == "on agents review"
    row = await scenario.pool.fetchrow(
        "SELECT status FROM artifacts WHERE id = 'SPEC-001'"
    )
    assert row["status"] == "on agents review"
    # só o achado do revisor que rodou virou pendência
    rows = await scenario.pool.fetch(
        "SELECT source FROM doubts WHERE artifact_id = 'SPEC-001'"
    )
    assert [row["source"] for row in rows] == ["reviewer"]
    completed = (await scenario.events("pipeline_completed"))[0]["payload"]
    assert completed["llm_available"] is False
    assert completed["error_type"] == "LLMUnavailable"


@pytest.mark.asyncio
async def test_review_artifacts_published_with_convention_paths(scenario):
    client = FakeClient()

    await reviewers_service.run_pipeline(scenario.artifact, client=client)

    events = await scenario.events("review_artifact_written")
    assert len(events) == 3
    paths = [e["payload"]["path"] for e in events]
    assert paths == [
        "docs/implementation-artifacts/review-login-login-blind-hunter.md",
        "docs/implementation-artifacts/review-login-login-edge-case-hunter.md",
        "docs/implementation-artifacts/review-login-login-acceptance-auditor.md",
    ]
    for event in events:
        payload = event["payload"]
        assert payload["artifact_id"] == "SPEC-001"
        assert payload["sha"]
        assert payload["content"].startswith("---")


@pytest.mark.asyncio
async def test_doubts_file_published_in_canonical_v1(scenario):
    client = FakeClient(
        {"blind-hunter": {"payload": {"findings": [finding("blocking")]}}}
    )

    await reviewers_service.run_pipeline(scenario.artifact, client=client)

    event = (await scenario.events("doubts_file_rendered"))[0]["payload"]
    content = event["content"]
    assert event["artifact_id"] == "SPEC-001"
    assert event["path"] == "docs/implementation-artifacts/duvidas-spec/SPEC-001.md"
    assert content.startswith("---\nid: SPEC-001\nartifactId: SPEC-001\n")
    assert "status: pending" in content
    assert 'updatedAt: "' in content
    assert "# Dúvidas — SPEC-001" in content
    assert "Pendências: 1" in content
    assert (
        "| id | status | source | question | raised_at | resolved_at |" in content
    )
    assert "| --- | --- | --- | --- | --- | --- |" in content


@pytest.mark.asyncio
async def test_doubts_file_reflects_final_artifact_status(scenario):
    """O arquivo de dúvidas é publicado **depois** da promoção (META-006 §6)."""
    result = await reviewers_service.run_pipeline(scenario.artifact, client=FakeClient())

    assert result.artifact_status == "approved"
    content = (await scenario.events("doubts_file_rendered"))[-1]["payload"]["content"]
    assert "status: approved" in content
    assert "Pendências: 0" in content


@pytest.mark.asyncio
async def test_f4_pull_reads_doubts_file_event(scenario):
    """O `pull` do F4 lê o evento `doubts_file_rendered` e devolve o sidecar."""
    client = FakeClient(
        {"blind-hunter": {"payload": {"findings": [finding("blocking")]}}}
    )
    await reviewers_service.run_pipeline(scenario.artifact, client=client)

    pending = await artifacts_service.list_pending(scenario.pool, repo=REPO)
    sidecars = [item for item in pending if item["kind"] == "doubts"]
    assert len(sidecars) == 1
    assert sidecars[0]["path"] == "docs/implementation-artifacts/duvidas-spec/SPEC-001.md"
    assert sidecars[0]["content"].startswith("---\nid: SPEC-001")


@pytest.mark.asyncio
async def test_f4_writes_doubts_file_at_birth_using_f6(scenario):
    """O F4 não tem template próprio: chama `render_doubts_file` do F6."""
    row = await scenario.pool.fetchrow(
        "SELECT doubts_content FROM artifacts WHERE id = 'BR-001'"
    )
    assert row["doubts_content"].startswith("---\nid: BR-001\nartifactId: BR-001\n")
    assert "status: draft" in row["doubts_content"]
    assert "Pendências: 0" in row["doubts_content"]


@pytest.mark.asyncio
async def test_catalog_lists_only_open_artifacts(scenario):
    """Catálogo só lista artefato com pendência aberta."""
    outro = await scenario.pool.fetchrow(
        """
        INSERT INTO artifacts (id, repo_id, kind, module, feature, path,
                               sha, status, version, content, doubts_index)
        VALUES ('SPEC-050', $1, 'spec', 'login', 'outro',
                'docs/SPEC/login/outro.md', 'sha-050', 'on agents review', '1.0.0',
                'conteudo', 'docs/implementation-artifacts/duvidas-spec/SPEC-050.md')
        RETURNING id
        """,
        uuid.UUID(scenario.repo_id),
    )
    assert outro is not None
    await scenario.pool.execute(
        """
        INSERT INTO doubts (artifact_id, question, status, source, raised_at, resolved_at)
        VALUES ('SPEC-050', 'já resolvida', 'cleaned', 'user', now(), now())
        """
    )
    client = FakeClient(
        {"blind-hunter": {"payload": {"findings": [finding("blocking")]}}}
    )

    await reviewers_service.run_pipeline(scenario.artifact, client=client)

    event = (await scenario.events("doubts_catalog_rendered"))[0]["payload"]
    assert event["kind"] == "spec"
    assert event["path"] == "docs/implementation-artifacts/duvidas-spec.md"
    assert "SPEC-001" in event["content"]
    assert "SPEC-050" not in event["content"]


@pytest.mark.asyncio
async def test_approval_blocked_by_open_doubt(scenario):
    """Dúvida aberta (mesmo `deferred`) impede a promoção (META-006 §8)."""
    await scenario.pool.execute(
        """
        INSERT INTO doubts (artifact_id, question, status, source, raised_at)
        VALUES ('SPEC-001', 'pendência anterior', 'deferred', 'user', now())
        """
    )

    result = await reviewers_service.run_pipeline(scenario.artifact, client=FakeClient())

    assert result.approval_ready is False
    assert result.artifact_status == "on agents review"
    row = await scenario.pool.fetchrow(
        "SELECT status FROM artifacts WHERE id = 'SPEC-001'"
    )
    assert row["status"] == "on agents review"
    assert "dúvida deferida ainda não resolvida" in result.blocking_reasons


@pytest.mark.asyncio
async def test_approval_succeeds_when_all_cleaned(scenario):
    """Linter limpo + 3 revisores rodados + nenhuma dúvida -> `approved`."""
    result = await reviewers_service.run_pipeline(scenario.artifact, client=FakeClient())

    assert result.verdict == "clean"
    assert result.approval_ready is True
    assert result.artifact_status == "approved"
    row = await scenario.pool.fetchrow(
        "SELECT status FROM artifacts WHERE id = 'SPEC-001'"
    )
    assert row["status"] == "approved"
    completed = (await scenario.events("pipeline_completed"))[0]["payload"]
    assert completed["approval_ready"] is True
    assert completed["artifact_status"] == "approved"


@pytest.mark.asyncio
async def test_approval_requires_llm_available(scenario):
    """Com o LLM fora, nada é promovido."""
    from app.services.generator import LLMUnavailable

    client = FakeClient(default={"error": LLMUnavailable("proxy fora")})

    result = await reviewers_service.run_pipeline(scenario.artifact, client=client)

    assert result.llm_available is False
    assert result.approval_ready is False
    assert result.artifact_status == "on agents review"
    row = await scenario.pool.fetchrow(
        "SELECT status FROM artifacts WHERE id = 'SPEC-001'"
    )
    assert row["status"] == "on agents review"


# --------------------------------------------------------------------------
# Testes — router de reviews
#
# A matriz de ownership (Contrato Comum §8) restringe o F6 a dois arquivos de
# teste — `test_pipeline.py` e `test_doubts.py` — então os testes das rotas
# (`POST /api/reviews`, `GET /api/reviews`) moram aqui.
# --------------------------------------------------------------------------

REVIEW_BODY = {
    "sha": "9f2c1ab4d7e5c6b8a0f1e2d3c4b5a697889900aa",
    "verdict": "clean",
    "findings": [
        {
            "severity": "suggestion",
            "title": "Falta teste de borda",
            "detail": "AC-003 não cobre e-mail com ponto no fim",
            "ac": "AC-003",
            "suggestion": 'Adicionar caso com "a@b."',
        }
    ],
    "demand_id": "demand-1",
    "message": "feat(login): adiciona validação de senha",
    "branch": "feat/login",
    "author": "brunosprotte",
    "files": ["src/auth/login.ts"],
}


@pytest.mark.asyncio
async def test_post_review_creates_review_and_transitions_demand(
    scenario, client, auth_token
):
    body = {**REVIEW_BODY, "demand_id": scenario.demand_id}

    response = await client.post("/api/reviews", json=body, headers=_auth(auth_token))

    assert response.status_code == 201
    data = response.json()
    assert data["sha"] == REVIEW_BODY["sha"]
    assert data["verdict"] == "clean"
    assert data["demand_status"] == "review"
    assert data["findings"][0]["ac"] == "AC-003"

    row = await scenario.pool.fetchrow(
        "SELECT status FROM demands WHERE id = $1", uuid.UUID(scenario.demand_id)
    )
    assert row["status"] == "review"

    reviews = await scenario.pool.fetch("SELECT id FROM reviews")
    commits = await scenario.pool.fetch("SELECT id FROM commits")
    assert len(reviews) == 1
    assert len(commits) == 1

    reported = (await scenario.events("review_reported"))[0]["payload"]
    assert reported["verdict"] == "clean"
    assert reported["findings"] == 1
    assert reported["demand_status"] == "review"


@pytest.mark.asyncio
async def test_post_review_blocking_transitions_back_to_in_progress(
    scenario, client, auth_token
):
    await scenario.pool.execute(
        "UPDATE demands SET status = 'review' WHERE id = $1",
        uuid.UUID(scenario.demand_id),
    )
    body = {
        **REVIEW_BODY,
        "demand_id": scenario.demand_id,
        "verdict": "blocking",
    }

    response = await client.post("/api/reviews", json=body, headers=_auth(auth_token))

    assert response.status_code == 201
    assert response.json()["demand_status"] == "in_progress"
    row = await scenario.pool.fetchrow(
        "SELECT status FROM demands WHERE id = $1", uuid.UUID(scenario.demand_id)
    )
    assert row["status"] == "in_progress"


@pytest.mark.asyncio
async def test_post_review_demand_not_found(scenario, client, auth_token):
    body = {**REVIEW_BODY, "demand_id": "6f1d2c8e-0a3b-4f5d-9e77-2b1c0a9d4e55"}

    response = await client.post("/api/reviews", json=body, headers=_auth(auth_token))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert await scenario.pool.fetch("SELECT id FROM reviews") == []


@pytest.mark.asyncio
async def test_post_review_empty_sha_is_422(scenario, client, auth_token):
    body = {**REVIEW_BODY, "demand_id": scenario.demand_id, "sha": ""}

    response = await client.post("/api/reviews", json=body, headers=_auth(auth_token))

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_review_accepts_kit_shape_without_verdict(
    scenario, client, auth_token
):
    """Shape do kit: `sha` + `demand_id` obrigatórios, `verdict` extra (Contrato Comum §4.2 b)."""
    body = {"sha": REVIEW_BODY["sha"], "demand_id": scenario.demand_id}

    response = await client.post("/api/reviews", json=body, headers=_auth(auth_token))

    assert response.status_code == 201
    data = response.json()
    assert data["verdict"] == "pending"
    assert data["findings"] == []


@pytest.mark.asyncio
async def test_post_review_requires_scope(scenario, client, pool):
    token = await _token_with_scopes(pool, scenario.user_id, ["demand:claim"])
    body = {**REVIEW_BODY, "demand_id": scenario.demand_id}

    response = await client.post("/api/reviews", json=body, headers=_auth(token))

    assert response.status_code == 403
    assert await pool.fetch("SELECT id FROM reviews") == []


@pytest.mark.asyncio
async def test_post_review_illegal_transition_is_409_without_writing(
    scenario, client, auth_token, monkeypatch
):
    """Transição ilegal -> 409 e **nada** gravado (sem estado parcial)."""
    from app.services import lifecycle

    monkeypatch.setattr(lifecycle, "can_transition", lambda *args: False)
    body = {**REVIEW_BODY, "demand_id": scenario.demand_id}

    response = await client.post("/api/reviews", json=body, headers=_auth(auth_token))

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "illegal_transition"
    assert error["detail"]["current"] == "in_progress"
    assert error["detail"]["target"] == "review"
    assert await scenario.pool.fetch("SELECT id FROM reviews") == []
    assert await scenario.pool.fetch("SELECT id FROM commits") == []
    assert await scenario.events("review_reported") == []


@pytest.mark.asyncio
async def test_post_review_without_lifecycle_keeps_demand_status(
    scenario, client, auth_token, monkeypatch
):
    """Fallback degradado: sem o F4, o status da demanda não muda.

    O lifecycle é o **único** caminho para escrever status (invariante 2); sem
    ele, o F6 registra a review e não mexe no estado da demanda.
    """
    monkeypatch.setitem(sys.modules, "app.services.lifecycle", None)
    body = {**REVIEW_BODY, "demand_id": scenario.demand_id}

    response = await client.post("/api/reviews", json=body, headers=_auth(auth_token))

    assert response.status_code == 201
    assert response.json()["demand_status"] == "in_progress"
    row = await scenario.pool.fetchrow(
        "SELECT status FROM demands WHERE id = $1", uuid.UUID(scenario.demand_id)
    )
    assert row["status"] == "in_progress"


@pytest.mark.asyncio
async def test_post_review_reuses_commit_for_same_sha(scenario, client, auth_token):
    body = {**REVIEW_BODY, "demand_id": scenario.demand_id}

    first = await client.post("/api/reviews", json=body, headers=_auth(auth_token))
    second = await client.post("/api/reviews", json=body, headers=_auth(auth_token))

    assert first.json()["commit_id"] == second.json()["commit_id"]
    assert len(await scenario.pool.fetch("SELECT id FROM commits")) == 1
    assert len(await scenario.pool.fetch("SELECT id FROM reviews")) == 2


@pytest.mark.asyncio
async def test_get_reviews_requires_demand_parameter(scenario, client, auth_token):
    response = await client.get("/api/reviews", headers=_auth(auth_token))

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "missing_parameter"
    assert error["detail"] == {"parameter": "demand"}


@pytest.mark.asyncio
async def test_get_reviews_demand_not_found(scenario, client, auth_token):
    response = await client.get(
        "/api/reviews",
        params={"demand": "6f1d2c8e-0a3b-4f5d-9e77-2b1c0a9d4e55"},
        headers=_auth(auth_token),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_get_reviews_lists_newest_first(scenario, client, auth_token):
    body = {**REVIEW_BODY, "demand_id": scenario.demand_id}
    await client.post("/api/reviews", json=body, headers=_auth(auth_token))
    await client.post(
        "/api/reviews",
        json={**body, "sha": "abc1234", "findings": []},
        headers=_auth(auth_token),
    )

    response = await client.get(
        "/api/reviews",
        params={"demand": scenario.demand_id},
        headers=_auth(auth_token),
    )

    assert response.status_code == 200
    data = response.json()
    assert data["demand_id"] == scenario.demand_id
    assert [r["sha"] for r in data["reviews"]] == ["abc1234", REVIEW_BODY["sha"]]
    assert data["reviews"][0]["findings"] == []


@pytest.mark.asyncio
async def test_get_reviews_includes_findings_and_commit_sha(
    scenario, client, auth_token
):
    body = {**REVIEW_BODY, "demand_id": scenario.demand_id}
    await client.post("/api/reviews", json=body, headers=_auth(auth_token))

    response = await client.get(
        "/api/reviews",
        params={"demand": scenario.demand_id},
        headers=_auth(auth_token),
    )

    review = response.json()["reviews"][0]
    assert review["sha"] == REVIEW_BODY["sha"]
    assert review["findings"][0]["title"] == "Falta teste de borda"
    assert review["created_at"]


@pytest.mark.asyncio
async def test_f4_approve_delegates_to_f6_pipeline(
    scenario_user_review, client, auth_token, monkeypatch
):
    """O `approve` do F4 chama o `run_pipeline` do F6 (contrato §8.1, D8)."""
    from app.services import generator

    def _no_llm():
        raise generator.LLMUnavailable("sem credencial")

    monkeypatch.setattr(generator, "build_client", _no_llm)

    response = await client.post(
        "/api/artifacts/SPEC-001/approve", headers=_auth(auth_token)
    )

    assert response.status_code == 200
    body = response.json()
    # LLM fora: nada bloqueia, nada é promovido (design master §19)
    assert body["pipeline"]["verdict"] == "pending"
    assert body["pipeline"]["llm_available"] is False
    assert body["artifact"]["status"] == "on agents review"
    stages = [e["payload"]["stage"] for e in await scenario_user_review.events("pipeline_stage")]
    assert stages[0] == "linter"
