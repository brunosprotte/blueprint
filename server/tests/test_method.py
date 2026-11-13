"""Testes da fase F3 — método servido (`/api/method/*`) e skills (`/api/skills/*`).

Os testes rodam contra a **fixture** `server/tests/fixtures/method/` — o `docs/` real
do repo blueprint nunca é tocado.

O banco é o do F1 (`server/tests/conftest.py`): a fixture `pool` aplica as
migrations (inclusive a `001`, que cria `chunks.tsv` como coluna simples) e trunca
as tabelas a cada teste. As fixtures `client` e `auth_token` também vêm do F1.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

import pytest
import pytest_asyncio

from app import main as app_main
from app.config import settings
from app.routers import method as method_router
from app.services.method import (
    get_method_index,
    load_method_document,
    load_method_documents,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "method"

#: Módulo real de `app.db`. O `app.main` foi importado pelo conftest do F1 antes de
#: qualquer dublê de outra fase, então esta referência é o módulo de verdade.
REAL_DB = app_main.db

HIT_KEYS = {"heading", "text", "score", "source_kind", "artifact_id", "demand_id", "corpus_id"}
SKILL_KEYS = {"id", "version", "hash", "description", "path"}


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def repo_root(monkeypatch) -> Path:
    """Aponta `settings.repo_root` para a fixture e limpa o cache dos serviços."""
    monkeypatch.setattr(settings, "repo_root", FIXTURE_ROOT)
    method_router.reset_services()
    return FIXTURE_ROOT


@pytest_asyncio.fixture
async def method_corpus(repo_root, pool, monkeypatch):
    """Popula o corpus `method` — a escrita é do F7 (`indexer.index_method`).

    O F3 não escreve em `chunks` (Contrato Comum §7.6): quem indexa é o F7.

    O `index_method` do F7 importa `app.db.get_pool` em tempo de execução. O
    `test_claim.py` (F4) troca `app.db` por um dublê no **import do módulo** e
    deixa um pool fechado lá — durante este teste volta o módulo real. É um
    bug de outra fase; o `monkeypatch` desfaz a troca no fim do teste.
    """
    from app.services.indexer import index_method

    monkeypatch.setitem(sys.modules, "app.db", REAL_DB)
    await index_method()
    return pool


@pytest.fixture
def auth_headers(auth_token) -> dict[str, str]:
    """Cabeçalho de autenticação com um token real gravado no banco."""
    return {"Authorization": f"Bearer {auth_token}"}


# --------------------------------------------------------------------------- #
# GET /api/method/index
# --------------------------------------------------------------------------- #


async def test_index_lists_categories(client, repo_root):
    response = await client.get("/api/method/index")
    assert response.status_code == 200
    body = response.json()
    categories = {category["id"]: category for category in body["categories"]}
    assert "META" in categories
    assert categories["META"]["official"] is True
    assert categories["META"]["title"] == "Meta Documents"
    assert categories["META"]["count"] == 2
    assert "SK" in categories and categories["SK"]["official"] is True
    assert body["count"] == len(body["docs"])
    assert [doc["path"] for doc in body["docs"]] == sorted(doc["path"] for doc in body["docs"])
    assert body["corpus_hash"]


async def test_index_excludes_implementation_artifacts(client, repo_root):
    body = (await client.get("/api/method/index")).json()
    paths = [doc["path"] for doc in body["docs"]]
    assert not any("implementation-artifacts" in path for path in paths)
    assert not any("duvidas" in path for path in paths)


async def test_index_includes_non_official_category(client, repo_root):
    body = (await client.get("/api/method/index")).json()
    categories = {category["id"]: category for category in body["categories"]}
    assert "RULES" in categories
    assert categories["RULES"]["official"] is False
    assert categories["RULES"]["count"] == 1
    assert categories["RULES"]["path"] == "docs/rules"


async def test_corpus_hash_changes_with_content(client, repo_root, tmp_path, monkeypatch):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE_ROOT / "docs", root / "docs")
    monkeypatch.setattr(settings, "repo_root", root)
    method_router.reset_services()

    first = (await client.get("/api/method/index")).json()["corpus_hash"]
    target = root / "docs" / "rules" / "coding.md"
    target.write_text(target.read_text(encoding="utf-8") + "\nlinha nova\n", encoding="utf-8")
    second = (await client.get("/api/method/index")).json()["corpus_hash"]
    assert first != second


async def test_corpus_hash_format(client, repo_root):
    """sha256 de `relpath + "\0" + sha256_hex + "\n"`, com relpath relativo a `docs/`."""
    body = (await client.get("/api/method/index")).json()
    parts = [
        f"{doc['path'][len('docs/'):]}\0{doc['hash']}\n"
        for doc in sorted(body["docs"], key=lambda doc: doc["path"])
    ]
    expected = hashlib.sha256("".join(parts).encode()).hexdigest()
    assert body["corpus_hash"] == expected


# --------------------------------------------------------------------------- #
# GET /api/method/doc/{doc_id}
# --------------------------------------------------------------------------- #


async def test_doc_by_id(client, repo_root):
    response = await client.get("/api/method/doc/META-004")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "META-004"
    assert body["category"] == "META"
    assert body["path"] == "docs/META/META-004_WORKSPACE_CONVENTION.md"
    assert body["frontmatter"]["type"] == "Meta"
    assert body["frontmatter"]["title"] == "META-004 — Workspace Convention"
    assert body["content"].startswith("---")


async def test_doc_by_relative_path(client, repo_root):
    by_id = await client.get("/api/method/doc/META-004")
    by_path = await client.get("/api/method/doc/docs/META/META-004_WORKSPACE_CONVENTION.md")
    assert by_path.status_code == 200
    assert by_path.json()["hash"] == by_id.json()["hash"]


async def test_doc_by_title_prefix(client, repo_root):
    response = await client.get("/api/method/doc/SK-001")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == "SK-001"
    assert body["category"] == "SK"


async def test_doc_content_matches_disk(client, repo_root):
    expected = (FIXTURE_ROOT / "docs" / "META" / "META-004_WORKSPACE_CONVENTION.md").read_bytes()
    body = (await client.get("/api/method/doc/META-004")).json()
    assert body["content"].encode("utf-8") == expected
    assert body["hash"] == hashlib.sha256(expected).hexdigest()


async def test_doc_not_found_404(client, repo_root):
    response = await client.get("/api/method/doc/nao-existe")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# --------------------------------------------------------------------------- #
# GET /api/method/search
# --------------------------------------------------------------------------- #


async def test_search_response_shape(client, method_corpus):
    response = await client.get("/api/method/search", params={"q": "workspace convention"})
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "workspace convention"
    assert body["hits"], "esperava ao menos um hit"
    for hit in body["hits"]:
        assert set(hit) == HIT_KEYS


async def test_search_hits_are_method_corpus(client, method_corpus, pool):
    await pool.execute(
        "INSERT INTO chunks (source_kind, heading, text, token_count, corpus_id) "
        "VALUES ('br', 'Workspace de outro repo', 'workspace convention', 3, $1)",
        "repo:00000000-0000-0000-0000-000000000000",
    )
    try:
        body = (await client.get("/api/method/search", params={"q": "workspace convention"})).json()
        assert body["hits"]
        for hit in body["hits"]:
            assert hit["corpus_id"] == "method"
            assert hit["source_kind"] == "method"
            assert hit["artifact_id"] is None
            assert hit["demand_id"] is None
    finally:
        await pool.execute("DELETE FROM chunks WHERE corpus_id <> 'method'")


async def test_search_empty_query_400(client, method_corpus):
    response = await client.get("/api/method/search", params={"q": ""})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_query"


async def test_search_no_match_returns_empty(client, method_corpus):
    response = await client.get("/api/method/search", params={"q": "xyzzy-inexistente"})
    assert response.status_code == 200
    assert response.json() == {"query": "xyzzy-inexistente", "hits": []}


async def test_search_respects_top(client, method_corpus):
    response = await client.get("/api/method/search", params={"q": "workspace convention", "top": 1})
    assert response.status_code == 200
    assert len(response.json()["hits"]) == 1


async def test_search_invalid_top_400(client, method_corpus):
    response = await client.get("/api/method/search", params={"q": "workspace", "top": 0})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_query"


async def test_deterministic_search(client, method_corpus):
    first = (await client.get("/api/method/search", params={"q": "workspace convention"})).json()
    second = (await client.get("/api/method/search", params={"q": "workspace convention"})).json()
    assert first == second


async def test_search_matches_knowledge_shape(client, method_corpus):
    """A forma do hit é a mesma do F7 (`GET /api/knowledge`) — Contrato Comum §7.6."""
    body = (await client.get("/api/method/search", params={"q": "workspace convention"})).json()
    assert set(body) == {"query", "hits"}
    for hit in body["hits"]:
        assert set(hit) == HIT_KEYS
        assert isinstance(hit["score"], float)


# --------------------------------------------------------------------------- #
# Handoff para o F5 — `app/services/method.py`
# --------------------------------------------------------------------------- #


async def test_method_index_api(repo_root):
    """`MethodIndex` expõe `.all()` / `.get()` — o que o resto do sistema consome."""
    index = get_method_index(FIXTURE_ROOT)[0]
    assert [doc.path for doc in index.all()] == sorted(doc.path for doc in index.all())
    assert index.get("META-004").id == "META-004"
    assert index.get("nao-existe") is None


async def test_load_method_documents_handoff(repo_root):
    """`load_method_documents` é o caminho primário do F5 (async, sem banco)."""
    docs = await load_method_documents()
    assert docs, "esperava o corpus do método"
    assert all(doc.content for doc in docs)
    only_meta = await load_method_documents("META")
    assert only_meta and all(doc.category == "META" for doc in only_meta)
    assert await load_method_document("META-004") is not None
    assert await load_method_document("nao-existe") is None


# --------------------------------------------------------------------------- #
# GET /api/skills/*
# --------------------------------------------------------------------------- #


async def test_skills_manifest_shape(client, repo_root, auth_headers):
    response = await client.get("/api/skills/manifest", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == len(body["skills"])
    assert body["count"] >= 1
    for skill in body["skills"]:
        assert set(skill) == SKILL_KEYS
    ponytail = next(skill for skill in body["skills"] if skill["id"] == "ponytail")
    assert ponytail["path"] == "skills/ponytail/SKILL.md"
    assert ponytail["version"] == "0.0.0"
    assert ponytail["description"].startswith("You are a lazy senior developer")


async def test_skills_manifest_stable_hash(client, repo_root, auth_headers):
    first = (await client.get("/api/skills/manifest", headers=auth_headers)).json()
    second = (await client.get("/api/skills/manifest", headers=auth_headers)).json()
    assert first["corpus_hash"] == second["corpus_hash"]
    assert [skill["hash"] for skill in first["skills"]] == [skill["hash"] for skill in second["skills"]]


async def test_skill_content_raw(client, repo_root, auth_headers):
    expected = (FIXTURE_ROOT / "skills" / "ponytail" / "SKILL.md").read_bytes()
    response = await client.get("/api/skills/ponytail", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["content"].encode("utf-8") == expected
    assert body["id"] == "ponytail"


async def test_skill_files_map(client, repo_root, auth_headers):
    body = (await client.get("/api/skills/ponytail", headers=auth_headers)).json()
    assert "README.md" in body["files"]
    assert "SKILL.md" not in body["files"]
    assert body["files"]["README.md"].startswith("# Ponytail")


async def test_skill_hash_format(client, repo_root, auth_headers):
    """sha256 da árvore — mesmo cálculo que o kit (F8) reimplementa em stdlib."""
    body = (await client.get("/api/skills/ponytail", headers=auth_headers)).json()
    skill_dir = FIXTURE_ROOT / "skills" / "ponytail"
    parts = []
    for path in sorted(skill_dir.rglob("*"), key=lambda item: item.relative_to(skill_dir).as_posix()):
        if path.is_file():
            rel = path.relative_to(skill_dir).as_posix()
            parts.append(f"{rel}\0{hashlib.sha256(path.read_bytes()).hexdigest()}\n")
    expected = hashlib.sha256("".join(parts).encode()).hexdigest()
    assert body["hash"] == expected


async def test_skill_not_found_404(client, repo_root, auth_headers):
    response = await client.get("/api/skills/inexistente", headers=auth_headers)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_skills_manifest_requires_auth(client, repo_root):
    response = await client.get("/api/skills/manifest")
    assert response.status_code == 401


async def test_method_read_is_public(client, repo_root):
    assert (await client.get("/api/method/index")).status_code == 200
    assert (await client.get("/api/method/doc/META-004")).status_code == 200
    assert (
        await client.get("/api/method/search", params={"q": "workspace convention"})
    ).status_code == 200


async def test_skills_dir_missing_is_empty(client, tmp_path, monkeypatch, auth_headers):
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    monkeypatch.setattr(settings, "repo_root", root)
    method_router.reset_services()
    response = await client.get("/api/skills/manifest", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["skills"] == []
    assert body["count"] == 0
    assert body["corpus_hash"] == hashlib.sha256(b"").hexdigest()
