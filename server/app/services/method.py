"""Serviço do corpus do método — documentos de `docs/` (somente leitura). F3.

O corpus é lido do disco do repo blueprint (`settings.repo_root / "docs"`) e
**nunca** é gravado em disco nem no banco: é reconstruído do git a cada boot
(invariante 4 do design master).

F3 entrega busca **provisória** — FTS puro no Postgres (`ts_rank_cd`). F7 troca a
implementação por BM25 de duas etapas **sem mudar a forma da resposta**
(Contrato Comum §7.6).

`MethodIndex` guarda metadados + conteúdo + hash. É **diferente** do `MethodCorpus`
do F2 (`app/lint/runner.py`), que resolve `[[wiki-links]]` para o linter: o F2 é
composto aqui (import tardio), nunca copiado.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "CATEGORIES",
    "CATEGORY_TITLES",
    "EXCLUDED_DIRS",
    "MAX_TEXT",
    "MethodDoc",
    "MethodIndex",
    "Chunk",
    "chunk_document",
    "get_method_index",
    "index_chunks",
    "load_method_document",
    "load_method_documents",
    "reset_method_index",
    "search",
    "sha256_hex",
    "split_frontmatter",
    "tokenize",
]

CATEGORIES: tuple[str, ...] = ("BR", "PRD", "SPEC", "ADR", "ES", "PAT", "LS", "TS", "TP", "RI", "META", "SK")

CATEGORY_TITLES: dict[str, str] = {
    "BR": "Business Rules",
    "PRD": "Product Requirements",
    "SPEC": "Functional Specifications",
    "ADR": "Architecture Decision Records",
    "ES": "Engineering Standards",
    "PAT": "Patterns",
    "LS": "Language Standards",
    "TS": "Technology Standards",
    "TP": "Technology Packs",
    "RI": "Reference Implementations",
    "META": "Meta Documents",
    "SK": "Skills",
}

#: Diretórios de `docs/` que **não** são conhecimento do método (META-006 §9).
EXCLUDED_DIRS: tuple[str, ...] = ("implementation-artifacts",)

#: Teto de caracteres por chunk — mesmo teto do `tools/retrieve.py`.
MAX_TEXT = 800

#: Tokenizador de referência — idêntico ao `tools/retrieve.py`.
_WORD = re.compile(r"\w+", re.UNICODE)

_ID_PREFIX = re.compile(r"^([A-Z]{2,4}-\d{3})\b")
_TITLE_PREFIX = re.compile(r"^([A-Z]{2,4}-\d{3})\s+—")
_SLUG_PREFIX = re.compile(r"^[A-Z]{2,4}-\d{3}[_\-\s]*")
_H1 = re.compile(r"^# (.+)$", re.M)
_H2 = re.compile(r"^## (.+)$", re.M)

_KINDS = {"BR": "br", "SPEC": "spec", "META": "meta", "SK": "skill", "ES": "es"}


# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class MethodDoc:
    """Um documento do corpus do método."""

    id: str
    title: str
    category: str
    path: str
    kind: str
    frontmatter: dict[str, str]
    content: str
    hash: str


@dataclass(frozen=True)
class Chunk:
    """Trecho indexável de um documento (seção H2)."""

    heading: str
    text: str
    token_count: int


# --------------------------------------------------------------------------- #
# Helpers de arquivo
# --------------------------------------------------------------------------- #


def split_frontmatter(content: str) -> tuple[dict[str, str], str]:
    """Separa o frontmatter YAML do corpo. Devolve `({}, content)` se não houver."""
    if not content.startswith("---"):
        return {}, content
    end = content.find("\n---", 3)
    if end == -1:
        return {}, content
    try:
        data = yaml.safe_load(content[3:end])
    except yaml.YAMLError:
        data = None
    frontmatter: dict[str, str] = {}
    if isinstance(data, dict):
        frontmatter = {str(k): _scalar(v) for k, v in data.items()}
    return frontmatter, content[end + 4 :]


def _scalar(value: Any) -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple)):
        return ", ".join(_scalar(v) for v in value)
    return str(value)


def sha256_hex(data: str | bytes) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


def tokenize(text: str) -> list[str]:
    """Tokenizador de referência — mesmo do `tools/retrieve.py`."""
    return [w.lower() for w in _WORD.findall(text) if len(w) > 1]


def _first_h1(body: str) -> str:
    match = _H1.search(body)
    return match.group(1).strip() if match else ""


def _strip_first_h1(body: str) -> str:
    return _H1.sub("", body, count=1)


def _normalize_title(title: str) -> str:
    """Minúsculas, sem acento, espaços colapsados."""
    decomposed = unicodedata.normalize("NFD", title.lower())
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(without_accents.split())


def _slug(path: Path) -> str:
    """Slug do arquivo: stem sem o prefixo, minúsculo, `_`→`-`."""
    stem = path.stem
    if stem.upper() == "SKILL":
        stem = path.parent.name
    stem = _SLUG_PREFIX.sub("", stem)
    return stem.lower().replace("_", "-").replace(" ", "-")


# --------------------------------------------------------------------------- #
# Índice
# --------------------------------------------------------------------------- #


class MethodIndex:
    """Índice de documentos do método. NÃO é o `MethodCorpus` do F2."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.docs_dir = self.root / "docs"
        # `MethodCorpus` do F2 — opcional e tardio: o MethodIndex funciona sozinho.
        self.corpus = None
        try:
            from app.lint.runner import MethodCorpus  # type: ignore[import-not-found]
        except Exception:  # pragma: no cover - F2 pode ainda não existir
            pass
        else:
            try:
                self.corpus = MethodCorpus(self.root)
            except Exception:  # pragma: no cover - F2 pode ainda não existir
                self.corpus = None
        self._docs: list[MethodDoc] = []
        self._by_path: dict[str, MethodDoc] = {}
        self._cache: dict[str, tuple[tuple[int, int], MethodDoc]] = {}
        self._corpus_hash = ""
        self.refresh()

    # -- leitura ------------------------------------------------------------ #

    @property
    def corpus_hash(self) -> str:
        return self._corpus_hash

    def all(self) -> list[MethodDoc]:
        """Todos os documentos, ordenados por path."""
        return list(self._docs)

    def by_path(self, path: str) -> MethodDoc | None:
        """Documento pelo path repo-relativo (ou relativo a `docs/`)."""
        if not path:
            return None
        key = path.replace("\\", "/").strip().lstrip("./")
        doc = self._by_path.get(key)
        if doc is not None:
            return doc
        return self._by_path.get(f"docs/{key}")

    def get(self, doc_id: str) -> MethodDoc | None:
        """Resolve `doc_id` em 7 passos (§3.6 da spec F3)."""
        if not doc_id:
            return None
        key = doc_id.strip()
        if not key:
            return None

        # 1 e 2 — path repo-relativo ou relativo a `docs/`
        doc = self.by_path(key)
        if doc is not None:
            return doc

        # 3 — id declarado no frontmatter
        for doc in self._docs:
            if doc.frontmatter.get("id", "").strip() == key:
                return doc

        # 4 — prefixo do nome do arquivo
        for doc in self._docs:
            match = _ID_PREFIX.match(Path(doc.path).stem)
            if match and match.group(1) == key:
                return doc

        # 5 — prefixo do título
        for doc in self._docs:
            match = _TITLE_PREFIX.match(doc.title)
            if match and match.group(1) == key:
                return doc

        # 6 — slug do arquivo
        wanted = key.lower()
        for doc in self._docs:
            if _slug(Path(doc.path)) == wanted:
                return doc

        # 7 — título normalizado
        wanted_title = _normalize_title(key)
        for doc in self._docs:
            if _normalize_title(doc.title) == wanted_title:
                return doc

        return None

    def categories(self) -> list[dict]:
        """Categorias presentes no disco: oficiais primeiro (por `CATEGORIES`), resto alfabético."""
        groups: dict[str, list[MethodDoc]] = {}
        for doc in self._docs:
            groups.setdefault(doc.category, []).append(doc)
        official = [c for c in CATEGORIES if c in groups]
        unofficial = sorted(c for c in groups if c not in CATEGORIES)
        entries: list[dict] = []
        for category in official + unofficial:
            sample = groups[category][0].path.split("/")
            directory = "docs" if len(sample) <= 2 else sample[1]
            entries.append(
                {
                    "id": category,
                    "title": CATEGORY_TITLES.get(category, category.replace("-", " ").title()),
                    "path": directory if directory == "docs" else f"docs/{directory}",
                    "count": len(groups[category]),
                    "official": category in CATEGORIES,
                }
            )
        return entries

    # -- manutenção --------------------------------------------------------- #

    def refresh(self) -> bool:
        """Recalcula o índice. Devolve `True` se o corpus mudou."""
        docs, corpus_hash, cache = self._scan()
        changed = corpus_hash != self._corpus_hash
        self._docs = docs
        self._by_path = {doc.path: doc for doc in docs}
        self._corpus_hash = corpus_hash
        self._cache = cache
        return changed

    # -- interno ------------------------------------------------------------ #

    def _iter_files(self) -> list[Path]:
        if not self.docs_dir.is_dir():
            return []
        found: list[Path] = []
        for path in self.docs_dir.rglob("*.md"):
            if not path.is_file():
                continue
            parts = path.relative_to(self.docs_dir).parts
            if any(part.startswith(".") for part in parts):
                continue
            if any(part in EXCLUDED_DIRS for part in parts):
                continue
            found.append(path)
        return sorted(found)

    def _scan(self) -> tuple[list[MethodDoc], str, dict[str, tuple[tuple[int, int], MethodDoc]]]:
        docs: list[MethodDoc] = []
        cache: dict[str, tuple[tuple[int, int], MethodDoc]] = {}
        for path in self._iter_files():
            rel = path.relative_to(self.root).as_posix()
            try:
                stat = path.stat()
            except OSError:  # pragma: no cover - arquivo sumiu no meio da varredura
                continue
            fingerprint = (stat.st_mtime_ns, stat.st_size)
            cached = self._cache.get(rel)
            if cached is not None and cached[0] == fingerprint:
                doc = cached[1]
            else:
                doc = self._read(path, rel)
            cache[rel] = (fingerprint, doc)
            docs.append(doc)
        docs.sort(key=lambda d: d.path)
        return docs, self._hash_corpus(docs), cache

    def _hash_corpus(self, docs: list[MethodDoc]) -> str:
        """sha256 da concatenação `relpath + "\0" + sha256_hex + "\n"`, em ordem alfabética.

        `relpath` é relativo a `docs/` — mesmo formato do hash de árvore das skills (§4.4).
        """
        parts: list[str] = []
        for doc in docs:
            rel = doc.path[len("docs/") :] if doc.path.startswith("docs/") else doc.path
            parts.append(f"{rel}\0{doc.hash}\n")
        return sha256_hex("".join(parts))

    def _read(self, path: Path, rel: str) -> MethodDoc:
        raw = path.read_bytes()
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:  # pragma: no cover - corpus é UTF-8
            content = raw.decode("utf-8", errors="replace")
        frontmatter, body = split_frontmatter(content)
        title = frontmatter.get("title", "").strip() or _first_h1(body) or path.stem
        category = self._category(rel)
        return MethodDoc(
            id=self._derive_id(frontmatter, path, title),
            title=title,
            category=category,
            path=rel,
            kind=_KINDS.get(category, "doc"),
            frontmatter=frontmatter,
            content=content,
            hash=sha256_hex(content),
        )

    @staticmethod
    def _category(rel: str) -> str:
        parts = rel.split("/")
        if len(parts) <= 2:
            return "ROOT"
        return parts[1].upper()

    @staticmethod
    def _derive_id(frontmatter: dict[str, str], path: Path, title: str) -> str:
        declared = frontmatter.get("id", "").strip()
        if declared:
            return declared
        match = _ID_PREFIX.match(path.stem)
        if match:
            return match.group(1)
        match = _TITLE_PREFIX.match(title)
        if match:
            return match.group(1)
        return _slug(path)


# --------------------------------------------------------------------------- #
# Índice compartilhado e handoff para o F5
# --------------------------------------------------------------------------- #

_index_cache: MethodIndex | None = None


def _default_root() -> Path:
    """Raiz do repo blueprint — `SDD_REPO_ROOT` (ou a raiz do repo, sem `app.config`)."""
    try:
        from app.config import settings

        return Path(settings.repo_root)
    except Exception:  # pragma: no cover - app.config ausente (F1 pendente)
        return Path(__file__).resolve().parents[3]


def get_method_index(root: Path | None = None) -> tuple[MethodIndex, bool]:
    """Índice do método compartilhado — `(índice, corpus mudou desde a última checagem)`.

    O cache vive aqui (e não no router) para que o F5 e a API leiam **a mesma**
    instância. `changed=True` numa raiz nova: o corpus precisa ser reindexado.
    """
    global _index_cache
    target = Path(root) if root is not None else _default_root()
    index = _index_cache
    if index is None or index.root != target:
        index = MethodIndex(target)
        _index_cache = index
        return index, True
    return index, index.refresh()


def reset_method_index() -> None:
    """Limpa o índice compartilhado — troca de raiz e testes."""
    global _index_cache
    _index_cache = None


async def load_method_documents(category: str | None = None) -> list[MethodDoc]:
    """Corpus do método em memória — handoff do F5 (spec F5, "Origem do corpus").

    Sem banco: é leitura do disco (invariante 4). `category` filtra pela
    categoria (`"META"`, `"SK"`, ...); sem filtro, devolve tudo.
    """
    index, _ = get_method_index()
    docs = index.all()
    if category:
        wanted = category.strip().upper()
        docs = [doc for doc in docs if doc.category == wanted]
    return docs


async def load_method_document(doc_id: str) -> MethodDoc | None:
    """Um documento do corpus pelo id — handoff do F5."""
    index, _ = get_method_index()
    return index.get(doc_id)


# --------------------------------------------------------------------------- #
# Chunking e busca
# --------------------------------------------------------------------------- #


def chunk_document(doc: MethodDoc) -> list[Chunk]:
    """Divide o documento por seção H2. Sem H2 → um chunk (heading = H1)."""
    _, body = split_frontmatter(doc.content)
    parts = _H2.split(body)
    raw: list[tuple[str, str]] = []
    if len(parts) == 1:
        raw.append((_first_h1(body) or doc.title, _strip_first_h1(body)))
    else:
        preamble = _strip_first_h1(parts[0])
        if preamble.strip():
            raw.append((_first_h1(body) or doc.title, preamble))
        for index in range(1, len(parts), 2):
            raw.append((parts[index].strip(), parts[index + 1]))

    chunks: list[Chunk] = []
    for heading, text in raw:
        body_text = text.strip()[:MAX_TEXT]
        if not body_text:
            continue
        chunks.append(
            Chunk(
                heading=heading,
                text=body_text,
                token_count=len(tokenize(f"{heading}\n{body_text}")),
            )
        )
    return chunks


async def index_chunks(pool, docs: list[MethodDoc]) -> int:
    """Reindexa o corpus do método. `DELETE` + reinserção — o corpus é derivado.

    `chunks.tsv` é coluna simples (Contrato Comum §4.1): F3 escreve o valor no
    `INSERT` com a **mesma** expressão que o trigger do F7 usará.
    """
    rows: list[tuple[str, str, str, int]] = []
    for doc in docs:
        for chunk in chunk_document(doc):
            rows.append(("method", chunk.heading, chunk.text, chunk.token_count))
    async with pool.acquire() as connection:
        await connection.execute("DELETE FROM chunks WHERE corpus_id = 'method'")
        if rows:
            await connection.executemany(
                "INSERT INTO chunks (source_kind, heading, text, token_count, tsv, corpus_id) "
                "VALUES ($1, $2, $3, $4, "
                "        to_tsvector('portuguese', coalesce($2, '') || ' ' || coalesce($3, '')), "
                "        'method')",
                rows,
            )
    return len(rows)


async def search(pool, query: str, top: int = 50) -> list[dict]:
    """Busca lexical provisória — FTS puro (`ts_rank_cd`) no corpus `method`."""
    rows = await pool.fetch(
        "SELECT heading, text, "
        "       ts_rank_cd(tsv, plainto_tsquery('portuguese', $1)) AS score "
        "  FROM chunks "
        " WHERE corpus_id = 'method' "
        "   AND tsv @@ plainto_tsquery('portuguese', $1) "
        " ORDER BY score DESC, heading ASC, text ASC "
        " LIMIT $2",
        query,
        top,
    )
    return [
        {
            "heading": row["heading"],
            "text": row["text"],
            "score": float(row["score"]),
            "source_kind": "method",
            "artifact_id": None,
            "demand_id": None,
            "corpus_id": "method",
        }
        for row in rows
    ]
