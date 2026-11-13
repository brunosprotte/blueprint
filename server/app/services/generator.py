"""Serviço de geração de BR e SPEC — fase F5 do ambiente SDD multi-agentes.

Executa SK-001 (business discovery) e SK-002 (technical planning) via Claude API e
devolve markdown pronto: frontmatter canônico do método, corpo com as seções
canônicas e o arquivo de dúvidas do artefato.

O servidor **nunca** escreve no repo de dev (invariante 1 do design master): devolve
markdown e quem escreve no repo é o kit (`sdd.py pull`, F8).

Contrato: Contrato Comum §7.3. Spec da fase:
`design/specs/2026-11-10-fase-F5-geracao-br-spec.md`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

import anthropic
import yaml

if TYPE_CHECKING:  # pragma: no cover - apenas para tipagem
    import asyncpg

    from app.models import Artifact, Demand

__all__ = [
    "BR_SCHEMA",
    "BR_SYSTEM_PROMPT",
    "GenerationContext",
    "GenerationReport",
    "InvalidArtifactPath",
    "LLMUnavailable",
    "MethodContext",
    "MethodDocument",
    "RepoContext",
    "SPEC_SCHEMA",
    "SPEC_SYSTEM_PROMPT",
    "build_br_user_prompt",
    "build_client",
    "build_spec_user_prompt",
    "generate_br",
    "generate_br_report",
    "generate_specs",
    "generate_specs_report",
    "render_document",
    "render_doubts_seed",
    "resolve_method_context",
    "resolve_repo_context",
]

# Modelo e limite de tokens — Contrato Comum §5 e §7.3.
MODEL_FALLBACK = "claude-opus-5-5"
MAX_TOKENS = 32000

# META-004 §6 / PATH-001 do F2: kebab-case, sem acento, sem separador duplo.
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# Categorias do corpus do método, da mais abstrata para a mais concreta (META-001).
CATEGORY_PREFIXES = ("SK", "META", "ES", "PAT", "LS", "TS", "TP", "RI", "BR", "SPEC")

# Limite de documentos por categoria na resolução do contexto (spec F5 §5.2).
CATEGORY_LIMITS: dict[str, tuple[tuple[str, int], ...]] = {
    "br": (("SPEC", 5), ("ES", 5), ("PAT", 3), ("LS", 5), ("TS", 2), ("TP", 1), ("RI", 1)),
    # A BR de origem entra fora do corpus (é o artefato de entrada, não um documento).
    "spec": (
        ("SPEC", 5),
        ("ES", 5),
        ("PAT", 3),
        ("LS", 5),
        ("TS", 2),
        ("TP", 1),
        ("RI", 1),
    ),
}

# Demanda em estado terminal: gerar BR/SPEC é transição ilegal (spec F5 §5.8).
TERMINAL_DEMAND_STATUSES = ("merged", "done", "blocked")


class LLMUnavailable(RuntimeError):
    """LLM indisponível: sem credencial, proxy fora, timeout, 5xx, ou recusa."""

    def __init__(
        self,
        message: str,
        *,
        stage: str | None = None,
        reason: str = "llm_unavailable",
        category: str | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.reason = reason
        self.category = category


class InvalidArtifactPath(ValueError):
    """`module`/`feature` devolvidos pelo modelo não casam com o slug canônico."""

    def __init__(self, module: str, feature: str) -> None:
        super().__init__(f"slug inválido: module={module!r} feature={feature!r}")
        self.module = module
        self.feature = feature


class IllegalDemandState(RuntimeError):
    """A demanda está em estado terminal — a geração seria uma transição ilegal."""

    def __init__(self, current: str, target: str) -> None:
        super().__init__(f"{current} -> {target}")
        self.current = current
        self.target = target


@dataclass(frozen=True)
class MethodDocument:
    """Um documento do corpus do método."""

    doc_id: str
    title: str
    category: str
    content: str


@dataclass(frozen=True)
class MethodContext:
    """Corpus do método resolvido por META-001 para uma chamada de geração."""

    documents: tuple[MethodDocument, ...]
    technology_pack: str | None
    degraded: bool
    degraded_reason: str | None


@dataclass(frozen=True)
class RepoContext:
    """Top-k BM25 do corpus do repo (F7) — força reuso, evita duplicar conhecimento."""

    corpus_id: str | None
    hits: tuple[tuple[str, str], ...]
    degraded: bool
    degraded_reason: str | None


@dataclass(frozen=True)
class GenerationContext:
    """Tudo que uma geração precisa. `client=None` usa `build_client()`."""

    pool: "asyncpg.Pool"
    demand_id: str
    repo_id: str
    module: str
    method_context: MethodContext
    repo_context: RepoContext
    client: Any | None = None


@dataclass(frozen=True)
class DoubtsFile:
    """Arquivo de dúvidas do artefato (META-006 §5) — publicado, não escrito no disco."""

    path: str
    content: str


@dataclass(frozen=True)
class SpecEdge:
    """Aresta do grafo de SPECs gravada em `spec_edges`."""

    parent_id: str
    child_id: str
    type: str


@dataclass(frozen=True)
class GenerationReport:
    """Resultado completo de uma geração.

    `artifacts` é a lista de `GeneratedArtifact` do Contrato Comum §7.3 (6 campos).
    O resto viaja no payload da rota (decisão D3 da spec F5): o `GeneratedArtifact`
    não tem onde levar o arquivo de dúvidas, o grafo e o consumo de tokens.
    """

    artifacts: tuple[dict[str, Any], ...]
    doubts_files: tuple[DoubtsFile, ...]
    spec_edges: tuple[SpecEdge, ...]
    usage: dict[str, int] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    created: bool = True
    idempotent: bool = False


# --------------------------------------------------------------------------- #
# Cliente Anthropic
# --------------------------------------------------------------------------- #


def build_client() -> anthropic.AsyncAnthropic:
    """Cliente async. Lê ANTHROPIC_API_KEY e ANTHROPIC_BASE_URL do ambiente.

    D6: o SDK concatena `/v1/messages` ao `base_url`; o proxy do usuário já vem
    com `/v1` (`http://127.0.0.1:20128/v1`) — o sufixo é removido para não gerar
    `/v1/v1/messages`.
    """
    base = os.environ.get("ANTHROPIC_BASE_URL", "").strip().rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    try:
        return anthropic.AsyncAnthropic(base_url=base) if base else anthropic.AsyncAnthropic()
    except anthropic.AnthropicError as exc:
        raise LLMUnavailable(f"credencial ausente: {exc}") from exc


def model_name() -> str:
    """Modelo em uso — `SDD_LLM_MODEL` (Contrato Comum §5), com fallback fixo."""
    try:
        from app.config import settings

        return str(settings.llm_model)
    except Exception:  # app.config ausente (F1 pendente) ou sem SDD_SECRET_KEY
        return os.environ.get("SDD_LLM_MODEL", MODEL_FALLBACK)


# --------------------------------------------------------------------------- #
# Schema de saída (structured outputs)
# --------------------------------------------------------------------------- #

BR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "frontmatter": {
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "feature": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["module", "feature", "title", "description", "tags"],
            "additionalProperties": False,
        },
        "body": {"type": "string"},
    },
    "required": ["frontmatter", "body"],
    "additionalProperties": False,
}

SPEC_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "specs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "feature": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "complexity": {
                        "type": "string",
                        "enum": ["LOW", "MEDIUM", "HIGH", "VERY HIGH"],
                    },
                    "acceptanceCriteria": {"type": "array", "items": {"type": "string"}},
                    "body": {"type": "string"},
                },
                "required": [
                    "feature",
                    "title",
                    "description",
                    "tags",
                    "complexity",
                    "acceptanceCriteria",
                    "body",
                ],
                "additionalProperties": False,
            },
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "parentFeature": {"type": "string"},
                    "childFeature": {"type": "string"},
                    "type": {
                        "type": "string",
                        "enum": ["depends_on", "derives_from", "tests"],
                    },
                },
                "required": ["parentFeature", "childFeature", "type"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["specs", "edges"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------- #
# Prompts (spec F5 §5.10)
# --------------------------------------------------------------------------- #

BR_SYSTEM_PROMPT = """Você executa a Skill SK-001 — Business Discovery do método Blueprint.
Papel: Senior Business Analyst. Toda a conversa permanece no domínio de negócio.
Nunca discuta arquitetura, banco de dados, APIs, linguagens, frameworks ou implementação.
Nunca invente informação ausente: informação desconhecida vira Open Question, não suposição.
Fluxo obrigatório: Business Context → Actors → Capabilities → Business Rules → Domain Language
→ Business Scenarios → Acceptance Criteria → Open Questions → Business Validation → Generate BR.
Cada Acceptance Criteria é objetivo, verificável, numerado no formato AC-\\d{3}, independente de
tecnologia e pequeno o suficiente para virar teste automatizado. Escreva a seção Acceptance
Criteria como uma lista "- AC-001: <critério>".
O corpo Markdown deve conter, nesta ordem, as seções: Objetivo, Contexto, Atores, Capacidades,
Regras de Negócio, Restrições, Exceções, Acceptance Criteria e Open Questions.
A seção Open Questions só entra quando houver dúvida em aberto; cada item é uma linha "- <pergunta>".
Nenhuma informação técnica no corpo.
Reutilize o conhecimento fornecido: não repita o que os documentos de contexto já resolvem.
Responda somente com o JSON do schema fornecido."""

SPEC_SYSTEM_PROMPT = """Você executa a Skill SK-002 — Technical Planning do método Blueprint.
Papel: Software Architect. Transforme a BR em um conjunto de Functional Specifications.
Nunca gere código, nunca escolha tecnologias (a Technology Pack já vem resolvida), nunca crie
regras de negócio e nunca modifique a BR.
Cada SPEC tem responsabilidade única: 1 SPEC = 1 capacidade técnica. Minimize acoplamento;
SPECs independentes devem poder ser implementadas em paralelo.
Todo Acceptance Criteria da BR precisa estar em pelo menos uma SPEC, em "Acceptance Criteria
atendidos". Nenhuma AC pode ficar sem cobertura.
Complexidade de cada SPEC: LOW, MEDIUM, HIGH ou VERY HIGH.
O corpo Markdown de cada SPEC deve conter, nesta ordem, as 14 seções: Objetivo, Escopo,
Responsabilidade, Entradas, Saídas, Fluxo principal, Fluxos alternativos, Validações, Failures,
Pré-condições, Pós-condições, Acceptance Criteria atendidos, Dependências e Blueprint Documents
necessários.
As arestas do grafo usam o feature da SPEC dentro deste lote como identificador. Em "tests", a
SPEC de testes é o parent e a SPEC testada é o child.
Responda somente com o JSON do schema fornecido."""


def build_br_user_prompt(
    *,
    title: str,
    body: str,
    method_context: MethodContext,
    repo_context: RepoContext,
) -> str:
    """Monta o prompt de usuário da BR (spec F5 §5.10)."""
    parts = [
        "# Necessidade",
        title,
        "",
        body,
        "",
        "# Contexto do método (resolvido por META-001)",
        _render_method_documents(method_context),
        "",
        "# Conhecimento prévio do repositório (BM25 sobre artefatos anteriores)",
        _render_repo_hits(repo_context),
        "",
        "Gere a Business Rule da necessidade acima. Se algo for ambíguo ou incerto, registre em",
        "Open Questions em vez de assumir. Não invente ACs que não derivem da necessidade.",
    ]
    return "\n".join(parts)


def build_spec_user_prompt(
    *,
    br_content: str,
    acceptance_criteria: Sequence[str],
    method_context: MethodContext,
    repo_context: RepoContext,
) -> str:
    """Monta o prompt de usuário das SPECs (spec F5 §5.10)."""
    acs = "\n".join(f"- {ac}" for ac in acceptance_criteria)
    parts = [
        "# Business Rule de origem",
        br_content,
        "",
        "# Acceptance Criteria da BR",
        acs,
        "",
        "# Contexto do método (resolvido por META-001)",
        _render_method_documents(method_context),
        "",
        "# Conhecimento prévio do repositório (BM25 sobre artefatos anteriores)",
        _render_repo_hits(repo_context),
        "",
        "Gere o Specification Graph e as Functional Specifications. Cada SPEC cobre exatamente as",
        "responsabilidades que declara em \"Acceptance Criteria atendidos\".",
    ]
    return "\n".join(parts)


def _render_method_documents(method_context: MethodContext) -> str:
    """Serializa o corpus do método para o prompt."""
    if not method_context.documents:
        return "(sem documentos do método disponíveis)"
    blocks = []
    for doc in method_context.documents:
        blocks.append(f"## {doc.doc_id} — {doc.title}\n{doc.content}")
    return "\n\n".join(blocks)


def _render_repo_hits(repo_context: RepoContext) -> str:
    """Serializa os hits BM25 do repo para o prompt."""
    if not repo_context.hits:
        return "(sem conhecimento prévio do repositório)"
    blocks = [f"## {heading}\n{text}" for heading, text in repo_context.hits]
    return "\n\n".join(blocks)


# --------------------------------------------------------------------------- #
# Renderização de markdown
# --------------------------------------------------------------------------- #

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


class _BlueprintDumper(yaml.SafeDumper):
    """SafeDumper que emite strings ISO-8601 com aspas duplas (template canônico)."""


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.Node:
    if _ISO_RE.match(data):
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


_BlueprintDumper.add_representer(str, _represent_str)


def render_document(frontmatter: Mapping[str, Any], body: str) -> str:
    """Monta o markdown do artefato: frontmatter YAML + corpo.

    `sort_keys=False` preserva a ordem de inserção do dict — a ordem canônica do
    template é garantida pela ordem de construção do dict, não pelo dump.
    """
    dumped = yaml.dump(
        dict(frontmatter),
        Dumper=_BlueprintDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    ).rstrip()
    return f"---\n{dumped}\n---\n\n{body.strip()}\n"


def render_doubts_seed(
    artifact_id: str,
    status: str,
    doubts: Sequence[Mapping[str, Any]],
) -> str:
    """Renderiza o arquivo de dúvidas no **formato canônico v1** (META-006 §5).

    F5 cria a primeira versão do arquivo; o F6 precisa re-renderizar byte a byte
    igual no seu `render_doubts_file` (Contrato Comum §7.5).
    """
    rows = list(doubts)
    pending = sum(1 for row in rows if str(row.get("status")) != "cleaned")
    lines = [
        "---",
        f"id: {artifact_id}",
        f"artifactId: {artifact_id}",
        f"status: {status}",
        f'updatedAt: "{_now_iso()}"',
        "---",
        "",
        f"# Dúvidas — {artifact_id}",
        "",
        f"Pendências: {pending}",
        "",
        "| id | status | source | question | raised_at | resolved_at |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row.get("id") or ""),
                    str(row.get("status") or ""),
                    str(row.get("source") or ""),
                    _escape_cell(str(row.get("question") or "")),
                    _iso(row.get("raised_at")),
                    _iso(row.get("resolved_at")) or "—",
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def _escape_cell(text: str) -> str:
    """Escapa o separador de coluna do markdown dentro da tabela de dúvidas."""
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _now_iso() -> str:
    """Timestamp UTC no formato ISO-8601 com sufixo `Z` (spec F5 §5.4)."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso(value: Any) -> str:
    """Formata um datetime (asyncpg) como ISO-8601 `Z`; string passa direto."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


def parse_frontmatter(content: str) -> dict[str, Any]:
    """Lê o bloco de frontmatter YAML de um markdown (vazio se não houver)."""
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------- #
# Contexto: corpus do método (F3) e corpus do repo (F7)
# --------------------------------------------------------------------------- #


def repo_root() -> Path:
    """Raiz do repo blueprint — de onde o corpus do método é lido (leitura, só)."""
    try:
        from app.config import settings

        return Path(settings.repo_root)
    except Exception:  # app.config ausente (F1 pendente) ou sem SDD_SECRET_KEY
        return Path(__file__).resolve().parents[3]


_DOC_ID_RE = re.compile(r"^([A-Z]+-\d+)")


async def load_method_documents() -> tuple[tuple[MethodDocument, ...], bool, str | None]:
    """Carrega o corpus do método (F3). Retorna (documentos, degradado, motivo).

    Sem F3, o corpus é lido localmente de `docs/` (leitura — invariante 4) e o
    contexto sai degradado, sem falhar a geração.
    """
    try:
        from app.services.method import load_method_documents as loader  # F3
    except ImportError:
        loader = None
    if loader is not None:
        try:
            documents = tuple(_as_method_document(doc) for doc in await loader())
            if documents:
                return documents, False, None
        except Exception as exc:
            return _load_local_method_documents(f"F3 indisponível: {exc}")

    try:
        from app.services.method import MethodIndex  # F3, nomes diferentes
    except ImportError:
        MethodIndex = None
    if MethodIndex is not None:
        try:
            index = MethodIndex(repo_root())
            documents = tuple(_as_method_document(doc) for doc in index.all())
            if documents:
                return documents, False, None
        except Exception:
            pass

    return _load_local_method_documents(
        "F3 pendente: corpus do método lido localmente sem índice compartilhado"
    )


def _load_local_method_documents(reason: str) -> tuple[tuple[MethodDocument, ...], bool, str | None]:
    """Varre `docs/` do repo blueprint e indexa os documentos por id e título."""
    documents: list[MethodDocument] = []
    root = repo_root()
    docs_dir = root / "docs"
    if docs_dir.is_dir():
        for path in sorted(docs_dir.rglob("*.md")):
            relative = path.relative_to(root)
            if relative.parts[0] == "implementation-artifacts":
                continue
            if path.name.lower() in ("index.md", "readme.md"):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                continue
            front = parse_frontmatter(text)
            title = str(front.get("title") or "")
            documents.append(
                MethodDocument(
                    doc_id=_doc_id_of(path, title),
                    title=title,
                    category=path.parent.name if path.parent != docs_dir else "ROOT",
                    content=text,
                )
            )
    return tuple(documents), True, reason


def _doc_id_of(path: Path, title: str) -> str:
    """Id canônico do documento: prefixo do nome do arquivo, depois do título."""
    match = _DOC_ID_RE.match(path.stem)
    if match:
        return match.group(1)
    match = _DOC_ID_RE.match(title)
    if match:
        return match.group(1)
    return path.stem


def _as_method_document(doc: Any) -> MethodDocument:
    """Adapta um documento do F3 (`MethodDoc`) ou do F5 ao `MethodDocument`."""
    if isinstance(doc, MethodDocument):
        return doc
    doc_id = str(getattr(doc, "doc_id", None) or getattr(doc, "id", "") or "")
    title = str(getattr(doc, "title", "") or "")
    category = str(getattr(doc, "category", "") or "")
    content = str(getattr(doc, "content", "") or "")
    return MethodDocument(
        doc_id=doc_id,
        title=title,
        category=_category_of(doc_id, category),
        content=content,
    )


def _category_of(doc_id: str, category: str) -> str:
    """Categoria do documento; cai no prefixo do id quando o F3 usa outra taxonomia."""
    if category in CATEGORY_PREFIXES:
        return category
    for prefix in CATEGORY_PREFIXES:
        if doc_id.startswith(f"{prefix}-"):
            return prefix
    return category or "ROOT"


async def resolve_method_context(
    kind: str,
    module: str = "",
    feature: str = "",
    br_content: str | None = None,
) -> MethodContext:
    """Resolve o corpus do método de uma chamada (META-001 §5/§6).

    `kind` é `"br"` (SK-001) ou `"spec"` (SK-002). A skill executada entra sempre;
    o TP é selecionado pelo `technologyPack` da BR de origem, senão pelo único TP do
    corpus, senão pelo de menor id — determinístico, sem heurística de stack.
    """
    documents, degraded, reason = await load_method_documents()
    by_id = {doc.doc_id: doc for doc in documents}
    selected: list[MethodDocument] = []

    skill_id = "SK-001" if kind == "br" else "SK-002"
    for doc_id in (skill_id, "META-001", "META-004"):
        doc = by_id.get(doc_id)
        if doc is not None:
            selected.append(doc)

    if kind == "spec" and br_content:
        selected.append(
            MethodDocument(
                doc_id=_br_id_of(br_content),
                title="Business Rule de origem",
                category="BR",
                content=br_content,
            )
        )

    technology_pack = _select_technology_pack(documents, br_content)
    for category, limit in CATEGORY_LIMITS.get(kind, CATEGORY_LIMITS["br"]):
        for doc in _documents_of_category(documents, category, limit, technology_pack):
            if doc not in selected:
                selected.append(doc)

    return MethodContext(
        documents=tuple(selected),
        technology_pack=technology_pack.doc_id if technology_pack else None,
        degraded=degraded,
        degraded_reason=reason,
    )


def _documents_of_category(
    documents: Sequence[MethodDocument],
    category: str,
    limit: int,
    technology_pack: MethodDocument | None,
) -> list[MethodDocument]:
    """Documentos de uma categoria, respeitando o limite e a dependência do TP."""
    if category == "TP":
        return [technology_pack] if technology_pack is not None else []
    if category == "RI":
        reference = _select_reference_implementation(documents)
        return [reference] if reference is not None else []
    if category == "TS":
        # TS só entra se o TP selecionado os referencia (spec F5 §5.2).
        if technology_pack is None:
            return []
        return [
            doc
            for doc in documents
            if doc.category == "TS" and doc.doc_id in technology_pack.content
        ][:limit]
    return [doc for doc in documents if doc.category == category][:limit]


def _select_technology_pack(
    documents: Sequence[MethodDocument],
    br_content: str | None,
) -> MethodDocument | None:
    """TP: o declarado na BR de origem, senão o único do corpus, senão o menor id."""
    packs = [doc for doc in documents if doc.category == "TP"]
    if not packs:
        return None
    if br_content:
        declared = parse_frontmatter(br_content).get("technologyPack")
        if declared:
            for doc in packs:
                if doc.doc_id == str(declared):
                    return doc
    if len(packs) == 1:
        return packs[0]
    return sorted(packs, key=lambda doc: doc.doc_id)[0]


def _select_reference_implementation(documents: Sequence[MethodDocument]) -> MethodDocument | None:
    """RI: o mais específico por título, senão `RI-001` (META-001 §9)."""
    references = [doc for doc in documents if doc.category == "RI"]
    if not references:
        return None
    for doc in references:
        if doc.doc_id == "RI-001":
            return doc
    return sorted(references, key=lambda doc: doc.doc_id)[0]


def _br_id_of(br_content: str) -> str:
    """Id da BR de origem a partir do frontmatter do markdown."""
    return str(parse_frontmatter(br_content).get("id") or "BR")


async def resolve_repo_context(repo_id: str, query: str, *, top: int = 5) -> RepoContext:
    """Top-k BM25 do corpus do repo (F7). Sem F7, degrada — a geração continua.

    O corpus nunca cruza corpora (Contrato Comum §7.6): `corpus_id = "repo:<uuid>"`.
    """
    corpus_id = f"repo:{repo_id}"
    try:
        from app.services.retriever import search  # F7
    except ImportError:
        return RepoContext(
            corpus_id=None,
            hits=(),
            degraded=True,
            degraded_reason="F7 pendente: corpus do repo indisponível",
        )
    try:
        hits = await search(query, corpus_id, top=top)
    except Exception as exc:
        return RepoContext(
            corpus_id=None,
            hits=(),
            degraded=True,
            degraded_reason=f"F7 indisponível: {exc}",
        )
    return RepoContext(
        corpus_id=corpus_id,
        hits=tuple((str(hit.heading), str(hit.text)) for hit in hits),
        degraded=False,
        degraded_reason=None,
    )
