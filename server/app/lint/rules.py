"""Regras canônicas do linter de artefatos — fase F2.

Cada regra é uma função pura: recebe um ``ArtifactDoc`` e devolve ``Finding``.
Regras que precisam de contexto do lote (cobertura de AC, grafo de SPECs) leem o
``LintContext`` corrente, publicado pelo runner (``app.lint.runner``).

Regras (design master §11.1, spec F2 §4):
BR-001..BR-004, SPEC-001..SPEC-004, PATH-001, PATH-002, LINK-001.
"""

from __future__ import annotations

import re
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Iterator

if TYPE_CHECKING:  # pragma: no cover - apenas para tipagem
    from .runner import ArtifactDoc, LinkUniverse

__all__ = [
    "Finding",
    "Rule",
    "LintContext",
    "RULES",
    "BR_FIELDS",
    "SPEC_FIELDS",
    "BR_SECTIONS",
    "SPEC_SECTIONS",
    "ARTIFACT_STATUSES",
]


# --------------------------------------------------------------------------- #
# Contrato (contrato comum §7.2)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Finding:
    """Uma violação encontrada num artefato."""

    rule: str
    severity: str
    message: str
    path: str | None = None
    line: int | None = None
    detail: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Rule:
    """Uma regra do linter: id, severidade e a função que a aplica."""

    id: str
    severity: str
    check: Callable[["ArtifactDoc"], list[Finding]]


@dataclass
class LintContext:
    """Contexto publicado pelo runner durante a execução das regras."""

    doc: "ArtifactDoc"
    universe: "LinkUniverse"
    docs: list["ArtifactDoc"]


_CONTEXT: ContextVar[LintContext | None] = ContextVar("sdd_lint_context", default=None)


def current_context() -> LintContext | None:
    """Contexto do lint em execução (``None`` fora de um lint)."""
    return _CONTEXT.get()


@contextmanager
def lint_context(
    doc: "ArtifactDoc", universe: "LinkUniverse", docs: list["ArtifactDoc"]
) -> Iterator[LintContext]:
    """Publica o contexto do lint enquanto as regras rodam."""
    context = LintContext(doc=doc, universe=universe, docs=docs)
    token = _CONTEXT.set(context)
    try:
        yield context
    finally:
        _CONTEXT.reset(token)


# --------------------------------------------------------------------------- #
# Constantes do padrão Blueprint
# --------------------------------------------------------------------------- #

# SK-001 §16
BR_FIELDS = (
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
)

# SK-002 §15
SPEC_FIELDS = (
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
    "timestamp",
    "doubtsIndex",
    "version",
)

# SK-001 §14 — "Open Questions" é opcional: só entra na lista se for exigida.
BR_SECTIONS = (
    "Objetivo",
    "Contexto",
    "Atores",
    "Capacidades",
    "Regras de Negócio",
    "Restrições",
    "Exceções",
    "Acceptance Criteria",
)

# SK-002 §10
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

# Ciclo de vida do artefato (design master §9.2)
ARTIFACT_STATUSES = (
    "draft",
    "pending",
    "on user review",
    "on agents review",
    "approved",
    "stable",
)

DOUBTS_DIR = {
    "br": "docs/implementation-artifacts/duvidas-br/",
    "spec": "docs/implementation-artifacts/duvidas-spec/",
}

_KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_WIKI_LINK = re.compile(r"\[\[([^\]]+)\]\]")
_AC = re.compile(r"\bAC-\d{3}\b")
_AC_LOOSE = re.compile(r"\bAC-\d+\b")
_AC_ID = re.compile(r"^AC-\d{3}$")
_DOC_REF = re.compile(r"\b[A-Z]{2,4}-\d{3}\b")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def normalize(text: str) -> str:
    """minúsculas, sem acentos, sem pontuação, espaços colapsados."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^0-9a-zA-Z]+", " ", text.lower())
    return " ".join(text.split())


def _strip_numbering(title: str) -> str:
    """Remove prefixo numérico de heading ('13. Objetivo' -> 'Objetivo')."""
    return re.sub(r"^\d+(?:[.)]\d+)*[.)]?\s*", "", title).strip()


def _heading_lines(body: str) -> list[tuple[int, int, str]]:
    """(índice da linha, nível, título normalizado) dos headings do body.

    Blocos de código cercados por ``` ou ~~~ são ignorados: um ``#`` dentro de
    um diagrama não é uma seção.
    """
    headings: list[tuple[int, int, str]] = []
    fence: str | None = None
    for index, line in enumerate(body.splitlines()):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            marker = stripped[:3]
            fence = None if fence == marker else (fence or marker)
            continue
        if fence is not None:
            continue
        match = _HEADING.match(line)
        if match:
            title = normalize(_strip_numbering(match.group(2)))
            headings.append((index, len(match.group(1)), title))
    return headings


def section_text(body: str, canonical: str) -> str | None:
    """Texto da seção ``canonical`` (match por normalização) ou ``None``."""
    target = normalize(canonical)
    lines = body.splitlines()
    level: int | None = None
    start = 0
    for index, current_level, title in _heading_lines(body):
        if level is None:
            if title == target:
                level = current_level
                start = index + 1
            continue
        if current_level <= level:
            return "\n".join(lines[start:index])
    if level is None:
        return None
    return "\n".join(lines[start:])


def has_section(body: str, canonical: str) -> bool:
    return section_text(body, canonical) is not None


def fm_str(frontmatter: dict, key: str) -> str | None:
    """Valor do frontmatter como string (aceita lista com um item)."""
    value = frontmatter.get(key)
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
        if value is None:
            return None
    if isinstance(value, (str, int, float)):
        text = str(value).strip()
        return text or None
    return None


def fm_list(frontmatter: dict, key: str) -> list[str]:
    """Valor do frontmatter como lista de strings."""
    value = frontmatter.get(key)
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def has_field(frontmatter: dict, key: str) -> bool:
    """Campo presente e não vazio."""
    if key not in frontmatter:
        return False
    value = frontmatter[key]
    if value is None:
        return False
    if isinstance(value, (list, tuple, set)):
        return len(value) > 0
    return bool(str(value).strip())


def ac_ids(text: str) -> list[str]:
    """IDs de AC válidos (``AC-001``) na ordem em que aparecem, com repetições."""
    return [match.group(0) for match in _AC.finditer(text)]


def malformed_ac_ids(text: str) -> list[str]:
    """IDs de AC com formato inválido (``AC-3``, ``AC-3000``)."""
    bad: list[str] = []
    for match in _AC_LOOSE.finditer(text):
        token = match.group(0)
        if not _AC_ID.match(token) and token not in bad:
            bad.append(token)
    return bad


def doc_refs(text: str) -> list[str]:
    """Referências do tipo ``META-000``, ``PAT-001``, ``TP-001``."""
    seen: list[str] = []
    for match in _DOC_REF.finditer(text):
        token = match.group(0)
        if token not in seen:
            seen.append(token)
    return seen


def _line_of(doc: "ArtifactDoc", needle: str) -> int | None:
    """Linha (1-based) da primeira ocorrência de ``needle`` no arquivo."""
    index = doc.content.find(needle)
    if index < 0:
        return None
    return doc.content[:index].count("\n") + 1


def _finding(
    rule: str,
    severity: str,
    message: str,
    doc: "ArtifactDoc",
    detail: dict | None = None,
    line: int | None = None,
) -> Finding:
    return Finding(
        rule=rule,
        severity=severity,
        message=message,
        path=doc.path,
        line=line,
        detail=detail or {},
    )


def _has_frontmatter_block(doc: "ArtifactDoc") -> bool:
    return doc.content.lstrip("﻿").lstrip().startswith("---")


def _batch_of(kind: str) -> list["ArtifactDoc"]:
    context = current_context()
    if context is None:
        return []
    return [doc for doc in context.docs if doc.kind == kind]


def _id_of(doc: "ArtifactDoc") -> str | None:
    return fm_str(doc.frontmatter, "id")


# --------------------------------------------------------------------------- #
# BR-001 / SPEC-001 — frontmatter completo
# --------------------------------------------------------------------------- #


def _check_required_fields(
    doc: "ArtifactDoc", rule: str, required: tuple[str, ...]
) -> list[Finding]:
    if not _has_frontmatter_block(doc) or not doc.frontmatter:
        return [
            _finding(
                rule,
                "error",
                "frontmatter ausente",
                doc,
                detail={"missing": list(required)},
            )
        ]
    findings: list[Finding] = []
    for name in required:
        if not has_field(doc.frontmatter, name):
            findings.append(
                _finding(
                    rule,
                    "error",
                    f"frontmatter sem o campo obrigatório '{name}'",
                    doc,
                    detail={"missing": name},
                )
            )
    return findings


def check_br001(doc: "ArtifactDoc") -> list[Finding]:
    if doc.kind != "br":
        return []
    return _check_required_fields(doc, "BR-001", BR_FIELDS)


def check_spec001(doc: "ArtifactDoc") -> list[Finding]:
    if doc.kind != "spec":
        return []
    return _check_required_fields(doc, "SPEC-001", SPEC_FIELDS)


# --------------------------------------------------------------------------- #
# BR-002 — status no ciclo de vida
# --------------------------------------------------------------------------- #


def check_br002(doc: "ArtifactDoc") -> list[Finding]:
    if doc.kind not in ("br", "spec"):
        return []
    status = fm_str(doc.frontmatter, "status")
    if status is None:
        return []  # campo ausente é reportado por BR-001 / SPEC-001
    if status not in ARTIFACT_STATUSES:
        return [
            _finding(
                "BR-002",
                "error",
                f"status '{status}' fora do ciclo de vida do artefato",
                doc,
                detail={"status": status, "allowed": list(ARTIFACT_STATUSES)},
            )
        ]
    return []


# --------------------------------------------------------------------------- #
# BR-003 / SPEC-002 — seções obrigatórias
# --------------------------------------------------------------------------- #


def _check_sections(
    doc: "ArtifactDoc", rule: str, required: tuple[str, ...]
) -> list[Finding]:
    findings: list[Finding] = []
    for name in required:
        if not has_section(doc.body, name):
            findings.append(
                _finding(
                    rule,
                    "error",
                    f"seção obrigatória ausente: {name}",
                    doc,
                    detail={"missing": name},
                )
            )
    return findings


def check_br003(doc: "ArtifactDoc") -> list[Finding]:
    if doc.kind != "br":
        return []
    return _check_sections(doc, "BR-003", BR_SECTIONS)


def check_spec002(doc: "ArtifactDoc") -> list[Finding]:
    if doc.kind != "spec":
        return []
    return _check_sections(doc, "SPEC-002", SPEC_SECTIONS)


# --------------------------------------------------------------------------- #
# BR-004 — ACs: formato, unicidade, cobertura e AC citado que não existe
# --------------------------------------------------------------------------- #


def _declared_acs(spec: "ArtifactDoc") -> list[str]:
    """ACs que uma SPEC declara: seção 'Acceptance Criteria atendidos' e/ou
    frontmatter ``acceptanceCriteria``."""
    declared: list[str] = []
    section = section_text(spec.body, "Acceptance Criteria atendidos")
    if section:
        declared.extend(ac_ids(section))
    for value in fm_list(spec.frontmatter, "acceptanceCriteria"):
        declared.extend(ac_ids(value))
    seen: list[str] = []
    for token in declared:
        if token not in seen:
            seen.append(token)
    return seen


def _specs_for_br(br_id: str) -> list["ArtifactDoc"]:
    """SPECs do lote que derivam da BR informada."""
    result: list["ArtifactDoc"] = []
    for spec in _batch_of("spec"):
        if fm_str(spec.frontmatter, "createdFrom") == br_id:
            result.append(spec)
        elif br_id and br_id in doc_refs(spec.body):
            result.append(spec)
    return result


def check_br004(doc: "ArtifactDoc") -> list[Finding]:
    """BR-004 tem dois lados: ACs da BR e AC que a SPEC cita sem existir na BR."""
    if doc.kind == "br":
        return _check_br_acs(doc)
    if doc.kind == "spec":
        return _check_spec_acs(doc)
    return []


def _check_br_acs(doc: "ArtifactDoc") -> list[Finding]:
    findings: list[Finding] = []

    occurrences = ac_ids(doc.body)
    counts: dict[str, int] = {}
    for token in occurrences:
        counts[token] = counts.get(token, 0) + 1
    for token, total in counts.items():
        if total > 1:
            findings.append(
                _finding(
                    "BR-004",
                    "error",
                    f"Acceptance Criteria duplicada: {token} ({total} ocorrências)",
                    doc,
                    detail={"duplicate": token},
                    line=_line_of(doc, token),
                )
            )

    for token in malformed_ac_ids(doc.body):
        findings.append(
            _finding(
                "BR-004",
                "error",
                f"Acceptance Criteria com formato inválido: {token}",
                doc,
                detail={"malformed": token},
                line=_line_of(doc, token),
            )
        )

    br_id = _id_of(doc)
    specs = _specs_for_br(br_id) if br_id else []
    if specs:
        covered: set[str] = set()
        for spec in specs:
            covered.update(_declared_acs(spec))
        for token in dict.fromkeys(occurrences):
            if token not in covered:
                findings.append(
                    _finding(
                        "BR-004",
                        "error",
                        f"Acceptance Criteria sem cobertura em SPEC: {token}",
                        doc,
                        detail={"uncovered": token},
                    )
                )
    return findings


def _check_spec_acs(doc: "ArtifactDoc") -> list[Finding]:
    br_id = fm_str(doc.frontmatter, "createdFrom")
    if not br_id:
        return []
    br = next((item for item in _batch_of("br") if _id_of(item) == br_id), None)
    if br is None:
        return []
    known = set(ac_ids(br.body))
    findings: list[Finding] = []
    for token in _declared_acs(doc):
        if token not in known:
            findings.append(
                _finding(
                    "BR-004",
                    "error",
                    f"SPEC cita Acceptance Criteria inexistente na BR: {token}",
                    doc,
                    detail={"unknown_ac": token, "spec": _id_of(doc) or ""},
                )
            )
    return findings


# --------------------------------------------------------------------------- #
# SPEC-003 — createdFrom aponta pra BR existente
# --------------------------------------------------------------------------- #


def check_spec003(doc: "ArtifactDoc") -> list[Finding]:
    if doc.kind != "spec":
        return []
    created_from = fm_str(doc.frontmatter, "createdFrom")
    if not created_from:
        return []  # campo ausente é reportado por SPEC-001
    context = current_context()
    if context is None:
        return []

    br = next((item for item in _batch_of("br") if _id_of(item) == created_from), None)
    if br is not None:
        return []
    if context.universe.resolve(created_from) is not None:
        return []
    return [
        _finding(
            "SPEC-003",
            "error",
            f"createdFrom aponta para uma BR inexistente: {created_from}",
            doc,
            detail={"createdFrom": created_from},
        )
    ]


# --------------------------------------------------------------------------- #
# SPEC-004 — grafo de dependências
# --------------------------------------------------------------------------- #


def _declared_dependencies(spec: "ArtifactDoc") -> list[str]:
    """SPECs de que a SPEC depende (frontmatter ``dependsOn``/``depends_on`` e
    seção 'Dependências')."""
    deps: list[str] = []
    for key in ("dependsOn", "depends_on"):
        for value in fm_list(spec.frontmatter, key):
            deps.extend(doc_refs(value))
    section = section_text(spec.body, "Dependências")
    if section:
        deps.extend(doc_refs(section))
    seen: list[str] = []
    for token in deps:
        if token.startswith("SPEC-") and token not in seen:
            seen.append(token)
    return seen


def check_spec004(doc: "ArtifactDoc") -> list[Finding]:
    if doc.kind != "spec":
        return []
    context = current_context()
    if context is None:
        return []
    findings: list[Finding] = []

    for target in _declared_dependencies(doc):
        if any(_id_of(item) == target for item in _batch_of("spec")):
            continue
        if context.universe.resolve(target) is not None:
            continue
        findings.append(
            _finding(
                "SPEC-004",
                "error",
                f"dependência inexistente: {target}",
                doc,
                detail={"missing": target},
            )
        )

    specs = [spec for spec in _batch_of("spec") if _id_of(spec)]
    ids = {_id_of(spec) for spec in specs}
    graph = {
        _id_of(spec): [
            dep for dep in _declared_dependencies(spec) if dep in ids
        ]
        for spec in specs
    }
    cycle = _find_cycle(_id_of(doc), graph)
    if cycle:
        findings.append(
            _finding(
                "SPEC-004",
                "error",
                "ciclo de dependências entre SPECs: " + " -> ".join(cycle),
                doc,
                detail={"cycle": cycle},
            )
        )
    return findings


def _find_cycle(start: str | None, graph: dict[str, list[str]]) -> list[str]:
    """DFS com pilha de visiting; devolve o ciclo encontrado (lista de ids).

    O ciclo é reportado uma vez por nó, na ordem da travessia — o nó de
    partida não é repetido no fim (``["SPEC-010", "SPEC-011"]``).
    """
    if not start or start not in graph:
        return []
    stack: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def walk(node: str) -> list[str]:
        if node in visiting:
            return stack[stack.index(node) :]
        if node in visited:
            return []
        visiting.add(node)
        stack.append(node)
        for neighbour in graph.get(node, []):
            found = walk(neighbour)
            if found:
                return found
        stack.pop()
        visiting.discard(node)
        visited.add(node)
        return []

    return walk(start)


# --------------------------------------------------------------------------- #
# PATH-001 — path canônico
# --------------------------------------------------------------------------- #


def check_path001(doc: "ArtifactDoc") -> list[Finding]:
    path = doc.path.replace("\\", "/").strip()
    problems: list[str] = []
    parts = path.split("/")
    if not (path.startswith("docs/BR/") or path.startswith("docs/SPEC/")):
        problems.append("path fora de docs/BR/<modulo>/ ou docs/SPEC/<modulo>/")
    else:
        module = parts[2] if len(parts) > 2 else ""
        if not _KEBAB.match(module):
            problems.append(f"modulo '{module}' fora de kebab-case")
        name = parts[-1]
        if not name.endswith(".md"):
            problems.append("arquivo sem extensao .md")
        elif not _KEBAB.match(name[:-3]):
            problems.append(f"nome de arquivo '{name}' fora de kebab-case")
    if not problems:
        return []
    return [
        _finding(
            "PATH-001",
            "error",
            "path fora do padrão do workspace: " + "; ".join(problems),
            doc,
            detail={"path": path, "problems": problems},
        )
    ]


# --------------------------------------------------------------------------- #
# PATH-002 — doubtsIndex aponta pra arquivo existente
# --------------------------------------------------------------------------- #


def check_path002(doc: "ArtifactDoc") -> list[Finding]:
    context = current_context()
    if context is None:
        return []
    doubts_index = fm_str(doc.frontmatter, "doubtsIndex")
    if not doubts_index:
        return []  # campo ausente é reportado por BR-001 / SPEC-001

    path = doubts_index.replace("\\", "/").strip()
    expected_dir = DOUBTS_DIR.get(doc.kind or "")
    problems: list[str] = []
    if expected_dir and not path.startswith(expected_dir):
        problems.append(f"esperado em {expected_dir}")
    if not path.startswith("docs/implementation-artifacts/"):
        problems.append("esperado em docs/implementation-artifacts/")
    if not problems and not context.universe.exists(path):
        problems.append("arquivo de duvidas inexistente")
    if not problems:
        return []
    return [
        _finding(
            "PATH-002",
            "error",
            "doubtsIndex inválido: " + "; ".join(problems),
            doc,
            detail={"doubtsIndex": path, "problems": problems},
        )
    ]


# --------------------------------------------------------------------------- #
# LINK-001 — todo link resolve
# --------------------------------------------------------------------------- #


def _refs_of(doc: "ArtifactDoc") -> list[tuple[str, str, int | None]]:
    """(ref, origem, linha) de todos os links declarados no artefato."""
    refs: list[tuple[str, str, int | None]] = []

    for match in _WIKI_LINK.finditer(doc.body):
        raw = match.group(1).split("|")[0].strip()
        if raw:
            refs.append((raw, "wiki-link", _line_of(doc, raw)))

    created_from = fm_str(doc.frontmatter, "createdFrom")
    if created_from:
        refs.append((created_from, "createdFrom", None))

    technology_pack = fm_str(doc.frontmatter, "technologyPack")
    if technology_pack:
        refs.append((technology_pack, "technologyPack", None))

    for key in ("dependsOn", "depends_on"):
        for value in fm_list(doc.frontmatter, key):
            for token in doc_refs(value):
                refs.append((token, key, None))

    section = section_text(doc.body, "Blueprint Documents necessários")
    if section:
        for token in doc_refs(section):
            refs.append((token, "blueprint-documents", None))

    doubts_index = fm_str(doc.frontmatter, "doubtsIndex")
    if doubts_index:
        refs.append((doubts_index.replace("\\", "/").strip(), "doubtsIndex", None))

    return refs


def check_link001(doc: "ArtifactDoc") -> list[Finding]:
    context = current_context()
    if context is None:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for ref, source, line in _refs_of(doc):
        key = (ref, source)
        if key in seen:
            continue
        seen.add(key)
        if context.universe.resolve(ref) is not None:
            continue
        findings.append(
            _finding(
                "LINK-001",
                "error",
                f"link quebrado: {ref}",
                doc,
                detail={"ref": ref, "source": source},
                line=line,
            )
        )
    return findings


# --------------------------------------------------------------------------- #
# Registro de regras
# --------------------------------------------------------------------------- #

RULES: tuple[Rule, ...] = (
    Rule(id="BR-001", severity="error", check=check_br001),
    Rule(id="BR-002", severity="error", check=check_br002),
    Rule(id="BR-003", severity="error", check=check_br003),
    Rule(id="BR-004", severity="error", check=check_br004),
    Rule(id="SPEC-001", severity="error", check=check_spec001),
    Rule(id="SPEC-002", severity="error", check=check_spec002),
    Rule(id="SPEC-003", severity="error", check=check_spec003),
    Rule(id="SPEC-004", severity="error", check=check_spec004),
    Rule(id="PATH-001", severity="error", check=check_path001),
    Rule(id="PATH-002", severity="error", check=check_path002),
    Rule(id="LINK-001", severity="error", check=check_link001),
)
