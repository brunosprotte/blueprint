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
from dataclasses import asdict, dataclass, field, is_dataclass
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


# --------------------------------------------------------------------------- #
# Geração
# --------------------------------------------------------------------------- #


async def generate_br(demand: "Demand", ctx: GenerationContext) -> dict[str, Any]:
    """Gera a BR da demanda — Contrato Comum §7.3.

    Devolve o `GeneratedArtifact` (6 campos). O relatório completo (arquivo de
    dúvidas, uso de tokens) está em :func:`generate_br_report`.
    """
    report = await generate_br_report(demand, ctx)
    return report.artifacts[0]


async def generate_specs(br: "Artifact", ctx: GenerationContext) -> tuple[dict[str, Any], ...]:
    """Gera as SPECs da BR — Contrato Comum §7.3.

    Devolve a tupla de `GeneratedArtifact`. O relatório completo (arquivos de
    dúvidas, grafo, uso de tokens) está em :func:`generate_specs_report`.
    """
    report = await generate_specs_report(br, ctx)
    return report.artifacts


async def generate_br_report(demand: "Demand", ctx: GenerationContext) -> GenerationReport:
    """Executa SK-001 e persiste a BR, as dúvidas e o evento de geração.

    Idempotente por default (D4): se a demanda já tem BR, devolve a existente sem
    chamar o modelo e sem escrever nada.
    """
    data = _as_mapping(demand)
    demand_id = str(data.get("id") or "")
    status = str(data.get("status") or "open")
    if status in TERMINAL_DEMAND_STATUSES:
        raise IllegalDemandState(status, "generate-br")

    existing = await _find_artifact(ctx.pool, demand_id, "br")
    if existing is not None:
        return await _report_from_rows(ctx, [existing], created=False, idempotent=True)

    client = ctx.client or build_client()
    user_prompt = build_br_user_prompt(
        title=str(data.get("title") or ""),
        body=str(data.get("body") or ""),
        method_context=ctx.method_context,
        repo_context=ctx.repo_context,
    )
    try:
        payload, usage = await _call_model(
            client,
            schema=BR_SCHEMA,
            system=BR_SYSTEM_PROMPT,
            user=user_prompt,
            stage="br",
        )
    except LLMUnavailable as exc:
        await _reset_demand(ctx.pool, demand_id, stage="br", error=exc)
        raise

    front = payload.get("frontmatter")
    front = front if isinstance(front, Mapping) else {}
    module = str(front.get("module") or "")
    feature = str(front.get("feature") or "")
    if not SLUG_RE.match(module) or not SLUG_RE.match(feature):
        error = InvalidArtifactPath(module, feature)
        await _reset_demand(ctx.pool, demand_id, stage="br", error=error)
        raise error

    artifact_body = str(payload.get("body") or "")
    questions = extract_open_questions(artifact_body)

    async with ctx.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext('sdd.artifact_id'))")
            artifact_id = await _next_artifact_id(conn, "br", "BR")
            doubts_path = f"docs/implementation-artifacts/duvidas-br/{artifact_id}.md"
            frontmatter = {
                "id": artifact_id,
                "module": module,
                "feature": feature,
                "type": "Business Rule",
                "title": str(front.get("title") or ""),
                "description": str(front.get("description") or ""),
                "status": "draft",
                "tags": [str(tag) for tag in (front.get("tags") or [])],
                "timestamp": _now_iso(),
                "doubtsIndex": doubts_path,
                "version": "1.0.0",
                "generatedBy": "SK-001",
            }
            content = render_document(frontmatter, artifact_body)
            sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
            path = f"docs/BR/{module}/{feature}.md"
            await conn.execute(
                "INSERT INTO artifacts (id, demand_id, repo_id, kind, module, feature, path, sha,"
                " status, version, content) VALUES ($1,$2,$3,'br',$4,$5,$6,$7,'draft',$8,$9)",
                artifact_id,
                demand_id,
                ctx.repo_id or None,
                module,
                feature,
                path,
                sha,
                "1.0.0",
                content,
            )
            for question in questions:
                await conn.execute(
                    "INSERT INTO doubts (artifact_id, question, status, source)"
                    " VALUES ($1,$2,'pending','user')",
                    artifact_id,
                    question,
                )
            await _insert_generated_event(
                conn,
                demand_id=demand_id,
                artifact_id=artifact_id,
                kind="br",
                path=path,
                sha=sha,
                module=module,
                feature=feature,
                ctx=ctx,
            )

    row = await _fetch_artifact(ctx.pool, artifact_id)
    return await _report_from_rows(ctx, [row], created=True, usage=usage)


async def generate_specs_report(br: "Artifact", ctx: GenerationContext) -> GenerationReport:
    """Executa SK-002 e persiste as SPECs, o grafo, as dúvidas e os eventos.

    Idempotente por default (D4): se a BR já tem SPECs, devolve as existentes sem
    chamar o modelo e sem escrever nada.
    """
    data = _as_mapping(br)
    br_id = str(data.get("id") or "")
    br_content = str(data.get("content") or "")
    demand_id = str(data.get("demand_id") or ctx.demand_id or "")
    if not br_id:
        raise ValueError("a BR de origem precisa de id")

    existing = await _find_specs_of_br(ctx.pool, br_id, demand_id)
    if existing:
        return await _report_from_rows(ctx, existing, created=False, idempotent=True)

    client = ctx.client or build_client()
    user_prompt = build_spec_user_prompt(
        br_content=br_content,
        acceptance_criteria=extract_acceptance_criteria(br_content),
        method_context=ctx.method_context,
        repo_context=ctx.repo_context,
    )
    try:
        payload, usage = await _call_model(
            client,
            schema=SPEC_SCHEMA,
            system=SPEC_SYSTEM_PROMPT,
            user=user_prompt,
            stage="specs",
        )
    except LLMUnavailable as exc:
        await _reset_demand(ctx.pool, demand_id, stage="specs", error=exc)
        raise

    specs = payload.get("specs")
    specs = list(specs) if isinstance(specs, list) else []
    if not specs:
        error = LLMUnavailable("o modelo não devolveu nenhuma SPEC", stage="specs")
        await _reset_demand(ctx.pool, demand_id, stage="specs", error=error)
        raise error

    for spec in specs:
        feature = str((spec or {}).get("feature") or "")
        if not SLUG_RE.match(feature):
            error = InvalidArtifactPath(str(ctx.module), feature)
            await _reset_demand(ctx.pool, demand_id, stage="specs", error=error)
            raise error

    br_front = parse_frontmatter(br_content)
    module = str(br_front.get("module") or ctx.module or "")
    technology_pack = ctx.method_context.technology_pack or "TP-001"

    async with ctx.pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext('sdd.artifact_id'))")
            number = await _next_artifact_number(conn, "spec", "SPEC")
            ids = [f"SPEC-{number + index:03d}" for index in range(len(specs))]
            feature_to_id = {
                str(spec.get("feature") or ""): ids[index] for index, spec in enumerate(specs)
            }

            for spec, artifact_id in zip(specs, ids):
                feature = str(spec.get("feature") or "")
                complexity = str(spec.get("complexity") or "MEDIUM")
                tags = [str(tag) for tag in (spec.get("tags") or [])]
                complexity_tag = f"complexity:{complexity}"
                if complexity_tag not in tags:
                    tags.append(complexity_tag)
                doubts_path = f"docs/implementation-artifacts/duvidas-spec/{artifact_id}.md"
                frontmatter = {
                    "id": artifact_id,
                    "module": module,
                    "feature": feature,
                    "type": "Functional Specification",
                    "title": str(spec.get("title") or ""),
                    "description": str(spec.get("description") or ""),
                    "createdBy": "SK-002",
                    "createdFrom": br_id,
                    "technologyPack": technology_pack,
                    "status": "draft",
                    "tags": tags,
                    "complexity": complexity,
                    "timestamp": _now_iso(),
                    "doubtsIndex": doubts_path,
                    "version": "1.0.0",
                }
                content = render_document(frontmatter, str(spec.get("body") or ""))
                sha = hashlib.sha256(content.encode("utf-8")).hexdigest()
                path = f"docs/SPEC/{module}/{feature}.md"
                await conn.execute(
                    "INSERT INTO artifacts (id, demand_id, repo_id, kind, module, feature, path, sha,"
                    " status, version, content) VALUES ($1,$2,$3,'spec',$4,$5,$6,$7,'draft',$8,$9)",
                    artifact_id,
                    demand_id,
                    ctx.repo_id or None,
                    module,
                    feature,
                    path,
                    sha,
                    "1.0.0",
                    content,
                )
                for question in extract_open_questions(str(spec.get("body") or "")):
                    await conn.execute(
                        "INSERT INTO doubts (artifact_id, question, status, source)"
                        " VALUES ($1,$2,'pending','user')",
                        artifact_id,
                        question,
                    )
                # Toda SPEC deriva da BR de origem (spec F5 §5.6).
                await conn.execute(
                    "INSERT INTO spec_edges (parent_id, child_id, type) VALUES ($1,$2,'derives_from')"
                    " ON CONFLICT DO NOTHING",
                    artifact_id,
                    br_id,
                )
                await _insert_generated_event(
                    conn,
                    demand_id=demand_id,
                    artifact_id=artifact_id,
                    kind="spec",
                    path=path,
                    sha=sha,
                    module=module,
                    feature=feature,
                    ctx=ctx,
                )

            await _insert_spec_edges(
                conn,
                edges=payload.get("edges") or [],
                feature_to_id=feature_to_id,
                demand_id=demand_id,
            )

    rows = await _find_specs_of_br(ctx.pool, br_id, demand_id)
    return await _report_from_rows(ctx, rows, created=True, usage=usage)


async def _insert_spec_edges(
    conn: Any,
    *,
    edges: Sequence[Any],
    feature_to_id: Mapping[str, str],
    demand_id: str,
) -> None:
    """Grava as arestas do grafo devolvido pelo modelo (spec F5 §5.6).

    Aresta não resolvida **não** é gravada e gera o evento `spec_edge_unresolved`
    (D7): perder uma aresta é recuperável, perder a SPEC inteira não.
    """
    for raw in edges:
        edge = raw if isinstance(raw, Mapping) else {}
        edge_type = str(edge.get("type") or "")
        if edge_type == "derives_from":
            continue  # criada pelo servidor para toda SPEC
        parent_feature = str(edge.get("parentFeature") or "")
        child_feature = str(edge.get("childFeature") or "")
        parent_id = feature_to_id.get(parent_feature)
        child_id = feature_to_id.get(child_feature)
        if parent_id is None:
            parent_id = await _existing_spec_id(conn, parent_feature)
        if child_id is None:
            child_id = await _existing_spec_id(conn, child_feature)
        if parent_id is None or child_id is None:
            await conn.execute(
                "INSERT INTO events (demand_id, type, payload) VALUES ($1,'spec_edge_unresolved',$2::jsonb)",
                demand_id,
                json.dumps(
                    {
                        "parentFeature": parent_feature,
                        "childFeature": child_feature,
                        "type": edge_type,
                        "reason": "not_resolved",
                    }
                ),
            )
            continue
        await conn.execute(
            "INSERT INTO spec_edges (parent_id, child_id, type) VALUES ($1,$2,$3)"
            " ON CONFLICT DO NOTHING",
            parent_id,
            child_id,
            edge_type,
        )


async def _existing_spec_id(conn: Any, value: str) -> str | None:
    """Resolve um valor como id de SPEC já existente no banco."""
    if not value:
        return None
    return await conn.fetchval(
        "SELECT id FROM artifacts WHERE id = $1 AND kind = 'spec'", value
    )


async def _insert_generated_event(
    conn: Any,
    *,
    demand_id: str,
    artifact_id: str,
    kind: str,
    path: str,
    sha: str,
    module: str,
    feature: str,
    ctx: GenerationContext,
) -> None:
    """Registra o evento `artifact_generated` (spec F5 §5.8)."""
    payload = {
        "artifact_id": artifact_id,
        "kind": kind,
        "path": path,
        "sha": sha,
        "module": module,
        "feature": feature,
        "method_docs": [doc.doc_id for doc in ctx.method_context.documents],
        "repo_hits": len(ctx.repo_context.hits),
        "degraded": bool(ctx.method_context.degraded or ctx.repo_context.degraded),
        "degraded_reason": degraded_reason(ctx),
    }
    await conn.execute(
        "INSERT INTO events (demand_id, artifact_id, type, payload, actor)"
        " VALUES ($1,$2,'artifact_generated',$3::jsonb,$4)",
        demand_id,
        artifact_id,
        json.dumps(payload),
        None,
    )


async def _call_model(
    client: Any,
    *,
    schema: Mapping[str, Any],
    system: str,
    user: str,
    stage: str,
) -> tuple[dict[str, Any], dict[str, int]]:
    """Chama o modelo com structured outputs e devolve (payload, usage).

    `stop_reason` é obrigatório antes de ler o conteúdo: `max_tokens` significa
    texto truncado (schema inválido) e `refusal` é recusa — ambos são
    `LLMUnavailable`.
    """
    try:
        async with client.messages.stream(
            model=model_name(),
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={
                "effort": "high",
                "format": {"type": "json_schema", "schema": dict(schema)},
            },
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            final = await stream.get_final_message()
    except LLMUnavailable:
        raise
    except anthropic.AnthropicError as exc:
        raise LLMUnavailable(f"Claude API indisponível: {exc}", stage=stage) from exc
    except Exception as exc:  # timeout, proxy fora, rede
        raise LLMUnavailable(f"Claude API indisponível: {exc}", stage=stage) from exc

    stop_reason = getattr(final, "stop_reason", None)
    if stop_reason == "max_tokens":
        raise LLMUnavailable("resposta truncada (max_tokens)", stage=stage)
    if stop_reason == "refusal":
        details = getattr(final, "stop_details", None)
        category = getattr(details, "category", None) if details is not None else None
        raise LLMUnavailable(
            f"recusa do modelo (categoria={category})", stage=stage, category=category
        )

    text = _first_text(final)
    try:
        payload = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise LLMUnavailable(f"resposta fora do schema: {exc}", stage=stage) from exc
    if not isinstance(payload, dict):
        raise LLMUnavailable("resposta fora do schema", stage=stage)
    return payload, _usage_of(final)


def _first_text(final: Any) -> str:
    """Primeiro bloco de texto da resposta (structured outputs garante JSON válido)."""
    for block in getattr(final, "content", []) or []:
        if getattr(block, "type", None) == "text":
            return str(getattr(block, "text", ""))
    raise LLMUnavailable("resposta sem bloco de texto")


def _usage_of(final: Any) -> dict[str, int]:
    """Tokens consumidos na chamada."""
    usage = getattr(final, "usage", None)
    return {
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
    }


# --------------------------------------------------------------------------- #
# Persistência
# --------------------------------------------------------------------------- #


async def _next_artifact_number(conn: Any, kind: str, prefix: str) -> int:
    """Próximo número sequencial do kind (`BR-013` -> 13).

    Roda dentro do advisory lock de D2: duas gerações concorrentes não pegam o
    mesmo número.
    """
    rows = await conn.fetch(
        "SELECT id FROM artifacts WHERE kind = $1 AND id ~ ('^' || $2 || '-[0-9]{3}$')",
        kind,
        prefix,
    )
    numbers = []
    for row in rows:
        try:
            numbers.append(int(str(row["id"]).split("-", 1)[1]))
        except (IndexError, ValueError):
            continue
    return max(numbers, default=0) + 1


async def _next_artifact_id(conn: Any, kind: str, prefix: str) -> str:
    """Id do próximo artefato do kind — `BR-013`, `SPEC-024`."""
    return f"{prefix}-{await _next_artifact_number(conn, kind, prefix):03d}"


async def _fetch_artifact(pool: Any, artifact_id: str) -> Any:
    """Lê o artefato persistido."""
    return await pool.fetchrow(
        "SELECT id, kind, path, content, status FROM artifacts WHERE id = $1", artifact_id
    )


async def _find_artifact(pool: Any, demand_id: str, kind: str) -> Any | None:
    """Artefato mais recente da demanda no kind dado (caminho idempotente, D4)."""
    return await pool.fetchrow(
        "SELECT id, kind, path, content, status FROM artifacts"
        " WHERE demand_id = $1 AND kind = $2 ORDER BY created_at DESC LIMIT 1",
        demand_id,
        kind,
    )


async def _find_specs_of_br(pool: Any, br_id: str, demand_id: str) -> list[Any]:
    """SPECs já geradas para a BR (o vínculo é o `createdFrom` do frontmatter)."""
    rows = await pool.fetch(
        "SELECT id, kind, path, content, status FROM artifacts"
        " WHERE demand_id = $1 AND kind = 'spec' ORDER BY created_at",
        demand_id,
    )
    return [
        row
        for row in rows
        if str(parse_frontmatter(row["content"] or "").get("createdFrom") or "") == br_id
    ]


async def _report_from_rows(
    ctx: GenerationContext,
    rows: Sequence[Any],
    *,
    created: bool,
    idempotent: bool = False,
    usage: Mapping[str, int] | None = None,
) -> GenerationReport:
    """Monta o relatório da rota a partir dos artefatos persistidos."""
    artifacts: list[dict[str, Any]] = []
    doubts_files: list[DoubtsFile] = []
    edges: dict[tuple[str, str, str], SpecEdge] = {}

    for row in rows:
        content = row["content"] or ""
        front = parse_frontmatter(content)
        doubts_path = str(front.get("doubtsIndex") or "")
        artifacts.append(
            {
                "id": row["id"],
                "kind": row["kind"],
                "path": row["path"],
                "content": content,
                "frontmatter": front,
                "doubts_index_path": doubts_path,
            }
        )
        doubts = await ctx.pool.fetch(
            "SELECT id, status, source, question, raised_at, resolved_at"
            " FROM doubts WHERE artifact_id = $1 ORDER BY raised_at, id",
            row["id"],
        )
        doubts_files.append(
            DoubtsFile(
                path=doubts_path,
                content=render_doubts_seed(
                    row["id"], _doubts_file_status(row["status"]), doubts
                ),
            )
        )
        for edge in await ctx.pool.fetch(
            "SELECT parent_id, child_id, type FROM spec_edges"
            " WHERE parent_id = $1 OR child_id = $1",
            row["id"],
        ):
            key = (edge["parent_id"], edge["child_id"], edge["type"])
            edges[key] = SpecEdge(*key)

    return GenerationReport(
        artifacts=tuple(artifacts),
        doubts_files=tuple(doubts_files),
        spec_edges=tuple(edges.values()),
        usage=dict(usage or {}),
        context=context_summary(ctx),
        created=created,
        idempotent=idempotent,
    )


def context_summary(ctx: GenerationContext) -> dict[str, Any]:
    """Resumo do contexto usado na geração (vai no payload da rota)."""
    return {
        "method_docs": [doc.doc_id for doc in ctx.method_context.documents],
        "repo_hits": len(ctx.repo_context.hits),
        "repo_corpus_id": ctx.repo_context.corpus_id,
        "degraded": bool(ctx.method_context.degraded or ctx.repo_context.degraded),
        "degraded_reason": degraded_reason(ctx),
    }


def degraded_reason(ctx: GenerationContext) -> str | None:
    """Motivo da degradação — método e repo, quando os dois faltaram."""
    reasons = [
        reason
        for reason in (ctx.repo_context.degraded_reason, ctx.method_context.degraded_reason)
        if reason
    ]
    return "; ".join(reasons) if reasons else None


def _doubts_file_status(artifact_status: str) -> str:
    """Status do arquivo de dúvidas (META-006 §6)."""
    mapping = {
        "draft": "draft",
        "pending": "pending",
        "on user review": "pending",
        "on agents review": "pending",
        "approved": "approved",
        "stable": "approved",
    }
    return mapping.get(artifact_status, "draft")


# --------------------------------------------------------------------------- #
# Erro e reset da demanda
# --------------------------------------------------------------------------- #

_FALLBACK_DEMAND_TRANSITIONS: dict[str, set[str]] = {
    "open": {"claimed", "blocked"},
    "claimed": {"in_progress", "open", "blocked"},
    "in_progress": {"review", "blocked"},
    "review": {"in_progress", "merged", "blocked"},
    "merged": {"done", "blocked"},
    "done": {"blocked"},
    "blocked": {"open"},
}


def can_transition(table: str, current: str, target: str) -> bool:
    """A transição é legal? Usa o lifecycle do F4 quando existe; senão a tabela local."""
    try:
        from app.services.lifecycle import can_transition as lifecycle_can_transition
    except ImportError:
        lifecycle_can_transition = None
    if lifecycle_can_transition is not None:
        try:
            return bool(lifecycle_can_transition(table, current, target))
        except Exception:
            return False
    return target in _FALLBACK_DEMAND_TRANSITIONS.get(current, set())


async def _reset_demand(pool: Any, demand_id: str, *, stage: str, error: Exception) -> bool:
    """Devolve a demanda para `open` quando a transição é legal (spec F5 §5.9).

    `in_progress` **permanece** `in_progress`: `in_progress -> open` não é
    transição legal na tabela §9.1 e o servidor nunca adivinha (invariante 2).
    Registra o evento `generation_failed` em qualquer caso.
    """
    reason = "invalid_artifact_path" if isinstance(error, InvalidArtifactPath) else "llm_unavailable"
    row = await pool.fetchrow("SELECT status FROM demands WHERE id = $1", demand_id)
    current = str(row["status"]) if row is not None else ""
    reset = False

    if current == "claimed" and can_transition("demand", current, "open"):
        async with pool.acquire() as conn:
            async with conn.transaction():
                await _apply_demand_open(conn, demand_id, current)
                reset = True

    await pool.execute(
        "INSERT INTO events (demand_id, type, payload) VALUES ($1,'generation_failed',$2::jsonb)",
        demand_id,
        json.dumps(
            {
                "stage": stage,
                "error_type": type(error).__name__,
                "message": str(error),
                "reason": reason,
                "reset": reset,
            }
        ),
    )
    return reset


async def _apply_demand_open(conn: Any, demand_id: str, current: str) -> None:
    """Aplica `claimed -> open` pelo lifecycle do F4, com fallback local."""
    try:
        from app.services.lifecycle import apply_demand_transition
    except ImportError:
        apply_demand_transition = None
    if apply_demand_transition is not None:
        import inspect

        parameters = inspect.signature(apply_demand_transition).parameters
        if "demand_id" in parameters and "target" in parameters:
            await apply_demand_transition(
                conn, demand_id=demand_id, target="open", actor_id=None
            )
        else:
            await apply_demand_transition(conn, demand_id, "open")
        return
    await conn.execute(
        "UPDATE demands SET status = 'open', updated_at = now() WHERE id = $1 AND status = $2",
        demand_id,
        current,
    )


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

_OPEN_QUESTIONS_RE = re.compile(r"^#{1,6}\s*Open Questions\s*$", re.IGNORECASE | re.MULTILINE)
_AC_RE = re.compile(r"AC-\d{3}")


def extract_open_questions(body: str) -> list[str]:
    """Linhas da seção `Open Questions` do corpo do artefato (META-006 §5)."""
    match = _OPEN_QUESTIONS_RE.search(body or "")
    if not match:
        return []
    questions: list[str] = []
    for line in body[match.end() :].splitlines():
        if line.startswith("#"):
            break
        stripped = line.strip()
        if stripped.startswith(("- ", "* ")):
            question = stripped[2:].strip()
            if question:
                questions.append(question)
    return questions


def extract_acceptance_criteria(content: str) -> list[str]:
    """Ids de AC presentes no markdown da BR (`AC-001`)."""
    seen: list[str] = []
    for ac in _AC_RE.findall(content or ""):
        if ac not in seen:
            seen.append(ac)
    return seen


def _as_mapping(value: Any) -> Mapping[str, Any]:
    """Normaliza Demand/Artifact (dataclass), dict ou asyncpg.Record em mapping."""
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if hasattr(value, "keys"):
        return {key: value[key] for key in value.keys()}
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    raise TypeError(f"não sei ler {type(value)!r}")

