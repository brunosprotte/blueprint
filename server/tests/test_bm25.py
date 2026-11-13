"""Testes da fase F7 — chunking, BM25 de duas etapas e busca.

Rodam contra o core real: banco e app ASGI (F1), linter (F2) e corpus do método
(F3, `app.services.method.MethodIndex`). Nada de dummies.
"""
from __future__ import annotations

import importlib.util
import json
import math
import uuid
from pathlib import Path

import pytest

from app.lint.runner import parse_document
from app.services.indexer import (
    chunk_markdown,
    index_artifact,
    index_method,
    source_kind_for,
    tokenize,
)
from app.services.method import MethodIndex
from app.services.retriever import Candidate, bm25_rank, search

GOLD_SET = Path(__file__).parent / "gold_set.json"


def _retrieve_tool():
    """`tools/retrieve.py` (inalterado) — referência de tokenize e chunking."""
    path = Path(__file__).resolve().parents[2] / "tools" / "retrieve.py"
    spec = importlib.util.spec_from_file_location("retrieve_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _insert_chunk(pool, corpus_id, heading, text, source_ref, source_kind="spec"):
    await pool.execute(
        "INSERT INTO chunks (id, source_kind, heading, text, token_count, corpus_id, source_ref) "
        "VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6)",
        source_kind,
        heading,
        text,
        len(tokenize(heading + "\n" + text)),
        corpus_id,
        source_ref,
    )


# --- chunking (puro) -------------------------------------------------------


def test_chunk_markdown_sections():
    md = "# Title\n\nintro\n\n## Section A\n\nbody a\n\n### Sub B\n\nbody b\n"
    chunks = chunk_markdown(md, [])
    assert [c.heading for c in chunks] == ["Title", "Section A", "Sub B"]
    assert chunks[1].text == "body a"

    with_path = chunk_markdown(md, ["BR-013 — Login"])
    assert with_path[0].heading == "BR-013 — Login > Title"
    assert with_path[1].heading == "BR-013 — Login > Section A"

    long_body = chunk_markdown("# H\n\n" + ("x" * 1000) + "\n", [])
    assert len(long_body[0].text) == 800


def test_chunk_markdown_strips_frontmatter():
    md = "---\nid: BR-013\ntitle: Login\n---\n\n## Section\n\nbody\n"
    chunks = chunk_markdown(md, [])
    assert len(chunks) == 1
    assert chunks[0].text == "body"
    assert "BR-013" not in chunks[0].text


def test_chunk_markdown_skips_empty_body():
    chunks = chunk_markdown("## Empty\n\n## Full\n\nbody\n", [])
    assert [c.heading for c in chunks] == ["Full"]


def test_chunk_markdown_fallback():
    chunks = chunk_markdown("texto sem heading", [])
    assert len(chunks) == 1
    assert chunks[0].text == "texto sem heading"
    assert chunks[0].heading == "documento"


def test_tokenize_matches_retrieve_tool():
    assert tokenize("Hello, World!") == ["hello", "world"]
    assert tokenize("a b cd") == ["cd"]
    assert tokenize("ab cde") == ["ab", "cde"]
    assert tokenize("Ação_ção 123") == ["ação_ção", "123"]

    tool = _retrieve_tool()
    for sample in ["Hello, World!", "a b cd", "AC-001 Output Port", "ção e-mail"]:
        assert tokenize(sample) == tool.tokenize(sample)


def test_source_kind_for():
    assert source_kind_for("docs/BR/login/login.md") == "br"
    assert source_kind_for("docs/SPEC/login/login-api.md") == "spec"
    assert source_kind_for("docs/implementation-artifacts/duvidas-spec/SPEC-001.md") == "doubt"
    assert source_kind_for("src/app.ts", "br") == "br"
    assert source_kind_for("src/app.ts") is None


# --- BM25 (puro) -----------------------------------------------------------


def test_bm25_formula():
    candidates = [
        Candidate(chunk_id="D1", tokens=("a", "b", "b"), length=3),
        Candidate(chunk_id="D2", tokens=("b", "c"), length=2),
    ]
    scores = dict(bm25_rank(candidates, ["b"]))
    assert math.isclose(scores["D1"], math.log(1.2) * 200 / 149, rel_tol=1e-12)
    assert math.isclose(scores["D2"], math.log(1.2) * 100 / 91, rel_tol=1e-12)


def test_bm25_ranking():
    candidates = [
        Candidate(chunk_id="a", tokens=("alpha", "beta"), length=2),
        Candidate(chunk_id="b", tokens=("gamma", "delta"), length=2),
    ]
    ranked = bm25_rank(candidates, ["gamma"])
    assert ranked[0][0] == "b"
    assert ranked[0][1] > 0


def test_bm25_drops_zero_score():
    candidates = [
        Candidate(chunk_id="a", tokens=("alpha",), length=1),
        Candidate(chunk_id="b", tokens=("beta",), length=1),
    ]
    assert bm25_rank(candidates, ["gamma"]) == []


# --- busca (core real) -----------------------------------------------------


async def test_search_two_stage(pool):
    corpus = "repo:test-two-stage"
    await _insert_chunk(pool, corpus, "Alpha", "alpha alpha beta", "ref-alpha")
    await _insert_chunk(pool, corpus, "Beta", "beta gamma", "ref-beta")

    hits = await search("alpha", corpus, top=5)
    assert [hit.heading for hit in hits] == ["Alpha"]
    assert hits[0].score > 0
    assert hits[0].corpus_id == corpus

    rank_cd = await pool.fetchval(
        "SELECT ts_rank_cd(tsv, plainto_tsquery('portuguese', 'alpha')) FROM chunks "
        "WHERE corpus_id = $1 AND heading = 'Alpha'",
        corpus,
    )
    assert hits[0].score != rank_cd


async def test_search_never_crosses_corpora(pool):
    await _insert_chunk(pool, "repo:repo-a", "A chunk", "shared term alpha", "ref-a")
    await _insert_chunk(pool, "repo:repo-b", "B chunk", "shared term alpha", "ref-b")

    hits = await search("alpha", "repo:repo-a", top=5)
    assert hits
    assert {hit.corpus_id for hit in hits} == {"repo:repo-a"}
    assert "B chunk" not in [hit.heading for hit in hits]


async def test_search_caps_top(pool, client, auth_token):
    corpus = "repo:test-caps-top"
    for i in range(5):
        await _insert_chunk(pool, corpus, f"Chunk {i}", "alpha beta gamma", f"ref-{i}")

    hits = await search("alpha", corpus, top=2)
    assert len(hits) == 2

    response = await client.get(
        "/api/knowledge",
        params={"q": "alpha", "top": 201},
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    assert response.status_code == 422


async def test_search_empty_result(pool):
    await _insert_chunk(pool, "repo:test-empty", "Alpha", "alpha beta", "ref-alpha")
    hits = await search("palavrainexistente", "repo:test-empty", top=5)
    assert hits == []


async def test_index_artifact_idempotent(pool):
    repo_id = uuid.uuid4()
    await pool.execute(
        "INSERT INTO repos (id, owner, name) VALUES ($1, $2, $3)", repo_id, "acme", "app"
    )
    content = "---\nid: SPEC-002\ntitle: Login API\n---\n\n## Section\n\nbody\n"
    await pool.execute(
        "INSERT INTO artifacts (id, repo_id, kind, path, content) VALUES ($1, $2, $3, $4, $5)",
        "SPEC-002",
        repo_id,
        "spec",
        "docs/SPEC/login/login-api.md",
        content,
    )

    doc = parse_document("docs/SPEC/login/login-api.md", content, repo_id=str(repo_id))
    assert doc.kind == "spec"

    corpus = f"repo:{repo_id}"
    first = await index_artifact(doc, corpus)
    second = await index_artifact(doc, corpus)

    assert first == second > 0
    count = await pool.fetchval("SELECT count(*) FROM chunks WHERE corpus_id = $1", corpus)
    assert count == first


async def test_index_method_idempotent(pool):
    first = await index_method()
    assert first > 0

    count_before = await pool.fetchval(
        "SELECT count(*) FROM chunks WHERE corpus_id = 'method'"
    )
    second = await index_method()
    count_after = await pool.fetchval(
        "SELECT count(*) FROM chunks WHERE corpus_id = 'method'"
    )

    assert second == 0
    assert count_after == count_before

    payload = await pool.fetchrow(
        "SELECT payload->>'content_hash' AS content_hash, "
        "       payload->>'chunk_count' AS chunk_count FROM events "
        "WHERE type = 'method_corpus_indexed' ORDER BY id DESC LIMIT 1"
    )
    assert payload["content_hash"]
    assert int(payload["chunk_count"]) == count_after


async def test_index_method_uses_f3_method_index(pool):
    """D1 — o corpus indexado é o do F3, não uma varredura própria do F7."""
    from app.config import settings

    index = MethodIndex(Path(settings.repo_root))
    expected = {
        doc.path[len("docs/") :] if doc.path.startswith("docs/") else doc.path
        for doc in index.all()
    }
    assert expected

    await index_method()
    rows = await pool.fetch(
        "SELECT DISTINCT source_ref FROM chunks WHERE corpus_id = 'method' AND source_ref <> ''"
    )
    assert {row["source_ref"] for row in rows} == expected


async def test_index_method_excludes_implementation_artifacts(pool):
    """O catálogo de dúvidas não é conhecimento do método (META-006 §9).

    A lista de diretórios excluídos é a do F3 (`MethodIndex.EXCLUDED_DIRS`) — o
    F7 não mantém uma lista própria.
    """
    await index_method()
    total = await pool.fetchval(
        "SELECT count(*) FROM chunks WHERE corpus_id = 'method' AND source_ref <> ''"
    )
    assert total > 0
    rows = await pool.fetch(
        "SELECT DISTINCT source_ref FROM chunks "
        "WHERE corpus_id = 'method' AND source_ref LIKE '%implementation-artifacts%'"
    )
    assert rows == []


async def test_tsv_trigger_maintains_tsv(pool):
    corpus = "repo:test-tsv"
    await _insert_chunk(pool, corpus, "Alpha", "alpha beta", "ref-alpha")

    tsv = await pool.fetchval("SELECT tsv FROM chunks WHERE corpus_id = $1", corpus)
    assert tsv is not None

    await pool.execute(
        "UPDATE chunks SET text = 'gamma delta' WHERE corpus_id = $1", corpus
    )
    updated = await pool.fetchval("SELECT tsv::text FROM chunks WHERE corpus_id = $1", corpus)
    expected = await pool.fetchval(
        "SELECT to_tsvector('portuguese', coalesce($1, '') || ' ' || coalesce($2, ''))::text",
        "Alpha",
        "gamma delta",
    )
    assert updated == expected
    assert "beta" not in updated


async def test_tsv_uses_f3_expression(pool):
    """Contrato Comum §4.1 — o trigger do F7 usa a mesma expressão do INSERT do F3."""
    corpus = "repo:test-tsv-expression"
    heading = "Titulo da secao"
    text = "corpo do texto com acento"
    await _insert_chunk(pool, corpus, heading, text, "ref-expression")

    actual = await pool.fetchval("SELECT tsv FROM chunks WHERE corpus_id = $1", corpus)
    expected = await pool.fetchval(
        "SELECT to_tsvector('portuguese', coalesce($1, '') || ' ' || coalesce($2, ''))",
        heading,
        text,
    )
    assert actual == expected


async def test_commits_status_is_owned_by_f4(pool):
    """Contrato Comum §4.3 — `commits.status` é do F4; o F7 só consome."""
    default = await pool.fetchval(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_name = 'commits' AND column_name = 'status'"
    )
    assert default is not None and "present" in default

    constraint = await pool.fetchval(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'commits_status_check'"
    )
    assert constraint is not None
    assert "present" in constraint and "orphaned" in constraint
    assert "reported" not in constraint


async def test_source_ref_unique(pool):
    """Chunk idêntico (mesma origem, mesmo heading, mesmo corpo) viola a unicidade.

    A chave inclui heading e corpo porque uma origem gera um chunk por seção H2/H3
    (e seções homônimas existem no método) — ver migration 005.
    """
    corpus = "repo:test-unique"
    await _insert_chunk(pool, corpus, "Alpha", "alpha beta", "ref-same")
    with pytest.raises(Exception):
        await _insert_chunk(pool, corpus, "Alpha", "alpha beta", "ref-same")


async def test_response_shape_same_as_method_search(client, auth_token):
    headers = {"Authorization": f"Bearer {auth_token}"}
    knowledge = await client.get("/api/knowledge", params={"q": "knowledge"}, headers=headers)
    assert knowledge.status_code == 200

    body = knowledge.json()
    assert set(body) == {"query", "hits"}
    for hit in body["hits"]:
        assert set(hit) == {
            "heading",
            "text",
            "score",
            "source_kind",
            "artifact_id",
            "demand_id",
            "corpus_id",
        }

    method = await client.get("/api/method/search", params={"q": "knowledge"}, headers=headers)
    assert method.status_code == 200
    assert set(method.json()) == set(body)
    if method.json()["hits"]:
        assert set(method.json()["hits"][0]) == set(body["hits"][0])


async def test_gold_recall(pool):
    cases = json.loads(GOLD_SET.read_text(encoding="utf-8"))["cases"]
    assert len(cases) == 20

    await index_method()
    rows = await pool.fetch(
        "SELECT id, source_ref, heading FROM chunks WHERE corpus_id = 'method'"
    )
    by_id = {str(row["id"]): (row["source_ref"], row["heading"]) for row in rows}

    acertos = 0
    for case in cases:
        hits = await search(case["q"], case["corpus_id"], top=5)
        if any(
            by_id.get(hit.chunk_id) == (case["expect_ref"], case["expect_heading"])
            for hit in hits
        ):
            acertos += 1

    assert acertos / len(cases) >= 0.80, f"recall@5 = {acertos}/{len(cases)}"
