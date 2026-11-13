"""Runner do linter de artefatos — fase F2.

Módulo puro: recebe documentos in-memory, devolve findings. Não fala com banco
nem com rede — o acesso ao banco (artefatos sincronizados) é feito pela
implementação ``SyncedArtifacts``, que carrega um snapshot antes do lint.

Universo de links = corpus do método (repo blueprint, lido do disco) + artefatos
já sincronizados do repo de dev (tabela ``artifacts``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol, runtime_checkable

import yaml

from .rules import Finding, RULES, lint_context, normalize

__all__ = [
    "ArtifactDoc",
    "LinkUniverse",
    "MethodCorpus",
    "SyncedArtifacts",
    "CompositeUniverse",
    "parse_frontmatter",
    "infer_kind",
    "parse_document",
    "lint_document",
    "lint_batch",
]


# --------------------------------------------------------------------------- #
# Documento
# --------------------------------------------------------------------------- #


@dataclass
class ArtifactDoc:
    """Um artefato (BR/SPEC) pronto para o lint."""

    path: str
    content: str
    frontmatter: dict[str, str]
    body: str
    kind: str | None
    repo_id: str | None = None


@runtime_checkable
class LinkUniverse(Protocol):
    """Fonte de verdade dos links citados por um artefato."""

    def exists(self, ref: str) -> bool: ...

    def resolve(self, ref: str) -> str | None: ...


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

_ID_PREFIX = re.compile(r"^[A-Z]{2,4}-\d{3}")
_TITLE_ID = re.compile(r"\b([A-Z]{2,4}-\d{3})\b")


def parse_frontmatter(content: str) -> tuple[dict, str]:
    """Separa frontmatter YAML e body. Sem frontmatter → ({}, content)."""
    text = content.lstrip("﻿").lstrip()
    if not text.startswith("---"):
        return {}, content
    lines = text.splitlines()
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            raw = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1 :])
            try:
                data = yaml.safe_load(raw)
            except yaml.YAMLError:
                data = None
            if not isinstance(data, dict):
                data = {}
            return data, body
    return {}, content


def infer_kind(path: str) -> str | None:
    """``docs/BR/...`` -> br, ``docs/SPEC/...`` -> spec, caso contrário None."""
    normalized = path.replace("\\", "/")
    if normalized.startswith("docs/BR/"):
        return "br"
    if normalized.startswith("docs/SPEC/"):
        return "spec"
    return None


def parse_document(
    path: str, content: str, repo_id: str | None = None
) -> ArtifactDoc:
    """Monta um ``ArtifactDoc`` a partir de path + conteúdo bruto."""
    frontmatter, body = parse_frontmatter(content)
    return ArtifactDoc(
        path=path,
        content=content,
        frontmatter=frontmatter,
        body=body,
        kind=infer_kind(path),
        repo_id=repo_id,
    )


# --------------------------------------------------------------------------- #
# Universo: corpus do método
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Entry:
    path: str
    doc_id: str | None
    title: str | None
    name: str


class MethodCorpus:
    """Índice em memória dos ``.md`` sob ``docs/`` do repo blueprint.

    Indexa, para cada documento: path relativo, id do frontmatter (ou id
    derivado do nome do arquivo), title do frontmatter e nome do arquivo sem
    extensão.
    """

    def __init__(self, root: Path):
        self.root = Path(root)
        self._paths: dict[str, _Entry] = {}
        self._by_id: dict[str, str] = {}
        self._by_title: dict[str, str] = {}
        self._by_name: dict[str, str] = {}
        self._scan()

    def _scan(self) -> None:
        docs_dir = self.root / "docs"
        if not docs_dir.is_dir():
            return
        for file in sorted(docs_dir.rglob("*.md")):
            relative = file.relative_to(self.root).as_posix()
            frontmatter, _ = parse_frontmatter(
                file.read_text(encoding="utf-8", errors="replace")
            )
            title = _as_text(frontmatter.get("title"))
            doc_id = _as_text(frontmatter.get("id"))
            name = file.stem
            if doc_id is None:
                doc_id = _derive_id(name) or _derive_id(title or "")
            entry = _Entry(path=relative, doc_id=doc_id, title=title, name=name)
            self._paths[relative] = entry
            self._paths[file.name] = entry
            if doc_id:
                self._by_id.setdefault(doc_id.upper(), relative)
            if title:
                self._by_title.setdefault(normalize(title), relative)
                stripped = _strip_id_prefix(title)
                if stripped:
                    self._by_title.setdefault(normalize(stripped), relative)
            self._by_name.setdefault(normalize(name), relative)

    def refresh(self) -> int:
        """Reindexa o corpus do disco. Devolve quantos documentos foram indexados.

        Chamado pelo servidor quando o hash do método muda (design master §7.1).
        """
        self._paths.clear()
        self._by_id.clear()
        self._by_title.clear()
        self._by_name.clear()
        self._scan()
        return len({entry.path for entry in self._paths.values()})

    def exists(self, ref: str) -> bool:
        return self.resolve(ref) is not None

    def resolve(self, ref: str) -> str | None:
        candidate = (ref or "").strip().replace("\\", "/")
        if not candidate:
            return None
        if candidate in self._paths:
            return self._paths[candidate].path
        key = candidate.upper()
        if key in self._by_id:
            return self._by_id[key]
        normalized = normalize(candidate)
        if normalized in self._by_title:
            return self._by_title[normalized]
        if normalized in self._by_name:
            return self._by_name[normalized]
        return None


def _as_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
        if value is None:
            return None
    text = str(value).strip()
    return text or None


def _derive_id(text: str) -> str | None:
    """Id do artefato: prefixo do nome do arquivo (``META-000_BLUEPRINT``) ou
    do título (``META-000 — Blueprint Knowledge Model``)."""
    if not text:
        return None
    match = _ID_PREFIX.match(text)
    if match:
        return match.group(0)
    match = _TITLE_ID.search(text)
    return match.group(1) if match else None


def _strip_id_prefix(title: str) -> str | None:
    """Título sem o prefixo de id: 'META-000 — Blueprint Knowledge Model' ->
    'Blueprint Knowledge Model'."""
    match = re.match(r"^\s*[A-Z]{2,4}-\d{3}\s*[—–\-:]\s*(.+)$", title)
    return match.group(1).strip() if match else None


# --------------------------------------------------------------------------- #
# Universo: artefatos sincronizados
# --------------------------------------------------------------------------- #


class SyncedArtifacts:
    """Artefatos já sincronizados do repo de dev (tabela ``artifacts``).

    ``exists``/``resolve`` são síncronos (o linter é síncrono e puro): o snapshot
    é carregado por ``await refresh()`` antes do lint.
    """

    def __init__(self, pool: Any):
        self._pool = pool
        self._by_id: dict[str, str] = {}
        self._by_path: dict[str, str] = {}
        self._by_title: dict[str, str] = {}
        self._loaded = False

    async def refresh(self) -> int:
        """Recarrega o snapshot da tabela ``artifacts``. Devolve quantos linhas."""
        rows = await self._pool.fetch(
            "SELECT id, path, content FROM artifacts"
        )
        self._by_id.clear()
        self._by_path.clear()
        self._by_title.clear()
        for row in rows:
            artifact_id = _as_text(row["id"])
            path = _as_text(row["path"])
            if artifact_id:
                self._by_id.setdefault(artifact_id.upper(), path or artifact_id)
            if path:
                self._by_path.setdefault(path.replace("\\", "/"), path)
                self._by_path.setdefault(Path(path).name, path)
            content = row["content"]
            if content:
                frontmatter, _ = parse_frontmatter(content)
                title = _as_text(frontmatter.get("title"))
                if title:
                    self._by_title.setdefault(normalize(title), path or artifact_id or "")
        self._loaded = True
        return len(self._by_id)

    @property
    def loaded(self) -> bool:
        return self._loaded

    def exists(self, ref: str) -> bool:
        return self.resolve(ref) is not None

    def resolve(self, ref: str) -> str | None:
        candidate = (ref or "").strip().replace("\\", "/")
        if not candidate:
            return None
        if candidate in self._by_path:
            return self._by_path[candidate]
        key = candidate.upper()
        if key in self._by_id:
            return self._by_id[key]
        normalized = normalize(candidate)
        if normalized in self._by_title:
            return self._by_title[normalized]
        return None


# --------------------------------------------------------------------------- #
# Universo: composição
# --------------------------------------------------------------------------- #


class CompositeUniverse:
    """União de vários universos — o primeiro que resolve vence."""

    def __init__(self, *universes: LinkUniverse):
        self._universes = list(universes)

    def exists(self, ref: str) -> bool:
        return self.resolve(ref) is not None

    def resolve(self, ref: str) -> str | None:
        for universe in self._universes:
            found = universe.resolve(ref)
            if found is not None:
                return found
        return None


class _BatchUniverse:
    """Universo virtual: os próprios documentos do lote.

    Resolve pelo id do frontmatter, pelo path e pelo title.
    """

    def __init__(self, docs: Iterable[ArtifactDoc]):
        self._by_id: dict[str, str] = {}
        self._by_path: dict[str, str] = {}
        self._by_title: dict[str, str] = {}
        for doc in docs:
            path = doc.path.replace("\\", "/")
            self._by_path.setdefault(path, path)
            self._by_path.setdefault(Path(path).name, path)
            doc_id = _as_text(doc.frontmatter.get("id"))
            if doc_id:
                self._by_id.setdefault(doc_id.upper(), path)
            title = _as_text(doc.frontmatter.get("title"))
            if title:
                self._by_title.setdefault(normalize(title), path)
                stripped = _strip_id_prefix(title)
                if stripped:
                    self._by_title.setdefault(normalize(stripped), path)

    def exists(self, ref: str) -> bool:
        return self.resolve(ref) is not None

    def resolve(self, ref: str) -> str | None:
        candidate = (ref or "").strip().replace("\\", "/")
        if not candidate:
            return None
        if candidate in self._by_path:
            return self._by_path[candidate]
        key = candidate.upper()
        if key in self._by_id:
            return self._by_id[key]
        normalized = normalize(candidate)
        if normalized in self._by_title:
            return self._by_title[normalized]
        return None


# --------------------------------------------------------------------------- #
# Execução
# --------------------------------------------------------------------------- #


def _run(doc: ArtifactDoc, docs: list[ArtifactDoc], universe: LinkUniverse) -> list[Finding]:
    findings: list[Finding] = []
    with lint_context(doc, universe, docs):
        for rule in RULES:
            findings.extend(rule.check(doc))
    return findings


def _sort_key(finding: Finding) -> tuple[str, str, str]:
    return (finding.path or "", finding.rule, finding.message)


def lint_document(doc: ArtifactDoc, universe: LinkUniverse) -> list[Finding]:
    """Lint de um documento. Determinístico: mesmo input → mesma saída."""
    effective = CompositeUniverse(universe, _BatchUniverse([doc]))
    findings = _run(doc, [doc], effective)
    return sorted(findings, key=_sort_key)


def lint_batch(docs: list[ArtifactDoc], universe: LinkUniverse) -> list[Finding]:
    """Lint de um lote — as regras cruzadas (cobertura de AC, grafo de SPECs)
    enxergam o lote inteiro."""
    batch = list(docs)
    effective = CompositeUniverse(universe, _BatchUniverse(batch))
    findings: list[Finding] = []
    for doc in batch:
        findings.extend(_run(doc, batch, effective))
    return sorted(findings, key=_sort_key)
