"""Indexação do conhecimento em chunks pesquisáveis — fase F7.

Replica o chunking e a fórmula do `tools/retrieve.py` (inalterado) sobre o índice
Postgres. Dois corpora, nunca misturados:

* `method`       — `docs/` do repo blueprint (somente leitura).
* `repo:<uuid>`  — artefatos, commits e reviews de **um** repo.

Invariante: toda query SQL carrega `WHERE corpus_id = $1` com o corpus exato do
pedido. Não existe `LIKE`, `IN` com dois valores, nem fallback de corpus vazio.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # tipos apenas — o import real é tardio (F1/F2 podem não existir)
    from app.lint.runner import ArtifactDoc
    from app.models import Commit, Review

__all__ = [
    "Chunk",
    "tokenize",
    "chunk_markdown",
    "source_kind_for",
    "index_method",
    "index_artifact",
    "index_commit",
    "index_review",
    "ensure_method_indexed",
]

METHOD_CORPUS = "method"

_WORD = re.compile(r"\w+", re.UNICODE)
_SPLIT = re.compile(r"^(#{1,3} .+)$", re.M)

#: TTL do cache em processo do gate de hash do corpus do método (§8.7).
METHOD_INDEX_TTL_SECONDS = 60.0

_INSERT_CHUNK_SQL = """
INSERT INTO chunks (artifact_id, demand_id, source_kind, heading, text,
                    token_count, corpus_id, source_ref)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
"""

_SELECT_METHOD_HASH_SQL = """
SELECT payload->>'content_hash' AS content_hash
  FROM events
 WHERE type = 'method_corpus_indexed'
 ORDER BY id DESC
 LIMIT 1
"""

_INSERT_METHOD_EVENT_SQL = """
INSERT INTO events (demand_id, artifact_id, type, payload, actor)
VALUES (NULL, NULL, 'method_corpus_indexed', $1::jsonb, NULL)
"""


@dataclass
class Chunk:
    """Chunk do índice. Fonte da verdade do chunking (o `Chunk` de `app/models.py` é a visão da linha)."""

    heading: str
    text: str
    source_kind: str
    artifact_id: str | None = None
    demand_id: str | None = None
    corpus_id: str = METHOD_CORPUS
    token_count: int = 0


def tokenize(text: str) -> list[str]:
    """Minúsculas, `\\w+`, descarta token de 1 caractere — igual ao `tools/retrieve.py`."""
    return [w.lower() for w in _WORD.findall(text) if len(w) > 1]


def _strip_frontmatter(text: str) -> str:
    """Corta o frontmatter YAML — idêntico ao `tools/retrieve.py`."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


def _make_chunk(heading: str, text: str) -> Chunk:
    return Chunk(
        heading=heading,
        text=text,
        source_kind="",
        token_count=len(tokenize(heading + "\n" + text)),
    )


def chunk_markdown(text: str, heading_path: list[str] | None = None) -> list[Chunk]:
    """Divide o markdown em chunks de seção H2 (H1/H3 como sub-unidades).

    Réplica do `tools/retrieve.py`: mesmo regex, mesmo corte de 800 caracteres,
    mesmo tokenize. `heading_path` é a trilha de ancestrais do chunk — para o
    corpus `method` é sempre `[]`.
    """
    path = list(heading_path or [])
    body_text = _strip_frontmatter(text)
    parts = _SPLIT.split(body_text)
    chunks: list[Chunk] = []
    for i in range(1, len(parts), 2):
        heading = parts[i].lstrip("# ").strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        if not heading or not body.strip():
            continue
        chunks.append(_make_chunk(" > ".join(path + [heading]), body.strip()[:800]))
    if not chunks:
        chunks.append(_make_chunk(path[-1] if path else "documento", body_text[:800]))
    return chunks


def source_kind_for(path: str, kind: str | None = None) -> str | None:
    """`source_kind` do artefato: por path canônico (META-004), depois pelo `kind` do doc."""
    p = (path or "").replace("\\", "/")
    if p.startswith("docs/BR/"):
        return "br"
    if p.startswith("docs/SPEC/"):
        return "spec"
    if p.startswith("docs/implementation-artifacts/duvidas-"):
        return "doubt"
    if kind == "br":
        return "br"
    if kind == "spec":
        return "spec"
    return None


def _heading_path(frontmatter: dict) -> list[str]:
    """`[<id> — <title>]` a partir do frontmatter, descartando partes vazias."""
    fm = frontmatter or {}
    pieces = [str(fm.get(key) or "").strip() for key in ("id", "title")]
    pieces = [p for p in pieces if p]
    return [" — ".join(pieces)] if pieces else []


def _uuid(value: Any) -> Any:
    """Normaliza id de repo/demanda para `uuid.UUID` (asyncpg exige o tipo, não str)."""
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _as_list(value: Any) -> list:
    """Coluna `jsonb` (files, findings) pode chegar como lista ou como texto JSON."""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


async def index_method() -> int:
    """Reindexa o corpus `method` (docs/). Retorna o número de chunks inseridos.

    Se o hash do corpus não mudou, retorna 0 sem tocar no índice.
    """
    from app.config import settings
    from app.db import get_pool

    root = Path(settings.repo_root) / "docs"
    files = sorted(root.rglob("*.md")) if root.is_dir() else []

    digest = hashlib.sha256()
    contents: list[tuple[str, str]] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        content = path.read_text(encoding="utf-8")
        contents.append((rel, content))
        digest.update(f"{rel}:{hashlib.sha256(content.encode('utf-8')).hexdigest()}\n".encode())
    content_hash = digest.hexdigest()

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(_SELECT_METHOD_HASH_SQL)
            if row is not None and row["content_hash"] == content_hash:
                return 0
            await conn.execute("DELETE FROM chunks WHERE corpus_id = $1", METHOD_CORPUS)
            count = 0
            for rel, content in contents:
                for chunk in chunk_markdown(content, []):
                    chunk.source_kind = METHOD_CORPUS
                    chunk.corpus_id = METHOD_CORPUS
                    await conn.execute(
                        _INSERT_CHUNK_SQL,
                        chunk.artifact_id,
                        chunk.demand_id,
                        chunk.source_kind,
                        chunk.heading,
                        chunk.text,
                        chunk.token_count,
                        chunk.corpus_id,
                        rel,
                    )
                    count += 1
            payload = json.dumps(
                {"content_hash": content_hash, "chunk_count": count, "root": "docs"}
            )
            await conn.execute(_INSERT_METHOD_EVENT_SQL, payload)
    return count


async def index_artifact(doc: "ArtifactDoc", corpus_id: str) -> int:
    """Indexa um artefato (BR/SPEC/dúvida) no corpus recebido.

    O `corpus_id` é sempre o do chamador — nunca deduzido.
    """
    from app.db import get_pool

    source_kind = source_kind_for(doc.path, doc.kind)
    if source_kind is None:
        return 0

    pool = await get_pool()
    artifact_id: str | None = None
    demand_id: str | None = None
    repo_id = _uuid(doc.repo_id)
    if repo_id:
        row = await pool.fetchrow(
            "SELECT id, demand_id FROM artifacts WHERE repo_id = $1 AND path = $2",
            repo_id,
            doc.path,
        )
        if row is not None:
            artifact_id = row["id"]
            demand_id = row["demand_id"]
    if not artifact_id:
        artifact_id = str((doc.frontmatter or {}).get("id") or "").strip() or None
    if not artifact_id:
        # Chunk sem artifact_id num corpus de repo duplicaria a cada sync.
        return 0

    chunks = chunk_markdown(doc.content, _heading_path(doc.frontmatter))
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM chunks WHERE corpus_id = $1 AND source_ref = $2",
                corpus_id,
                artifact_id,
            )
            for chunk in chunks:
                chunk.source_kind = source_kind
                chunk.artifact_id = artifact_id
                chunk.demand_id = demand_id
                chunk.corpus_id = corpus_id
                await conn.execute(
                    _INSERT_CHUNK_SQL,
                    chunk.artifact_id,
                    chunk.demand_id,
                    chunk.source_kind,
                    chunk.heading,
                    chunk.text,
                    chunk.token_count,
                    chunk.corpus_id,
                    artifact_id,
                )
    return len(chunks)


async def index_commit(commit: "Commit") -> int:
    """Indexa um commit reportado no corpus `repo:<uuid>` do próprio commit."""
    from app.db import get_pool

    corpus_id = f"repo:{commit.repo_id}"
    source_ref = commit.sha
    text = (commit.message or "") + "\n\n" + "\n".join(_as_list(commit.files))
    chunks = chunk_markdown(text, [f"commit {commit.sha[:7]}"])

    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM chunks WHERE corpus_id = $1 AND source_ref = $2", corpus_id, source_ref
            )
            for chunk in chunks:
                chunk.source_kind = "commit"
                chunk.artifact_id = None
                chunk.demand_id = _uuid(commit.demand_id)
                chunk.corpus_id = corpus_id
                await conn.execute(
                    _INSERT_CHUNK_SQL,
                    chunk.artifact_id,
                    chunk.demand_id,
                    chunk.source_kind,
                    chunk.heading,
                    chunk.text,
                    chunk.token_count,
                    chunk.corpus_id,
                    source_ref,
                )
    return len(chunks)


async def index_review(review: "Review") -> int:
    """Indexa uma review no corpus `repo:<uuid>` do commit avaliado.

    Um chunk por achado; review sem achados vira um chunk de resumo.
    """
    from app.db import get_pool

    pool = await get_pool()
    commit = await pool.fetchrow(
        "SELECT repo_id, sha FROM commits WHERE id = $1", _uuid(review.commit_id)
    )
    if commit is None:
        return 0

    corpus_id = f"repo:{commit['repo_id']}"
    source_ref = str(review.id)
    findings = _as_list(review.findings)
    if findings:
        sections: list[str] = []
        for finding in findings:
            ac = str(finding.get("ac") or "").strip()
            title = str(finding.get("title") or "").strip()
            label = f"{ac} — {title}" if ac else title
            detail = str(finding.get("detail") or "").strip()
            suggestion = str(finding.get("suggestion") or "").strip()
            body = "\n\n".join(part for part in (detail, suggestion) if part) or title
            sections.append(f"## {label}\n\n{body}")
        text = "\n\n".join(sections)
    else:
        text = f"verdict: {review.verdict}"

    chunks = chunk_markdown(text, [f"review {commit['sha'][:7]} — {review.verdict}"])

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM chunks WHERE corpus_id = $1 AND source_ref = $2", corpus_id, source_ref
            )
            for chunk in chunks:
                chunk.source_kind = "review"
                chunk.artifact_id = None
                chunk.demand_id = _uuid(review.demand_id)
                chunk.corpus_id = corpus_id
                await conn.execute(
                    _INSERT_CHUNK_SQL,
                    chunk.artifact_id,
                    chunk.demand_id,
                    chunk.source_kind,
                    chunk.heading,
                    chunk.text,
                    chunk.token_count,
                    chunk.corpus_id,
                    source_ref,
                )
    return len(chunks)


_last_method_check: float = float("-inf")


async def ensure_method_indexed() -> int:
    """Indexa o corpus `method` se o conteúdo de `docs/` mudou (cache de 60 s)."""
    global _last_method_check
    now = time.monotonic()
    if now - _last_method_check < METHOD_INDEX_TTL_SECONDS:
        return 0
    count = await index_method()
    # Timestamp só depois do sucesso: se a indexação falhar, a próxima busca tenta de novo.
    _last_method_check = time.monotonic()
    return count
