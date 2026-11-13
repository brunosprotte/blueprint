"""Testes de resolução de links — fase F2.

O universo de links é o corpus do método (repo blueprint) + os artefatos já
sincronizados do repo de dev (tabela `artifacts`). Aqui o segundo é um stub
in-memory com a mesma interface (`exists` / `resolve`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.lint import (  # noqa: E402
    ArtifactDoc,
    CompositeUniverse,
    MethodCorpus,
    lint_document,
    parse_document,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


class SyncedStub:
    """Artefatos sincronizados (stub da tabela `artifacts`)."""

    def __init__(self, by_path: dict[str, str], by_id: dict[str, str] | None = None):
        self._by_path = dict(by_path)
        self._by_id = dict(by_id or {})

    def exists(self, ref: str) -> bool:
        return self.resolve(ref) is not None

    def resolve(self, ref: str) -> str | None:
        candidate = (ref or "").strip().replace("\\", "/")
        if candidate in self._by_path:
            return self._by_path[candidate]
        return self._by_id.get(candidate.upper())


@pytest.fixture
def corpus() -> MethodCorpus:
    return MethodCorpus(REPO_ROOT)


@pytest.fixture
def universe(corpus: MethodCorpus) -> CompositeUniverse:
    return CompositeUniverse(
        corpus,
        MethodCorpus(FIXTURES / "doubts-repo"),
        SyncedStub(
            by_path={
                "docs/BR/login/autenticacao.md": "docs/BR/login/autenticacao.md",
                "docs/implementation-artifacts/duvidas-br/BR-002.md": (
                    "docs/implementation-artifacts/duvidas-br/BR-002.md"
                ),
            },
            by_id={"BR-777": "docs/BR/login/autenticacao.md"},
        ),
    )


def doc(path: str, frontmatter: dict, body: str) -> ArtifactDoc:
    frontmatter = {key: value for key, value in frontmatter.items() if value is not None}
    content = (
        "---\n"
        + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
        + "---\n\n"
        + body
        + "\n"
    )
    return parse_document(path, content)


BR_FRONTMATTER = {
    "id": "BR-001",
    "module": "login",
    "feature": "login",
    "type": "Business Rule",
    "title": "BR de teste",
    "description": "BR usada nos testes de link.",
    "status": "draft",
    "tags": ["login"],
    "timestamp": "2026-11-10T00:00:00Z",
    "doubtsIndex": "docs/implementation-artifacts/duvidas-br/BR-002.md",
    "version": "1.0.0",
    "generatedBy": "SK-001",
}

SPEC_FRONTMATTER = {
    "id": "SPEC-001",
    "module": "login",
    "feature": "login",
    "type": "Functional Specification",
    "title": "SPEC de teste",
    "description": "SPEC usada nos testes de link.",
    "createdBy": "SK-002",
    "createdFrom": "BR-001",
    "technologyPack": "TP-001",
    "status": "draft",
    "tags": ["login"],
    "timestamp": "2026-11-10T00:00:00Z",
    "doubtsIndex": "docs/implementation-artifacts/duvidas-spec/SPEC-001.md",
    "version": "1.0.0",
}


def links_of(findings, source: str) -> list[dict]:
    return [
        finding.detail
        for finding in findings
        if finding.rule == "LINK-001" and finding.detail.get("source") == source
    ]


# --------------------------------------------------------------------------- #
# Wiki-links
# --------------------------------------------------------------------------- #


def test_broken_wiki_link(universe):
    doc_ = doc(
        "docs/BR/login/autenticacao.md",
        BR_FRONTMATTER,
        "## Objetivo\n\nVer [[META-999]] para o modelo.\n",
    )
    findings = lint_document(doc_, universe)
    broken = links_of(findings, "wiki-link")
    assert broken and broken[0]["ref"] == "META-999"


def test_valid_wiki_link(universe):
    doc_ = doc(
        "docs/BR/login/autenticacao.md",
        BR_FRONTMATTER,
        "## Objetivo\n\nVer [[META-004]] para a convenção.\n",
    )
    findings = lint_document(doc_, universe)
    assert links_of(findings, "wiki-link") == []


# --------------------------------------------------------------------------- #
# createdFrom
# --------------------------------------------------------------------------- #


def test_created_from_missing(universe):
    doc_ = doc(
        "docs/SPEC/login/api-autenticacao.md",
        {**SPEC_FRONTMATTER, "createdFrom": "BR-999"},
        "## Objetivo\n\nSPEC sem BR de origem.\n",
    )
    findings = lint_document(doc_, universe)
    broken = links_of(findings, "createdFrom")
    assert broken and broken[0]["ref"] == "BR-999"
    assert any(finding.rule == "SPEC-003" for finding in findings)


def test_created_from_resolved_by_synced_artifact(universe):
    doc_ = doc(
        "docs/SPEC/login/api-autenticacao.md",
        {**SPEC_FRONTMATTER, "createdFrom": "BR-777"},
        "## Objetivo\n\nSPEC de BR sincronizada.\n",
    )
    findings = lint_document(doc_, universe)
    assert links_of(findings, "createdFrom") == []
    assert not any(finding.rule == "SPEC-003" for finding in findings)


# --------------------------------------------------------------------------- #
# doubtsIndex
# --------------------------------------------------------------------------- #


def test_doubts_index_missing(universe):
    doc_ = doc(
        "docs/BR/login/autenticacao.md",
        {**BR_FRONTMATTER, "doubtsIndex": "docs/implementation-artifacts/duvidas-br/BR-404.md"},
        "## Objetivo\n\nSem arquivo de dúvidas.\n",
    )
    findings = lint_document(doc_, universe)
    broken = links_of(findings, "doubtsIndex")
    assert broken and broken[0]["ref"].endswith("BR-404.md")
    assert any(finding.rule == "PATH-002" for finding in findings)


def test_doubts_index_resolved(universe):
    doc_ = doc(
        "docs/BR/login/autenticacao.md",
        BR_FRONTMATTER,
        "## Objetivo\n\nDúvidas sincronizadas.\n",
    )
    findings = lint_document(doc_, universe)
    assert links_of(findings, "doubtsIndex") == []
    assert not any(finding.rule == "PATH-002" for finding in findings)


# --------------------------------------------------------------------------- #
# Blueprint Documents necessários
# --------------------------------------------------------------------------- #


def test_blueprint_doc_missing(universe):
    doc_ = doc(
        "docs/SPEC/login/api-autenticacao.md",
        SPEC_FRONTMATTER,
        "## Blueprint Documents necessários\n\n- META-999 — Documento inexistente\n",
    )
    findings = lint_document(doc_, universe)
    broken = links_of(findings, "blueprint-documents")
    assert broken and broken[0]["ref"] == "META-999"


def test_blueprint_doc_resolved(universe):
    doc_ = doc(
        "docs/SPEC/login/api-autenticacao.md",
        SPEC_FRONTMATTER,
        "## Blueprint Documents necessários\n\n- META-004 — Workspace Convention\n",
    )
    findings = lint_document(doc_, universe)
    assert links_of(findings, "blueprint-documents") == []


# --------------------------------------------------------------------------- #
# Universo composto
# --------------------------------------------------------------------------- #


def test_composite_universe(corpus: MethodCorpus):
    synced = SyncedStub(by_path={"docs/BR/x.md": "docs/BR/x.md"}, by_id={"BR-777": "docs/BR/x.md"})
    universe = CompositeUniverse(corpus, synced)

    # primeira fonte que resolve vence
    assert universe.resolve("META-004") == (
        "docs/META/META-004_WORKSPACE_CONVENTION.md"
    )
    assert universe.resolve("BR-777") == "docs/BR/x.md"
    assert universe.resolve("docs/BR/x.md") == "docs/BR/x.md"
    assert universe.resolve("META-999") is None
    assert not universe.exists("META-999")


# --------------------------------------------------------------------------- #
# Corpus do método
# --------------------------------------------------------------------------- #


def test_method_corpus_indexes_titles(corpus: MethodCorpus):
    assert corpus.resolve("META-004") == "docs/META/META-004_WORKSPACE_CONVENTION.md"
    assert corpus.resolve("META-000 — Blueprint Knowledge Model") == (
        "docs/META/META-000_BLUEPRINT_KNOWLEDGE_MODEL.md"
    )
    assert corpus.resolve("Blueprint Knowledge Model") == (
        "docs/META/META-000_BLUEPRINT_KNOWLEDGE_MODEL.md"
    )
    assert corpus.resolve("Workspace Convention") == (
        "docs/META/META-004_WORKSPACE_CONVENTION.md"
    )
    assert corpus.resolve("TP-001") == "docs/TP/TP-001_NEXTJS_FULL_STACK.md"
    assert corpus.exists("META-000_BLUEPRINT_KNOWLEDGE_MODEL.md")
    assert not corpus.exists("META-999")


def test_method_corpus_refresh_reindexes(tmp_path):
    """O corpus é reindexável — o servidor reindexa quando o método muda."""
    root = tmp_path / "repo"
    (root / "docs" / "META").mkdir(parents=True)
    (root / "docs" / "META" / "META-900_TESTE.md").write_text(
        "---\ntitle: META-900 — Teste\n---\n\n# META-900\n", encoding="utf-8"
    )

    corpus = MethodCorpus(root)
    assert corpus.resolve("META-900") == "docs/META/META-900_TESTE.md"

    (root / "docs" / "META" / "META-900_TESTE.md").unlink()
    assert corpus.refresh() == 0
    assert corpus.resolve("META-900") is None
