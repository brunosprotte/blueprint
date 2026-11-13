"""Testes da fase F5 — geração de BR e SPEC.

Sem chamada real à API: o `GenerationContext.client` recebe um fake que devolve o
JSON do schema. As rotas HTTP usam a fixture `client` do conftest do F1, com o
cliente Anthropic trocado por `monkeypatch` em `generator.build_client`.

O banco é o de teste do F1 (`conftest.pool`), separado do banco de dev.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from types import SimpleNamespace
from typing import Any

import pytest

from app.routers import generation
from app.services import generator


def _api_token() -> tuple[str, str]:
    """Token opaco no formato do contrato §6: `sdd_<base64url(32)>` + sha256 hex.

    Montado aqui (e não via `app.auth`) porque o `sys.modules` pode estar com
    dublês de outra fase — o token é só o valor bruto e o sha256 do valor bruto.
    """
    raw = "sdd_" + secrets.token_urlsafe(32)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()

# --------------------------------------------------------------------------- #
# Fake do SDK anthropic (nenhuma chamada de rede)
# --------------------------------------------------------------------------- #


class FakeStream:
    """Contexto assíncrono que devolve a mensagem final."""

    def __init__(self, message: Any) -> None:
        self._message = message

    async def __aenter__(self) -> "FakeStream":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def get_final_message(self) -> Any:
        return self._message


class FakeMessages:
    """`client.messages` do SDK: registra as chamadas e devolve o JSON do schema."""

    def __init__(self, owner: "FakeClient") -> None:
        self._owner = owner

    def stream(self, **kwargs: Any) -> FakeStream:
        self._owner.calls.append(kwargs)
        if self._owner.raises is not None:
            raise self._owner.raises
        payload = (
            self._owner.payloads.pop(0) if self._owner.payloads else self._owner.payload
        )
        stop_reason = self._owner.stop_reason
        message = SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(payload))],
            stop_reason=stop_reason,
            stop_details=(
                SimpleNamespace(category="general_harms")
                if stop_reason == "refusal"
                else None
            ),
            usage=SimpleNamespace(input_tokens=120, output_tokens=340),
        )
        return FakeStream(message)


class FakeClient:
    """Cliente Anthropic falso — devolve o payload do schema estruturado."""

    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        *,
        payloads: list[dict[str, Any]] | None = None,
        stop_reason: str = "end_turn",
        raises: Exception | None = None,
    ) -> None:
        self.payload = payload or {}
        self.payloads = list(payloads or [])
        self.stop_reason = stop_reason
        self.raises = raises
        self.calls: list[dict[str, Any]] = []
        self.messages = FakeMessages(self)


# --------------------------------------------------------------------------- #
# Payloads do modelo
# --------------------------------------------------------------------------- #

BR_BODY = """## Objetivo

Permite que usuários cadastrados autentiquem no sistema.

## Contexto

O acesso às áreas protegidas exige identidade verificada.

## Atores

- Usuário cadastrado
- Administrador

## Capacidades

- Autenticar com e-mail e senha

## Regras de Negócio

- RN-001: todo acesso autenticado é registrado.

## Restrições

- A autenticação não pode depender de informação técnica no documento.

## Exceções

- Credencial inválida devolve recusa, sem criar sessão.

## Acceptance Criteria

- AC-001: Usuário cadastrado autentica com e-mail e senha corretos
- AC-002: Credencial inválida é recusada sem criar sessão

## Open Questions

- A senha pode ser redefinida por e-mail ou por token?
"""

BR_PAYLOAD: dict[str, Any] = {
    "frontmatter": {
        "module": "login",
        "feature": "login",
        "title": "Autenticação de usuários com e-mail e senha",
        "description": "Permite que usuários cadastrados autentiquem e acessem áreas protegidas.",
        "tags": ["login", "autenticacao"],
    },
    "body": BR_BODY,
}


def br_payload(feature: str = "login") -> dict[str, Any]:
    """Payload do modelo para uma BR — o `feature` define o path do artefato."""
    payload = json.loads(json.dumps(BR_PAYLOAD))
    payload["frontmatter"]["feature"] = feature
    return payload

BR_SECTIONS = (
    "Objetivo",
    "Contexto",
    "Atores",
    "Capacidades",
    "Regras de Negócio",
    "Restrições",
    "Exceções",
    "Acceptance Criteria",
    "Open Questions",
)

SPEC_SECTIONS = (
    "Objetivo",
    "Escopo",
    "Responsabilidade",
    "Entradas",
    "Saídas",
    "Fluxo principal",
    "Fluxos alternativos",
    "Validações",
    "Failures",
    "Pré-condições",
    "Pós-condições",
    "Acceptance Criteria atendidos",
    "Dependências",
    "Blueprint Documents necessários",
)


def _spec_body(title: str, acs: list[str]) -> str:
    """Corpo de uma SPEC com as 14 seções de SK-002 §10.

    As ACs ficam na seção "Acceptance Criteria atendidos" do CORPO (Contrato Comum
    §8.4 D7) — é de lá que o BR-004 do linter lê a cobertura.
    """
    ac_lines = "\n".join(f"- {ac}" for ac in acs)
    blocks = []
    for section in SPEC_SECTIONS:
        if section == "Acceptance Criteria atendidos":
            content = ac_lines
        elif section == "Objetivo":
            content = title
        else:
            content = f"conteúdo de {section}"
        blocks.append(f"## {section}\n\n{content}\n")
    return "\n".join(blocks)


def spec_payload() -> dict[str, Any]:
    """Payload do modelo para um lote de 2 SPECs com uma aresta `depends_on`."""
    return {
        "specs": [
            {
                "feature": "login-api",
                "title": "Endpoint de autenticação por e-mail e senha",
                "description": "Expõe a autenticação de usuário e devolve sessão ao cliente autorizado.",
                "tags": ["login", "api"],
                "complexity": "MEDIUM",
                "acceptanceCriteria": ["AC-001"],
                "body": _spec_body("Endpoint de autenticação", ["AC-001"]),
            },
            {
                "feature": "login-tests",
                "title": "Testes da autenticação",
                "description": "Verifica o fluxo de autenticação do usuário.",
                "tags": ["login", "testes"],
                "complexity": "LOW",
                "acceptanceCriteria": ["AC-002"],
                "body": _spec_body("Testes da autenticação", ["AC-002"]),
            },
        ],
        "edges": [
            {"parentFeature": "login-tests", "childFeature": "login-api", "type": "depends_on"}
        ],
    }


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
async def demand(pool) -> dict[str, str]:
    """Demanda `claimed`, com repo e usuário de teste."""
    repo_id = await pool.fetchval(
        "INSERT INTO repos (owner, name) VALUES ('acme', 'app') RETURNING id"
    )
    user_id = await pool.fetchval(
        "INSERT INTO users (github_id, login) VALUES ($1, $2) RETURNING id", 313131, "f5-tester"
    )
    demand_id = await pool.fetchval(
        "INSERT INTO demands (repo_id, module, title, body, status, created_by)"
        " VALUES ($1,'login',$2,$3,'claimed',$4) RETURNING id",
        repo_id,
        "Autenticação de usuários com e-mail e senha",
        "Usuários cadastrados precisam entrar no sistema.",
        user_id,
    )
    return {"id": str(demand_id), "repo_id": str(repo_id), "user_id": str(user_id)}


@pytest.fixture
async def limited_token(pool) -> str:
    """Token de API sem o escopo `demand:write`."""
    raw, token_hash = _api_token()
    user_id = await pool.fetchval(
        "INSERT INTO users (github_id, login) VALUES ($1, $2) RETURNING id", 626262, "sem-escopo"
    )
    await pool.execute(
        "INSERT INTO tokens (user_id, token_hash, scopes) VALUES ($1, $2, $3)",
        user_id,
        token_hash,
        ["demand:claim"],
    )
    return raw


# --------------------------------------------------------------------------- #
# Geração de BR
# --------------------------------------------------------------------------- #


async def test_generate_br_frontmatter_matches_skill_template(pool, demand) -> None:
    """12 campos de SK-001 §16, na ordem exata."""
    status, payload = await generation.handle_generate_br(
        pool, demand["id"], client=FakeClient(BR_PAYLOAD)
    )
    assert status == 200
    frontmatter = payload["artifact"]["frontmatter"]
    assert list(frontmatter) == [
        "id",
        "module",
        "feature",
        "type",
        "title",
        "description",
        "status",
        "tags",
        "timestamp",
        "doubtsIndex",
        "version",
        "generatedBy",
    ]
    assert frontmatter["id"] == "BR-001"
    assert frontmatter["module"] == "login"
    assert frontmatter["feature"] == "login"
    assert frontmatter["type"] == "Business Rule"
    assert frontmatter["status"] == "draft"
    assert frontmatter["tags"] == ["login", "autenticacao"]
    assert frontmatter["version"] == "1.0.0"
    assert frontmatter["generatedBy"] == "SK-001"
    assert frontmatter["timestamp"].endswith("Z")
    assert frontmatter["doubtsIndex"] == "docs/implementation-artifacts/duvidas-br/BR-001.md"
    assert payload["artifact"]["path"] == "docs/BR/login/login.md"
    assert payload["artifact"]["content"].startswith("---\nid: BR-001\n")


async def test_generate_br_body_has_all_sections(pool, demand) -> None:
    """9 seções de SK-001 §14, na ordem."""
    _status, payload = await generation.handle_generate_br(
        pool, demand["id"], client=FakeClient(BR_PAYLOAD)
    )
    content = payload["artifact"]["content"]
    positions = [content.index(f"## {section}") for section in BR_SECTIONS]
    assert positions == sorted(positions)


async def test_generate_br_creates_doubts_file(pool, demand) -> None:
    """Arquivo de dúvidas no formato canônico v1, com o `doubtsIndex` bate."""
    _status, payload = await generation.handle_generate_br(
        pool, demand["id"], client=FakeClient(BR_PAYLOAD)
    )
    doubts_file = payload["doubts_file"]
    assert doubts_file["path"] == "docs/implementation-artifacts/duvidas-br/BR-001.md"
    assert doubts_file["path"] == payload["artifact"]["frontmatter"]["doubtsIndex"]
    content = doubts_file["content"]
    assert content.startswith("---\nid: BR-001\nartifactId: BR-001\nstatus: draft\n")
    assert 'updatedAt: "' in content
    assert "# Dúvidas — BR-001" in content
    assert "Pendências: 1" in content
    assert "| id | status | source | question | raised_at | resolved_at |" in content

    # O arquivo também é publicado em `events.payload` (sem tabela nova) e o
    # conteúdo publicado é byte a byte o devolvido na rota.
    published = json.loads(
        await pool.fetchval(
            "SELECT payload FROM events WHERE type = 'doubts_file_rendered' ORDER BY id DESC LIMIT 1"
        )
    )
    assert published["path"] == doubts_file["path"]
    assert published["content"] == content


async def test_generate_br_open_questions_become_doubt_rows(pool, demand) -> None:
    """Cada Open Question vira uma linha em `doubts` com `source='user'`."""
    await generation.handle_generate_br(pool, demand["id"], client=FakeClient(BR_PAYLOAD))
    rows = await pool.fetch(
        "SELECT artifact_id, question, status, source FROM doubts ORDER BY question"
    )
    assert len(rows) == 1
    assert rows[0]["artifact_id"] == "BR-001"
    assert rows[0]["question"] == "A senha pode ser redefinida por e-mail ou por token?"
    assert rows[0]["status"] == "pending"
    assert rows[0]["source"] == "user"


# --------------------------------------------------------------------------- #
# Geração de SPECs
# --------------------------------------------------------------------------- #


async def _make_br(pool, demand) -> dict[str, Any]:
    """Gera a BR que serve de origem das SPECs."""
    _status, payload = await generation.handle_generate_br(
        pool, demand["id"], client=FakeClient(BR_PAYLOAD)
    )
    return payload["artifact"]


async def test_generate_specs_frontmatter_matches_skill_template(pool, demand) -> None:
    """16 campos de frontmatter da SPEC (SK-002 §15 + complexity + dependsOn)."""
    br = await _make_br(pool, demand)
    status, payload = await generation.handle_generate_specs(
        pool, br["id"], client=FakeClient(spec_payload())
    )
    assert status == 200
    frontmatter = payload["artifacts"][0]["frontmatter"]
    assert list(frontmatter) == [
        "id",
        "module",
        "feature",
        "type",
        "title",
        "description",
        "createdBy",
        "createdFrom",
        "technologyPack",
        "status",
        "tags",
        "complexity",
        "dependsOn",
        "timestamp",
        "doubtsIndex",
        "version",
    ]
    assert frontmatter["id"] == "SPEC-001"
    assert frontmatter["module"] == "login"
    assert frontmatter["feature"] == "login-api"
    assert frontmatter["type"] == "Functional Specification"
    assert frontmatter["createdBy"] == "SK-002"
    assert frontmatter["createdFrom"] == "BR-001"
    assert frontmatter["technologyPack"] == "TP-001"
    assert frontmatter["status"] == "draft"
    assert frontmatter["complexity"] == "MEDIUM"
    assert "complexity:MEDIUM" in frontmatter["tags"]
    assert frontmatter["version"] == "1.0.0"
    assert frontmatter["doubtsIndex"] == "docs/implementation-artifacts/duvidas-spec/SPEC-001.md"
    assert payload["artifacts"][0]["path"] == "docs/SPEC/login/login-api.md"
    assert [doubts["path"] for doubts in payload["doubts_files"]] == [
        "docs/implementation-artifacts/duvidas-spec/SPEC-001.md",
        "docs/implementation-artifacts/duvidas-spec/SPEC-002.md",
    ]


async def test_spec_depends_on_lists_allocated_ids(pool, demand) -> None:
    """`dependsOn` leva os IDs que o servidor alocou (Contrato Comum §8.4 D3)."""
    br = await _make_br(pool, demand)
    _status, payload = await generation.handle_generate_specs(
        pool, br["id"], client=FakeClient(spec_payload())
    )
    by_feature = {
        artifact["frontmatter"]["feature"]: artifact for artifact in payload["artifacts"]
    }
    # login-tests depende de login-api → parent = a dependente (SPEC-002).
    assert by_feature["login-tests"]["frontmatter"]["dependsOn"] == ["SPEC-001"]
    assert by_feature["login-api"]["frontmatter"]["dependsOn"] == []
    # Os IDs citados existem no banco.
    for artifact in payload["artifacts"]:
        for dependency in artifact["frontmatter"]["dependsOn"]:
            row = await pool.fetchrow(
                "SELECT id FROM artifacts WHERE id = $1 AND kind = 'spec'", dependency
            )
            assert row is not None


async def test_contract_api_returns_generated_artifact(pool, demand) -> None:
    """`generate_br`/`generate_specs` devolvem o `GeneratedArtifact` do Contrato §7.3."""
    ctx = generator.GenerationContext(
        pool=pool,
        demand_id=demand["id"],
        repo_id=demand["repo_id"],
        module="login",
        method_context=await generator.resolve_method_context("br", "login"),
        repo_context=await generator.resolve_repo_context(demand["repo_id"], "login"),
        client=FakeClient(BR_PAYLOAD),
    )
    demand_row = await pool.fetchrow(
        "SELECT id, repo_id, module, title, body, status FROM demands WHERE id = $1",
        demand["id"],
    )
    artifact = await generator.generate_br(demand_row, ctx)
    assert set(artifact) == {
        "id",
        "kind",
        "path",
        "content",
        "frontmatter",
        "doubts_index_path",
    }
    assert artifact["kind"] == "br"

    spec_ctx = generator.GenerationContext(
        pool=pool,
        demand_id=demand["id"],
        repo_id=demand["repo_id"],
        module="login",
        method_context=await generator.resolve_method_context(
            "spec", "login", br_content=artifact["content"]
        ),
        repo_context=ctx.repo_context,
        client=FakeClient(spec_payload()),
    )
    br_row = await pool.fetchrow(
        "SELECT id, demand_id, repo_id, kind, module, feature, path, sha, status, version, content"
        " FROM artifacts WHERE id = $1",
        artifact["id"],
    )
    specs = await generator.generate_specs(br_row, spec_ctx)
    assert len(specs) == 2
    assert all(set(spec) == set(artifact) for spec in specs)
    assert all(spec["kind"] == "spec" for spec in specs)


async def test_generate_specs_body_has_14_sections(pool, demand) -> None:
    """14 seções de SK-002 §10, na ordem."""
    br = await _make_br(pool, demand)
    _status, payload = await generation.handle_generate_specs(
        pool, br["id"], client=FakeClient(spec_payload())
    )
    content = payload["artifacts"][0]["content"]
    positions = [content.index(f"## {section}") for section in SPEC_SECTIONS]
    assert positions == sorted(positions)
    assert len(SPEC_SECTIONS) == 14


async def test_spec_edges_derives_from_br(pool, demand) -> None:
    """Uma aresta `derives_from` por SPEC, com parent = SPEC e child = BR (§8.4 D4)."""
    br = await _make_br(pool, demand)
    _status, payload = await generation.handle_generate_specs(
        pool, br["id"], client=FakeClient(spec_payload())
    )
    derives = [edge for edge in payload["spec_edges"] if edge["type"] == "derives_from"]
    assert len(derives) == 2
    assert {edge["child_id"] for edge in derives} == {"BR-001"}
    assert {edge["parent_id"] for edge in derives} == {"SPEC-001", "SPEC-002"}


async def test_spec_edges_depends_on_resolved(pool, demand) -> None:
    """`parentFeature`/`childFeature` viram arestas com o ID real do servidor."""
    br = await _make_br(pool, demand)
    _status, payload = await generation.handle_generate_specs(
        pool, br["id"], client=FakeClient(spec_payload())
    )
    depends = [edge for edge in payload["spec_edges"] if edge["type"] == "depends_on"]
    assert depends == [{"parent_id": "SPEC-002", "child_id": "SPEC-001", "type": "depends_on"}]
    rows = await pool.fetch(
        "SELECT parent_id, child_id, type FROM spec_edges WHERE type = 'depends_on'"
    )
    assert [dict(row) for row in rows] == [
        {"parent_id": "SPEC-002", "child_id": "SPEC-001", "type": "depends_on"}
    ]


async def test_spec_edges_unresolved_is_skipped_with_event(pool, demand) -> None:
    """Aresta órfã não é gravada e gera o evento `spec_edge_unresolved`."""
    br = await _make_br(pool, demand)
    payload_model = spec_payload()
    payload_model["edges"].append(
        {"parentFeature": "login-api", "childFeature": "fantasma", "type": "depends_on"}
    )
    _status, payload = await generation.handle_generate_specs(
        pool, br["id"], client=FakeClient(payload_model)
    )
    assert {"parent_id": "SPEC-002", "child_id": "SPEC-001", "type": "depends_on"} in payload[
        "spec_edges"
    ]
    assert not [edge for edge in payload["spec_edges"] if edge["child_id"] == "fantasma"]
    rows = await pool.fetch("SELECT payload FROM events WHERE type = 'spec_edge_unresolved'")
    assert len(rows) == 1
    event = json.loads(rows[0]["payload"])
    assert event["childFeature"] == "fantasma"
    assert event["reason"] == "not_resolved"


async def test_every_ac_covered_by_some_spec(pool, demand) -> None:
    """Toda AC da BR aparece no CORPO de alguma SPEC (Contrato Comum §8.4 D7)."""
    br = await _make_br(pool, demand)
    client = FakeClient(spec_payload())
    _status, payload = await generation.handle_generate_specs(pool, br["id"], client=client)
    covered: set[str] = set()
    for artifact in payload["artifacts"]:
        covered |= set(generator.extract_acceptance_criteria(artifact["content"]))
    assert covered >= {"AC-001", "AC-002"}
    # As ACs NÃO vão para o frontmatter da SPEC.
    for artifact in payload["artifacts"]:
        assert "acceptanceCriteria" not in artifact["frontmatter"]
    prompt = client.calls[0]["messages"][0]["content"]
    assert "# Acceptance Criteria da BR" in prompt
    assert "AC-001" in prompt and "AC-002" in prompt


# --------------------------------------------------------------------------- #
# Idempotência e concorrência
# --------------------------------------------------------------------------- #


async def test_generate_br_is_idempotent(pool, demand) -> None:
    """2ª chamada devolve o mesmo id, `created=false`, e não chama o modelo."""
    client = FakeClient(BR_PAYLOAD)
    status, first = await generation.handle_generate_br(pool, demand["id"], client=client)
    assert status == 200
    assert first["created"] is True
    calls_after_first = len(client.calls)

    status, second = await generation.handle_generate_br(pool, demand["id"], client=client)
    assert status == 200
    assert second["created"] is False
    assert second["idempotent"] is True
    assert second["artifact"]["id"] == first["artifact"]["id"]
    assert len(client.calls) == calls_after_first

    rows = await pool.fetch("SELECT id FROM artifacts WHERE kind = 'br'")
    assert len(rows) == 1


async def test_generate_specs_is_idempotent(pool, demand) -> None:
    """Idem para as SPECs."""
    br = await _make_br(pool, demand)
    client = FakeClient(spec_payload())
    status, first = await generation.handle_generate_specs(pool, br["id"], client=client)
    assert status == 200
    calls_after_first = len(client.calls)

    status, second = await generation.handle_generate_specs(pool, br["id"], client=client)
    assert status == 200
    assert second["created"] is False
    assert second["idempotent"] is True
    assert [a["id"] for a in second["artifacts"]] == [a["id"] for a in first["artifacts"]]
    assert len(client.calls) == calls_after_first
    rows = await pool.fetch("SELECT id FROM artifacts WHERE kind = 'spec'")
    assert len(rows) == 2


async def test_ids_are_unique_under_concurrency(pool, demand) -> None:
    """Duas gerações concorrentes pegam IDs distintos."""
    import asyncio

    second = await pool.fetchval(
        "INSERT INTO demands (repo_id, module, title, body, status, created_by)"
        " VALUES ($1,'login','Outra demanda','corpo','claimed',$2) RETURNING id",
        demand["repo_id"],
        demand["user_id"],
    )
    results = await asyncio.gather(
        generation.handle_generate_br(
            pool, demand["id"], client=FakeClient(br_payload("login"))
        ),
        generation.handle_generate_br(
            pool, str(second), client=FakeClient(br_payload("recuperacao-senha"))
        ),
    )
    ids = {payload["artifact"]["id"] for _status, payload in results}
    assert ids == {"BR-001", "BR-002"}
    rows = await pool.fetch("SELECT id FROM artifacts WHERE kind = 'br' ORDER BY id")
    assert [row["id"] for row in rows] == ["BR-001", "BR-002"]


# --------------------------------------------------------------------------- #
# Erros
# --------------------------------------------------------------------------- #


async def test_llm_failure_returns_503_and_resets_demand(pool, demand) -> None:
    """503 `llm_unavailable`, demanda `claimed` volta para `open`, evento registrado."""
    client = FakeClient(BR_PAYLOAD, stop_reason="max_tokens")
    status, payload = await generation.handle_generate_br(pool, demand["id"], client=client)
    assert status == 503
    assert payload["error"]["code"] == "llm_unavailable"
    assert payload["error"]["detail"]["stage"] == "br"

    row = await pool.fetchrow("SELECT status FROM demands WHERE id = $1", demand["id"])
    assert row["status"] == "open"

    events = await pool.fetch("SELECT payload FROM events WHERE type = 'generation_failed'")
    assert len(events) == 1
    event = json.loads(events[0]["payload"])
    assert event["reason"] == "llm_unavailable"
    assert event["reset"] is True


async def test_llm_failure_writes_nothing(pool, demand) -> None:
    """Nada gravado em `artifacts` quando o modelo falha."""
    client = FakeClient(BR_PAYLOAD, raises=RuntimeError("proxy fora"))
    status, _payload = await generation.handle_generate_br(pool, demand["id"], client=client)
    assert status == 503
    assert await pool.fetchval("SELECT count(*) FROM artifacts") == 0
    assert await pool.fetchval("SELECT count(*) FROM doubts") == 0
    assert await pool.fetchval("SELECT count(*) FROM spec_edges") == 0


async def test_demand_in_progress_stays_in_progress_on_failure(pool, demand) -> None:
    """`in_progress` permanece `in_progress` — o evento carrega `reset=false`."""
    await pool.execute("UPDATE demands SET status = 'in_progress' WHERE id = $1", demand["id"])
    client = FakeClient(BR_PAYLOAD, stop_reason="max_tokens")
    status, _payload = await generation.handle_generate_br(pool, demand["id"], client=client)
    assert status == 503
    row = await pool.fetchrow("SELECT status FROM demands WHERE id = $1", demand["id"])
    assert row["status"] == "in_progress"
    event = json.loads(
        await pool.fetchval("SELECT payload FROM events WHERE type = 'generation_failed'")
    )
    assert event["reset"] is False


async def test_demand_done_returns_409(pool, demand) -> None:
    """409 `illegal_transition`, sem chamar o modelo."""
    await pool.execute("UPDATE demands SET status = 'done' WHERE id = $1", demand["id"])
    client = FakeClient(BR_PAYLOAD)
    status, payload = await generation.handle_generate_br(pool, demand["id"], client=client)
    assert status == 409
    assert payload["error"]["code"] == "illegal_transition"
    assert client.calls == []
    assert await pool.fetchval("SELECT count(*) FROM artifacts") == 0


async def test_invalid_module_feature_returns_422(pool, demand) -> None:
    """Slug inválido → 422, nada gravado."""
    bad = json.loads(json.dumps(BR_PAYLOAD))
    bad["frontmatter"]["feature"] = "Login Com Maiúscula"
    client = FakeClient(bad)
    status, payload = await generation.handle_generate_br(pool, demand["id"], client=client)
    assert status == 422
    assert payload["error"]["code"] == "invalid_module_feature"
    assert await pool.fetchval("SELECT count(*) FROM artifacts") == 0
    assert await pool.fetchval("SELECT count(*) FROM doubts") == 0


async def test_demand_not_found_returns_404(pool) -> None:
    """Demanda inexistente → 404."""
    status, payload = await generation.handle_generate_br(
        pool, "00000000-0000-0000-0000-000000000000", client=FakeClient(BR_PAYLOAD)
    )
    assert status == 404
    assert payload["error"]["code"] == "not_found"


async def test_path_conflict_returns_409(pool, demand) -> None:
    """Mesmo path no mesmo repo → 409 (índice único `artifacts_repo_path_uniq` do F4)."""
    await generation.handle_generate_br(pool, demand["id"], client=FakeClient(br_payload("login")))
    other = await pool.fetchval(
        "INSERT INTO demands (repo_id, module, title, body, status, created_by)"
        " VALUES ($1,'login','Outra demanda','corpo','claimed',$2) RETURNING id",
        demand["repo_id"],
        demand["user_id"],
    )
    status, payload = await generation.handle_generate_br(
        pool, str(other), client=FakeClient(br_payload("login"))
    )
    assert status == 409
    assert payload["error"]["code"] == "artifact_path_conflict"
    assert payload["error"]["detail"]["path"] == "docs/BR/login/login.md"
    rows = await pool.fetch("SELECT id FROM artifacts WHERE kind = 'br'")
    assert len(rows) == 1


# --------------------------------------------------------------------------- #
# Contexto degradado
# --------------------------------------------------------------------------- #


async def test_context_fallback_without_f7(pool, demand, monkeypatch) -> None:
    """Sem F7 o contexto degrada — e o artefato é gerado mesmo assim."""
    monkeypatch.setattr(generator, "_f7_search", lambda: None)
    _status, payload = await generation.handle_generate_br(
        pool, demand["id"], client=FakeClient(BR_PAYLOAD)
    )
    context = payload["context"]
    assert context["degraded"] is True
    assert context["repo_hits"] == 0
    assert context["repo_corpus_id"] is None
    assert "F7 pendente" in (context["degraded_reason"] or "")
    assert payload["artifact"]["id"] == "BR-001"


async def test_context_fallback_without_f3(pool, demand, monkeypatch) -> None:
    """Sem F3 o corpus é lido localmente e o motivo cita `F3 pendente`."""
    monkeypatch.setattr(generator, "_f3_method_index", lambda: None)
    monkeypatch.setattr(generator, "_f3_load_method_documents", lambda: None)
    _status, payload = await generation.handle_generate_br(
        pool, demand["id"], client=FakeClient(BR_PAYLOAD)
    )
    context = payload["context"]
    assert context["degraded"] is True
    assert "F3 pendente" in (context["degraded_reason"] or "")
    assert payload["artifact"]["id"] == "BR-001"


async def test_context_uses_f3_method_index(pool, demand) -> None:
    """Com o F3 no ar, o corpus vem do `MethodIndex` (sem degradação)."""
    _status, payload = await generation.handle_generate_br(
        pool, demand["id"], client=FakeClient(BR_PAYLOAD)
    )
    context = payload["context"]
    assert "SK-001" in context["method_docs"]
    assert context["degraded_reason"] is None or "F3 pendente" not in context["degraded_reason"]


async def test_generation_uses_adaptive_thinking_and_structured_output(pool, demand) -> None:
    """A chamada usa `thinking=adaptive`, `effort=high` e o schema do artefato."""
    client = FakeClient(BR_PAYLOAD)
    await generation.handle_generate_br(pool, demand["id"], client=client)
    call = client.calls[0]
    assert call["model"] == "claude-opus-5-5"
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"]["effort"] == "high"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["output_config"]["format"]["schema"] == generator.BR_SCHEMA
    assert call["max_tokens"] == 32000


# --------------------------------------------------------------------------- #
# Cliente e invariantes
# --------------------------------------------------------------------------- #


def test_base_url_strips_v1_suffix(monkeypatch) -> None:
    """`ANTHROPIC_BASE_URL=.../v1` não vira `/v1/v1/messages`."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-teste")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://127.0.0.1:20128/v1")
    client = generator.build_client()
    base = str(client.base_url).rstrip("/")
    assert base == "http://127.0.0.1:20128"
    assert f"{base}/v1/messages" == "http://127.0.0.1:20128/v1/messages"


async def test_server_never_writes_dev_repo(pool, demand) -> None:
    """Nenhum arquivo do repo é criado ou alterado pela geração."""
    root = generator.repo_root()

    def snapshot() -> dict[str, float]:
        return {
            str(path): path.stat().st_mtime
            for path in root.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts
        }

    before = snapshot()
    await generation.handle_generate_br(pool, demand["id"], client=FakeClient(BR_PAYLOAD))
    assert snapshot() == before


# --------------------------------------------------------------------------- #
# Rotas HTTP (app ASGI do F1)
# --------------------------------------------------------------------------- #


async def test_route_requires_scope(client, limited_token) -> None:
    """Token sem `demand:write` → 403."""
    response = await client.post(
        "/api/generation/demands/00000000-0000-0000-0000-000000000000/br",
        headers={"Authorization": f"Bearer {limited_token}"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


async def test_route_br_returns_artifact(client, pool, demand, auth_token, monkeypatch) -> None:
    """A rota HTTP devolve a BR gerada (com o modelo trocado pelo fake)."""
    monkeypatch.setattr(generator, "build_client", lambda: FakeClient(BR_PAYLOAD))
    response = await client.post(
        f"/api/generation/demands/{demand['id']}/br",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["artifact"]["id"] == "BR-001"
    assert body["artifact"]["path"] == "docs/BR/login/login.md"
    assert body["doubts_file"]["path"].endswith("duvidas-br/BR-001.md")
    assert body["usage"] == {"input_tokens": 120, "output_tokens": 340}
    rows = await pool.fetch("SELECT id, status FROM artifacts WHERE kind = 'br'")
    assert [dict(row) for row in rows] == [{"id": "BR-001", "status": "draft"}]


async def test_route_specs_returns_artifacts(client, pool, demand, auth_token, monkeypatch) -> None:
    """A rota de SPECs devolve o lote com o grafo e o `dependsOn` no frontmatter."""
    monkeypatch.setattr(generator, "build_client", lambda: FakeClient(BR_PAYLOAD))
    br_response = await client.post(
        f"/api/generation/demands/{demand['id']}/br",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert br_response.status_code == 200
    br_id = br_response.json()["artifact"]["id"]

    monkeypatch.setattr(generator, "build_client", lambda: FakeClient(spec_payload()))
    response = await client.post(
        f"/api/generation/artifacts/{br_id}/specs",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 200
    body = response.json()
    assert [artifact["id"] for artifact in body["artifacts"]] == ["SPEC-001", "SPEC-002"]
    assert body["artifacts"][1]["frontmatter"]["dependsOn"] == ["SPEC-001"]
    assert {"parent_id": "SPEC-001", "child_id": "BR-001", "type": "derives_from"} in body[
        "spec_edges"
    ]
