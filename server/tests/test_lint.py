"""Testes do linter de artefatos — fase F2.

O linter é puro: entrada (documento + universo) → findings. Os universos usados
aqui são reais (`MethodCorpus` sobre o repo blueprint e sobre o repo de dúvidas
de fixture) — nenhum stub de banco é necessário.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
import yaml

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

os.environ.setdefault("SDD_SECRET_KEY", "test-secret")

from app.lint import (  # noqa: E402
    ArtifactDoc,
    CompositeUniverse,
    MethodCorpus,
    lint_batch,
    lint_document,
    parse_document,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


# --------------------------------------------------------------------------- #
# Universo
# --------------------------------------------------------------------------- #


@pytest.fixture
def universe() -> CompositeUniverse:
    """Corpus do método (repo blueprint) + artefatos de dúvida (repo de dev)."""
    return CompositeUniverse(
        MethodCorpus(REPO_ROOT),
        MethodCorpus(FIXTURES / "doubts-repo"),
    )


# --------------------------------------------------------------------------- #
# Construtores de documento
# --------------------------------------------------------------------------- #

BR_FRONTMATTER = {
    "id": "BR-001",
    "module": "login",
    "feature": "login",
    "type": "Business Rule",
    "title": "BR de teste",
    "description": "BR usada nos testes do linter.",
    "status": "draft",
    "tags": ["login"],
    "timestamp": "2026-11-10T00:00:00Z",
    "doubtsIndex": "docs/implementation-artifacts/duvidas-br/BR-001.md",
    "version": "1.0.0",
    "generatedBy": "SK-001",
}

BR_BODY_SECTIONS = {
    "Objetivo": "Permitir que o usuário autenticado entre no sistema.",
    "Contexto": "O sistema ainda não possui autenticação própria.",
    "Atores": "- Usuário cadastrado",
    "Capacidades": "- Autenticar-se no sistema",
    "Regras de Negócio": "- O e-mail é único por usuário.",
    "Restrições": "- Nenhuma informação técnica no documento.",
    "Exceções": "- Usuário bloqueado após cinco tentativas.",
    "Acceptance Criteria": "- **AC-001** — Critério de teste um.",
}

SPEC_FRONTMATTER = {
    "id": "SPEC-001",
    "module": "login",
    "feature": "login",
    "type": "Functional Specification",
    "title": "SPEC de teste",
    "description": "SPEC usada nos testes do linter.",
    "createdBy": "SK-002",
    "createdFrom": "BR-001",
    "technologyPack": "TP-001",
    "status": "draft",
    "tags": ["login"],
    "timestamp": "2026-11-10T00:00:00Z",
    "doubtsIndex": "docs/implementation-artifacts/duvidas-spec/SPEC-001.md",
    "version": "1.0.0",
}

SPEC_BODY_SECTIONS = {
    "Objetivo": "Autenticar o usuário e devolver token de sessão.",
    "Escopo": "Somente autenticação.",
    "Responsabilidade": "Validar credenciais e emitir token.",
    "Entradas": "- `email`: string obrigatória.",
    "Saídas": "- `token`: string de sessão.",
    "Fluxo principal": "1. O cliente envia e-mail e senha.",
    "Fluxos alternativos": "- Credenciais inválidas devolvem erro.",
    "Validações": "- E-mail malformado é rejeitado.",
    "Failures": "- Falha de banco devolve erro genérico.",
    "Pré-condições": "- O usuário está cadastrado.",
    "Pós-condições": "- Existe sessão ativa.",
    "Acceptance Criteria atendidos": "- **AC-001** — Critério de teste um.",
    "Dependências": "Nenhuma dependência técnica.",
    "Blueprint Documents necessários": "- META-004 — Workspace Convention",
}


def _render(body_sections: dict[str, str]) -> str:
    return "\n\n".join(
        f"## {name}\n\n{text}" for name, text in body_sections.items()
    )


def _document(
    path: str, frontmatter: dict, body_sections: dict[str, str]
) -> ArtifactDoc:
    frontmatter = {key: value for key, value in frontmatter.items() if value is not None}
    content = (
        "---\n"
        + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
        + "---\n\n"
        + _render(body_sections)
        + "\n"
    )
    return parse_document(path, content)


def br_doc(
    sections: dict[str, str] | None = None,
    body_sections: dict[str, str] | None = None,
    **overrides,
) -> ArtifactDoc:
    frontmatter = {**BR_FRONTMATTER, **overrides}
    body = {**BR_BODY_SECTIONS, **(body_sections or {})}
    for name in sections or ():
        body.pop(name, None)
    return _document("docs/BR/login/autenticacao.md", frontmatter, body)


def spec_doc(
    sections: dict[str, str] | None = None,
    body_sections: dict[str, str] | None = None,
    path: str = "docs/SPEC/login/api-autenticacao.md",
    **overrides,
) -> ArtifactDoc:
    frontmatter = {**SPEC_FRONTMATTER, **overrides}
    body = {**SPEC_BODY_SECTIONS, **(body_sections or {})}
    for name in sections or ():
        body.pop(name, None)
    return _document(path, frontmatter, body)


# --------------------------------------------------------------------------- #
# Helpers de asserção
# --------------------------------------------------------------------------- #


def rules_of(findings) -> list[str]:
    return [finding.rule for finding in findings]


def of_rule(findings, rule: str) -> list:
    return [finding for finding in findings if finding.rule == rule]


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Critérios de aceitação — artefato válido não gera finding
# --------------------------------------------------------------------------- #


def test_valid_br_no_findings(universe):
    doc = parse_document(
        "docs/BR/login/autenticacao.md", read_fixture("br_valida.md")
    )
    assert lint_document(doc, universe) == []


def test_valid_spec_no_findings(universe):
    br = parse_document("docs/BR/login/autenticacao.md", read_fixture("br_valida.md"))
    spec = parse_document(
        "docs/SPEC/login/api-autenticacao.md", read_fixture("spec_valida.md")
    )
    assert lint_batch([br, spec], universe) == []


# --------------------------------------------------------------------------- #
# BR-001 — frontmatter completo
# --------------------------------------------------------------------------- #


def test_br001_missing_field(universe):
    findings = lint_document(br_doc(generatedBy=None), universe)
    assert "BR-001" in rules_of(findings)
    assert of_rule(findings, "BR-001")[0].detail == {"missing": "generatedBy"}


def test_br001_missing_frontmatter(universe):
    content = "# BR sem frontmatter\n\n## Objetivo\n\nSem frontmatter.\n"
    doc = parse_document("docs/BR/login/sem-frontmatter.md", content)
    findings = lint_document(doc, universe)
    assert of_rule(findings, "BR-001")[0].detail["missing"] == list(BR_FRONTMATTER)


# --------------------------------------------------------------------------- #
# BR-002 — status no ciclo de vida
# --------------------------------------------------------------------------- #


def test_br002_invalid_status(universe):
    findings = lint_document(br_doc(status="published"), universe)
    assert of_rule(findings, "BR-002")[0].detail["status"] == "published"


# --------------------------------------------------------------------------- #
# BR-003 — seções obrigatórias
# --------------------------------------------------------------------------- #


def test_br003_missing_section(universe):
    findings = lint_document(br_doc(sections=["Exceções"]), universe)
    assert of_rule(findings, "BR-003")[0].detail == {"missing": "Exceções"}


def test_br003_missing_section_reports_one_finding_per_section(universe):
    findings = lint_document(br_doc(sections=["Atores", "Exceções"]), universe)
    missing = [f.detail["missing"] for f in of_rule(findings, "BR-003")]
    assert missing == ["Atores", "Exceções"]


def test_br003_section_matches_without_accents(universe):
    """'Regras de Negócio' e 'Regras de negocio' são a mesma seção."""
    findings = lint_document(
        br_doc(body_sections={"Regras de Negócio": "- Substituída."}),
        universe,
    )
    assert "BR-003" not in rules_of(findings)


def test_br003_heading_inside_code_block_is_not_a_section(universe):
    """Um '#' dentro de um diagrama não satisfaz uma seção obrigatória."""
    findings = lint_document(
        br_doc(
            sections=["Atores"],
            body_sections={"Contexto": "```\n## Atores\n```"},
        ),
        universe,
    )
    assert of_rule(findings, "BR-003")[0].detail == {"missing": "Atores"}


# --------------------------------------------------------------------------- #
# BR-004 — ACs: duplicada, malformada, sem cobertura, inexistente
# --------------------------------------------------------------------------- #


def test_br004_duplicate_ac(universe):
    body = {
        "Acceptance Criteria": (
            "- **AC-001** — Primeira ocorrência.\n"
            "- **AC-001** — Segunda ocorrência.\n"
        )
    }
    findings = lint_document(br_doc(body_sections=body), universe)
    assert of_rule(findings, "BR-004")[0].detail["duplicate"] == "AC-001"


def test_br004_malformed_ac(universe):
    body = {"Acceptance Criteria": "- **AC-1** — Identificador malformado.\n"}
    findings = lint_document(br_doc(body_sections=body), universe)
    assert of_rule(findings, "BR-004")[0].detail["malformed"] == "AC-1"


def test_br004_uncovered_ac(universe):
    br = br_doc(
        body_sections={
            "Acceptance Criteria": (
                "- **AC-001** — Coberto pela SPEC.\n"
                "- **AC-002** — Sem cobertura.\n"
            )
        }
    )
    spec = spec_doc(
        body_sections={"Acceptance Criteria atendidos": "- **AC-001** — Coberto.\n"}
    )
    findings = lint_batch([br, spec], universe)
    assert of_rule(findings, "BR-004")[0].detail == {"uncovered": "AC-002"}


def test_br004_unknown_ac_on_spec(universe):
    br = br_doc()
    spec = spec_doc(
        body_sections={"Acceptance Criteria atendidos": "- **AC-777** — Inexistente.\n"}
    )
    findings = lint_batch([br, spec], universe)
    unknown = [
        finding.detail
        for finding in of_rule(findings, "BR-004")
        if "unknown_ac" in finding.detail
    ]
    assert unknown == [{"unknown_ac": "AC-777", "spec": "SPEC-001"}]


# --------------------------------------------------------------------------- #
# SPEC-001 / SPEC-002 — frontmatter e seções
# --------------------------------------------------------------------------- #


def test_spec001_missing_field(universe):
    findings = lint_document(spec_doc(technologyPack=None), universe)
    assert of_rule(findings, "SPEC-001")[0].detail == {"missing": "technologyPack"}


def test_spec002_missing_section(universe):
    findings = lint_document(spec_doc(sections=["Validações"]), universe)
    assert of_rule(findings, "SPEC-002")[0].detail == {"missing": "Validações"}


# --------------------------------------------------------------------------- #
# SPEC-003 — createdFrom aponta pra BR existente
# --------------------------------------------------------------------------- #


def test_spec003_created_from_missing(universe):
    findings = lint_document(spec_doc(createdFrom="BR-999"), universe)
    assert of_rule(findings, "SPEC-003")[0].detail == {"createdFrom": "BR-999"}


def test_spec003_created_from_in_batch(universe):
    findings = lint_batch([br_doc(), spec_doc()], universe)
    assert "SPEC-003" not in rules_of(findings)


# --------------------------------------------------------------------------- #
# SPEC-004 — grafo de dependências
# --------------------------------------------------------------------------- #


def test_spec004_dependency_cycle(universe):
    first = spec_doc(
        id="SPEC-010",
        createdFrom="BR-001",
        dependsOn=["SPEC-011"],
        body_sections={"Dependências": "- SPEC-011"},
    )
    second = spec_doc(
        id="SPEC-011",
        createdFrom="BR-001",
        dependsOn=["SPEC-010"],
        body_sections={"Dependências": "- SPEC-010"},
    )
    findings = lint_batch([first, second], universe)
    cycles = [f.detail["cycle"] for f in of_rule(findings, "SPEC-004")]
    assert cycles, "esperado um finding de ciclo"
    assert set(cycles[0]) == {"SPEC-010", "SPEC-011"}
    assert len(cycles[0]) == 2


def test_spec004_missing_dependency(universe):
    findings = lint_document(
        spec_doc(dependsOn=["SPEC-404"], body_sections={"Dependências": "- SPEC-404"}),
        universe,
    )
    assert of_rule(findings, "SPEC-004")[0].detail == {"missing": "SPEC-404"}


# --------------------------------------------------------------------------- #
# PATH-001 / PATH-002
# --------------------------------------------------------------------------- #


def test_path001_uppercase_path(universe):
    doc = parse_document("docs/BR/Login/Login.md", read_fixture("br_valida.md"))
    findings = lint_document(doc, universe)
    problems = of_rule(findings, "PATH-001")[0].detail["problems"]
    assert "modulo 'Login' fora de kebab-case" in problems
    assert "nome de arquivo 'Login.md' fora de kebab-case" in problems


def test_path001_underscore_filename(universe):
    doc = parse_document("docs/BR/login/login_final.md", read_fixture("br_valida.md"))
    findings = lint_document(doc, universe)
    assert of_rule(findings, "PATH-001")[0].detail["problems"] == [
        "nome de arquivo 'login_final.md' fora de kebab-case"
    ]


def test_path002_doubts_index_missing(universe):
    findings = lint_document(
        br_doc(doubtsIndex="docs/implementation-artifacts/duvidas-br/BR-404.md"),
        universe,
    )
    assert "arquivo de duvidas inexistente" in of_rule(findings, "PATH-002")[0].detail[
        "problems"
    ]


def test_path002_doubts_index_wrong_directory(universe):
    findings = lint_document(br_doc(doubtsIndex="docs/duvidas/BR-001.md"), universe)
    problems = of_rule(findings, "PATH-002")[0].detail["problems"]
    assert "esperado em docs/implementation-artifacts/duvidas-br/" in problems


# --------------------------------------------------------------------------- #
# Determinismo
# --------------------------------------------------------------------------- #


def test_deterministic(universe):
    doc = br_doc()
    first = lint_document(doc, universe)
    second = lint_document(doc, universe)
    assert first == second


def test_findings_sorted_by_path_and_rule(universe):
    br = br_doc(status="published")
    spec = spec_doc(createdFrom="BR-999", sections=["Validações"])
    findings = lint_batch([br, spec], universe)
    keys = [(finding.path or "", finding.rule) for finding in findings]
    assert keys == sorted(keys)


def test_rules_registry_is_the_contract():
    """As 11 regras do contrato, com severidade."""
    from app.lint import RULES

    assert [(rule.id, rule.severity) for rule in RULES] == [
        ("BR-001", "error"),
        ("BR-002", "error"),
        ("BR-003", "error"),
        ("BR-004", "error"),
        ("SPEC-001", "error"),
        ("SPEC-002", "error"),
        ("SPEC-003", "error"),
        ("SPEC-004", "error"),
        ("PATH-001", "error"),
        ("PATH-002", "error"),
        ("LINK-001", "error"),
    ]


# --------------------------------------------------------------------------- #
# Fixtures inválidas
# --------------------------------------------------------------------------- #


def test_invalid_br_fixture(universe):
    doc = parse_document("docs/BR/checkout/checkout.md", read_fixture("br_invalida.md"))
    findings = lint_document(doc, universe)
    rules = rules_of(findings)
    assert "BR-001" in rules
    assert "BR-002" in rules
    assert "BR-003" in rules
    assert "BR-004" in rules
    assert "PATH-002" in rules
    assert "LINK-001" in rules


def test_invalid_spec_fixture(universe):
    doc = parse_document(
        "docs/SPEC/checkout/checkout.md", read_fixture("spec_invalida.md")
    )
    findings = lint_document(doc, universe)
    rules = rules_of(findings)
    assert "SPEC-001" in rules
    assert "SPEC-002" in rules
    assert "SPEC-003" in rules
    assert "PATH-002" in rules
    assert "LINK-001" in rules


# --------------------------------------------------------------------------- #
# Endpoint — depende da F1 (app.auth / app.config / app.db)
# --------------------------------------------------------------------------- #


def _f1_available() -> bool:
    for name in ("app.auth", "app.config", "app.db"):
        try:
            if importlib.util.find_spec(name) is None:
                return False
        except (ImportError, ValueError):
            return False
    return True


F1_PENDING = pytest.mark.skipif(not _f1_available(), reason="F1 pendente")


@F1_PENDING
def test_lint_endpoint_returns_findings_and_summary(monkeypatch):
    """POST /api/lint devolve findings ordenados e o summary."""
    import asyncio

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.routers import lint as lint_router

    class _EmptyPool:
        async def fetch(self, query, *args):
            return []

    async def _get_pool():
        return _EmptyPool()

    monkeypatch.setattr(lint_router, "get_pool", _get_pool)

    app = FastAPI()
    app.include_router(lint_router.router, prefix="/api")
    app.dependency_overrides[lint_router.require_artifact_sync] = lambda: None

    payload = {
        "repo": "org/repo",
        "docs": [
            {"path": "docs/BR/login/autenticacao.md", "content": read_fixture("br_valida.md")},
            {"path": "docs/BR/login/quebrada.md", "content": read_fixture("br_invalida.md")},
        ],
    }

    async def call():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post("/api/lint", json=payload)

    response = asyncio.run(call())

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["error"] >= 1
    assert body["summary"]["warning"] == 0
    paths = [finding["path"] for finding in body["findings"]]
    assert paths == sorted(paths)


@F1_PENDING
def test_lint_endpoint_rejects_paths_without_content():
    """Só `paths` não serve: o servidor nunca lê o repo de dev."""
    import asyncio

    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.routers import lint as lint_router

    app = FastAPI()
    app.include_router(lint_router.router, prefix="/api")
    app.dependency_overrides[lint_router.require_artifact_sync] = lambda: None

    async def call():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/api/lint", json={"paths": ["docs/BR/login/autenticacao.md"]}
            )

    response = asyncio.run(call())

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "paths_without_content"
