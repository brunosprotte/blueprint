"""Pipeline de aprovação (META-005) — implementado na fase F6.

Ordem **fixa e sequencial** (META-005 "Regra"):

    1. LINTER            (app/lint — Python puro, determinístico, sem LLM)
    2. Blind Hunter      (LLM)
    3. Edge Case Hunter  (LLM)
    4. Acceptance Auditor(LLM)

O linter roda primeiro: artefato com frontmatter quebrado é barrado na hora,
sem gastar token de LLM (design master §12).

Falha de LLM **não bloqueia nada** (design master §19): `verdict="pending"`,
`llm_available=False`, o artefato não é promovido e o commit/push segue.

Contrato: Contrato Comum §7.4. Spec da fase: §5.1–§5.8.
"""

from __future__ import annotations

import importlib
import inspect
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.services.doubts import (
    _insert_doubt,
    as_uuid,
    list_open_doubts,
    publish_artifact_doubts,
    to_iso,
)

__all__ = [
    "FINDINGS_SCHEMA",
    "PipelineResult",
    "REVIEWERS",
    "call_lifecycle_transition",
    "extract_acs",
    "run_pipeline",
]

# --------------------------------------------------------------------------
# LLM (F5) — import tardio: F5 pode ainda não existir
# --------------------------------------------------------------------------

class _LocalLLMUnavailable(RuntimeError):
    """LLM indisponível (fallback local enquanto o F5 não existe)."""


def _llm_unavailable() -> type[Exception]:
    """Classe `LLMUnavailable` do F5 — resolvida **na hora do uso**.

    O import é tardio de propósito: `app.services.generator` só existe depois
    do F5, e o `except` casa por identidade da classe.
    """
    try:
        from app.services.generator import LLMUnavailable

        return LLMUnavailable
    except ImportError:
        return _LocalLLMUnavailable


# --------------------------------------------------------------------------
# Schemas e prompts
# --------------------------------------------------------------------------

#: Schema estrito de saída dos 3 revisores (spec §5.3).
FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {
                        "type": "string",
                        "enum": ["blocking", "suggestion", "deferred"],
                    },
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "ac": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": ["severity", "title", "detail", "ac", "suggestion"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}

SYSTEM_BLIND_HUNTER = """Você é o Blind Hunter. Papel: revisor ciego de artefato Blueprint.
Você recebe apenas o artefato e as regras do método. De propósito você NÃO recebe a BR de
origem, nem o contexto resolvido, nem as ACs: existe para pegar o que o autor não percebeu.
Procure, sem seguir a intenção do autor:
- afirmações que não podem ser verificadas ("rápido", "robusto", "moderno", "seguro", "etc.",
  "e demais");
- placeholders, TODO, FIXME, "a definir", "em breve", "a ser detalhado";
- contradições internas entre duas seções do próprio artefato;
- comportamento implícito sem cenário observável;
- AC sem Given/When/Then ou sem resultado observável;
- seção obrigatória vazia, com placeholder ou com uma frase que não diz nada.
Não sugira implementação, não reescreva o artefato: reporte o que está errado.
Cada achado: {"severity","title","detail","ac","suggestion"}.
severity: "blocking" se o artefato não pode ser implementado ou revisado sem a correção;
"suggestion" se é melhoria real; "deferred" se é melhoria postergável.
ac: id da AC afetada ("AC-003") ou "" se não houver.
Se não houver achado, devolva {"findings": []}."""

SYSTEM_EDGE_CASE_HUNTER = """Você é o Edge Case Hunter. Papel: caçar condições de contorno que o artefato não cobre.
Você recebe o artefato inteiro, as ACs da BR de origem e o conhecimento resolvido do método.
Para cada Acceptance Criteria da BR, derive mentalmente: entrada vazia; valor no limite
e valor fora do limite; entrada duplicada e reenvio; concorrência sobre o mesmo recurso;
requisição sem permissão; falha parcial de dependência externa; dado corrompido ou ausente;
cancelamento no meio do fluxo; operação repetida (idempotência).
Para cada AC, verifique se o artefato define o comportamento nesses casos.
Achado = gap concreto, não genérico: "quando <situação>, o artefato não diz <o que>".
Cada achado: {"severity","title","detail","ac","suggestion"}.
ac é obrigatório: é a AC cujo comportamento ficou indefinido.
Se não houver gap, devolva {"findings": []}."""

SYSTEM_ACCEPTANCE_AUDITOR = """Você é o Acceptance Auditor. Papel: verificar rastreabilidade e cobertura.
Você recebe o artefato inteiro, a BR de origem com todas as Acceptance Criteria e a lista
de SPECs do grafo.
Verifique:
1. Toda AC da BR aparece em "Acceptance Criteria atendidos" de pelo menos uma SPEC. AC sem
   cobertura é achado "blocking".
2. Toda SPEC declara ACs que existem na BR. AC citada que não existe na BR é "blocking".
3. Toda SPEC preenche as 14 seções obrigatórias com conteúdo real, não placeholder.
   Seção vazia ou placeholder é achado "blocking".
4. Toda dependência declarada existe no grafo informado e o grafo não tem ciclo.
5. A "Responsabilidade" da SPEC descreve uma única responsabilidade técnica.
Cada achado: {"severity","title","detail","ac","suggestion"}.
ac é a AC em rastreio; use "" apenas nos achados 3, 4 e 5.
Se a auditoria fechar limpa, devolva {"findings": []}."""


@dataclass(frozen=True)
class _Reviewer:
    """Um dos 3 revisores do META-005 e o contexto que ele recebe."""

    slug: str
    title: str
    system: str
    needs_acs: bool
    needs_context: bool
    needs_specs: bool


#: Ordem fixa — Blind -> Edge -> Acceptance (META-005 "Regra").
REVIEWERS: tuple[_Reviewer, ...] = (
    _Reviewer(
        slug="blind-hunter",
        title="Blind Hunter",
        system=SYSTEM_BLIND_HUNTER,
        needs_acs=False,
        needs_context=False,
        needs_specs=False,
    ),
    _Reviewer(
        slug="edge-case-hunter",
        title="Edge Case Hunter",
        system=SYSTEM_EDGE_CASE_HUNTER,
        needs_acs=True,
        needs_context=True,
        needs_specs=False,
    ),
    _Reviewer(
        slug="acceptance-auditor",
        title="Acceptance Auditor",
        system=SYSTEM_ACCEPTANCE_AUDITOR,
        needs_acs=True,
        needs_context=True,
        needs_specs=True,
    ),
)

#: severidade do achado -> status da pendência (spec D4).
FINDING_SEVERITY_TO_DOUBT_STATUS = {
    "blocking": "pending",
    "suggestion": "deferred",
    "deferred": "deferred",
}

_AC_RE = re.compile(r"\bAC-\d{3}\b")

#: Linha de AC no formato canônico: `- **AC-001** — texto` (SK-001 §16).
_AC_LINE_RE = re.compile(
    r"^\s*[-*]?\s*\**\s*(AC-\d{3})\s*\**\s*[:\-–—]?\s*(.*)$"
)

# --------------------------------------------------------------------------
# SQL
# --------------------------------------------------------------------------

_SQL_ARTIFACT_BY_ID = "SELECT * FROM artifacts WHERE id = $1"

_SQL_SIBLING_SPECS = """
SELECT * FROM artifacts
 WHERE demand_id = $1 AND kind = 'spec' AND id <> $2
 ORDER BY id
"""

_SQL_ARTIFACT_STATUS = "SELECT status FROM artifacts WHERE id = $1"

_SQL_SET_ARTIFACT_APPROVED = """
UPDATE artifacts
   SET status = $2, updated_at = now()
 WHERE id = $1 AND status = 'on agents review'
"""

_SQL_EVENT = """
INSERT INTO events (demand_id, artifact_id, type, payload, actor, at)
VALUES ($1, $2, $3, $4::jsonb, $5, now())
"""


# --------------------------------------------------------------------------
# Resultado
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class PipelineResult:
    """Resultado do pipeline (contrato §7.4 + extras da spec D1)."""

    verdict: str  # clean | suggestions | blocking | pending
    findings: list[dict]
    linter_findings: list[dict]
    doubts_written: int
    llm_available: bool
    review_artifacts: list[dict] = field(default_factory=list)
    stages: list[dict] = field(default_factory=list)
    approval_ready: bool = False
    blocking_reasons: list[str] = field(default_factory=list)
    artifact_status: str = ""

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "findings": list(self.findings),
            "linter_findings": list(self.linter_findings),
            "doubts_written": self.doubts_written,
            "llm_available": self.llm_available,
            "review_artifacts": list(self.review_artifacts),
            "stages": list(self.stages),
            "approval_ready": self.approval_ready,
            "blocking_reasons": list(self.blocking_reasons),
            "artifact_status": self.artifact_status,
        }


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


async def _fetch(query: str, *args: Any) -> list[Any]:
    from app.db import fetch, get_pool

    return await fetch(await get_pool(), query, *args)


async def _fetchrow(query: str, *args: Any) -> Any:
    from app.db import fetchrow, get_pool

    return await fetchrow(await get_pool(), query, *args)


async def _execute(query: str, *args: Any) -> Any:
    from app.db import execute, get_pool

    return await execute(await get_pool(), query, *args)


def _field(row: Any, name: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(name, default)
    value = getattr(row, name, None)
    if value is not None:
        return value
    try:
        return row[name]
    except Exception:
        return default


def _split_frontmatter(content: str) -> tuple[dict, str]:
    """Separa frontmatter YAML e corpo. Sem PyYAML/parse erro -> frontmatter vazio."""
    text = (content or "").replace("\r\n", "\n")
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            raw = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1 :]).lstrip("\n")
            try:
                import yaml

                data = yaml.safe_load(raw) or {}
            except Exception:
                data = {}
            return (data if isinstance(data, dict) else {}), body
    return {}, text


def extract_acs(content: str) -> list[str]:
    """ACs de uma BR, no formato `- **AC-001** — <critério>` (SK-001 §16)."""
    if not content:
        return []
    seen: set[str] = set()
    acs: list[str] = []
    for line in content.replace("\r\n", "\n").split("\n"):
        if not _AC_RE.search(line):
            continue
        match = _AC_LINE_RE.match(line)
        if not match:
            continue
        ac_id, rest = match.group(1), match.group(2).strip()
        if ac_id in seen:
            continue
        seen.add(ac_id)
        acs.append(f"- {ac_id}: {rest}" if rest else f"- {ac_id}")
    return acs


def _finding_question(finding: dict) -> str:
    """Monta o texto da pendência: `"[<ac>] <title> — <detail>"`."""
    ac = (finding.get("ac") or "").strip()
    title = (finding.get("title") or "").strip()
    detail = (finding.get("detail") or "").strip()
    prefix = f"[{ac}] " if ac else ""
    if detail:
        return f"{prefix}{title} — {detail}"
    return f"{prefix}{title}"


def _linter_question(finding: dict) -> str:
    """Pendência de linter: `"[<regra>] <mensagem>"` (mesma convenção da AC)."""
    rule = (finding.get("rule") or "").strip()
    message = (finding.get("message") or "").strip()
    prefix = f"[{rule}] " if rule else ""
    return f"{prefix}{message}"


def _finding_to_dict(finding: Any) -> dict:
    """Serializa um `Finding` do F2 (contrato §7.2)."""
    detail = _field(finding, "detail") or {}
    return {
        "rule": _field(finding, "rule"),
        "severity": _field(finding, "severity"),
        "message": _field(finding, "message"),
        "path": _field(finding, "path"),
        "line": _field(finding, "line"),
        "detail": dict(detail) if isinstance(detail, dict) else {},
    }


def _model() -> str:
    try:
        from app.config import settings

        return settings.llm_model
    except Exception:
        return "claude-opus-5-5"


# --------------------------------------------------------------------------
# Estágio 1 — linter (F2)
# --------------------------------------------------------------------------


def _to_doc(artifact: Any) -> Any:
    from app.lint import ArtifactDoc

    content = _field(artifact, "content") or ""
    frontmatter, body = _split_frontmatter(content)
    return ArtifactDoc(
        path=_field(artifact, "path") or "",
        content=content,
        frontmatter=frontmatter,
        body=body,
        kind=_field(artifact, "kind"),
        repo_id=_field(artifact, "repo_id"),
    )


async def _sibling_docs(artifact: Any) -> list[Any]:
    """SPECs irmãs da mesma demanda — necessárias para a cobertura de AC
    (regra `BR-004` do F2), que accusedaria AC não coberta num lint isolado."""
    demand_id = _field(artifact, "demand_id")
    artifact_id = _field(artifact, "id")
    if not demand_id:
        return []
    rows = await _fetch(_SQL_SIBLING_SPECS, as_uuid(demand_id), artifact_id)
    docs = []
    for row in rows:
        content = _field(row, "content") or ""
        frontmatter, body = _split_frontmatter(content)
        from app.lint import ArtifactDoc

        docs.append(
            ArtifactDoc(
                path=_field(row, "path") or "",
                content=content,
                frontmatter=frontmatter,
                body=body,
                kind=_field(row, "kind"),
                repo_id=_field(row, "repo_id"),
            )
        )
    return docs


async def _run_linter(artifact: Any) -> tuple[list[dict], str | None]:
    """Roda o linter do F2. Devolve (findings, erro).

    O universo é o do **F4** (`build_universe`): corpus do método + artefatos
    sincronizados + **sidecars de dúvidas**. Sem os sidecars, o PATH-002
    reprova todo artefato por `doubtsIndex` inexistente — falso positivo
    (Contrato Comum §8.4 D1/D2).

    Erro aqui é falha determinística e conhecida: `verdict="blocking"`, nenhum
    token de LLM gasto (design master §12).
    """
    try:
        from app.services.artifacts import build_universe
    except ImportError as exc:
        return [], f"indisponível: {exc}"

    try:
        universe = await build_universe(await _pool())
        if universe is None:
            return [], "indisponível: universo de links"
        from app.lint import lint_batch

        docs = [_to_doc(artifact), *await _sibling_docs(artifact)]
        findings = lint_batch(docs, universe)
        return [_finding_to_dict(f) for f in findings], None
    except Exception as exc:  # noqa: BLE001 — linter é local, mas pode estourar
        return [], f"erro interno: {exc}"


async def _pool() -> Any:
    from app.db import get_pool

    return await get_pool()


async def _current_status(artifact_id: str) -> str:
    """Status do artefato **no banco** — o snapshot recebido pode ser velho.

    O F4 transiciona `on user review -> on agents review` antes de chamar o
    pipeline (F4 `approve`); o dicionário que ele passa ainda diz
    `on user review`.
    """
    row = await _fetchrow(_SQL_ARTIFACT_STATUS, artifact_id)
    return _field(row, "status") or ""


# --------------------------------------------------------------------------
# Estágios 2–4 — os 3 revisores (LLM)
# --------------------------------------------------------------------------


def _first_text(final: Any) -> str:
    for block in getattr(final, "content", None) or []:
        if getattr(block, "type", None) == "text":
            return block.text
    raise _llm_unavailable()("resposta do LLM sem bloco de texto")


def _validate_findings(payload: Any) -> list[dict]:
    """Valida o payload contra `FINDINGS_SCHEMA` (schema estrito)."""
    if not isinstance(payload, dict):
        raise _llm_unavailable()("payload fora do schema: esperado objeto JSON")
    findings = payload.get("findings")
    if not isinstance(findings, list):
        raise _llm_unavailable()("payload fora do schema: 'findings' não é lista")
    expected = {"severity", "title", "detail", "ac", "suggestion"}
    validated: list[dict] = []
    for item in findings:
        if not isinstance(item, dict):
            raise _llm_unavailable()("payload fora do schema: achado não é objeto")
        if set(item) != expected:
            raise _llm_unavailable()(
                f"payload fora do schema: chaves {sorted(item)} != {sorted(expected)}"
            )
        if item["severity"] not in FINDING_SEVERITY_TO_DOUBT_STATUS:
            raise _llm_unavailable()(
                f"payload fora do schema: severity {item['severity']!r} fora do enum"
            )
        for key in ("title", "detail", "ac", "suggestion"):
            if not isinstance(item[key], str):
                raise _llm_unavailable()(
                    f"payload fora do schema: {key!r} não é string"
                )
        validated.append({key: item[key] for key in sorted(expected)})
    return validated


async def _call_reviewer(client: Any, system: str, user_prompt: str) -> list[dict]:
    """Uma chamada de Claude API por revisor (streaming, structured output)."""
    async with client.messages.stream(
        model=_model(),
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={
            "effort": "high",
            "format": {"type": "json_schema", "schema": FINDINGS_SCHEMA},
        },
        system=system,
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        final = await stream.get_final_message()

    stop_reason = getattr(final, "stop_reason", None)
    if stop_reason == "max_tokens":
        raise _llm_unavailable()("resposta truncada (max_tokens)")
    if stop_reason == "refusal":
        raise _llm_unavailable()("resposta recusada pelo modelo")

    try:
        payload = json.loads(_first_text(final))
    except json.JSONDecodeError as exc:
        raise _llm_unavailable()(f"resposta não é JSON válido: {exc}") from exc
    return _validate_findings(payload)


async def _method_documents(artifact: Any, kind: str) -> list[Any]:
    """Conhecimento resolvido por META-001 — reusa o F5 (contrato §7.3)."""
    try:
        from app.services.generator import resolve_method_context
    except ImportError:
        return []
    try:
        context = resolve_method_context(
            kind=kind,
            module=_field(artifact, "module") or "",
            feature=_field(artifact, "feature") or "",
        )
        if inspect.isawaitable(context):
            context = await context
    except Exception:  # noqa: BLE001 — contexto é enriquecimento, não requisito
        return []
    return list(getattr(context, "documents", None) or [])


async def _origin_acs(artifact: Any) -> list[str]:
    """ACs da BR de origem: a própria BR, ou a BR apontada por `createdFrom`."""
    kind = _field(artifact, "kind")
    content = _field(artifact, "content") or ""
    if kind == "br":
        return extract_acs(content)
    frontmatter, _ = _split_frontmatter(content)
    br_id = frontmatter.get("createdFrom")
    if not br_id:
        return []
    row = await _fetchrow(_SQL_ARTIFACT_BY_ID, br_id)
    if row is None:
        return []
    return extract_acs(_field(row, "content") or "")


async def _spec_list(artifact: Any) -> list[str]:
    """SPECs do grafo (a lista de que o Acceptance Auditor fala)."""
    rows = await _sibling_rows(artifact)
    return [f"- {_field(r, 'id')}: {_field(r, 'path')}" for r in rows]


async def _sibling_rows(artifact: Any) -> list[Any]:
    demand_id = _field(artifact, "demand_id")
    artifact_id = _field(artifact, "id")
    if not demand_id:
        return []
    return await _fetch(_SQL_SIBLING_SPECS, demand_id, artifact_id)


def _method_context_text(documents: list[Any]) -> str:
    blocks = []
    for doc in documents:
        blocks.append(
            f"## {_field(doc, 'doc_id')} — {_field(doc, 'title')}\n{_field(doc, 'content') or ''}"
        )
    return "\n\n".join(blocks)


def _user_prompt(
    artifact: Any,
    reviewer: _Reviewer,
    acs: list[str],
    documents: list[Any],
    spec_list: list[str],
) -> str:
    """Esqueleto do prompt de usuário (spec §5.3)."""
    sections = [
        "# Artefato sob revisão\n\n" + (_field(artifact, "content") or ""),
    ]
    if reviewer.needs_acs:
        sections.append(
            "# Acceptance Criteria da BR de origem\n\n"
            + ("\n".join(acs) if acs else "(nenhuma AC informada)")
        )
    if reviewer.needs_context:
        context = _method_context_text(documents)
        sections.append(
            "# Conhecimento resolvido (META-001)\n\n"
            + (context if context else "(sem contexto resolvido)")
        )
    if reviewer.needs_specs:
        sections.append(
            "# SPECs do grafo\n\n"
            + ("\n".join(spec_list) if spec_list else "(nenhuma SPEC no grafo)")
        )
    sections.append(
        "Revise o artefato acima e devolva os achados no formato definido."
    )
    return "\n\n".join(sections)


def _review_artifact_path(artifact: Any, reviewer: _Reviewer) -> str:
    """`docs/implementation-artifacts/review-<tema>-<revisor>.md` (META-005)."""
    module = (_field(artifact, "module") or "").strip()
    feature = (_field(artifact, "feature") or "").strip()
    if module and feature:
        theme = f"{module}-{feature}"
    else:
        theme = (module or feature or str(_field(artifact, "id") or "artefato")).lower()
    return (
        f"docs/implementation-artifacts/review-{theme}-{reviewer.slug}.md"
    )


def _render_review_file(
    artifact: Any, reviewer: _Reviewer, findings: list[dict]
) -> str:
    """Arquivo de revisão do revisor (convenção de nome do META-005)."""
    artifact_id = str(_field(artifact, "id"))
    updated_at = to_iso(datetime.now(timezone.utc))
    lines = [
        "---",
        f"id: REVIEW-{artifact_id}-{reviewer.slug.upper()}",
        f"artifactId: {artifact_id}",
        f"reviewer: {reviewer.slug}",
        "status: complete",
        f'updatedAt: "{updated_at}"',
        "---",
        "",
        f"# Revisão — {reviewer.title} — {artifact_id}",
        "",
        f"Artefato: {_field(artifact, 'path') or ''}",
        "",
        f"## Achados ({len(findings)})",
        "",
    ]
    if not findings:
        lines.append("Nenhum achado.")
    for index, finding in enumerate(findings, start=1):
        lines.append(f"### {index}. [{finding.get('severity')}] {finding.get('title')}")
        lines.append("")
        lines.append(f"- **AC**: {finding.get('ac') or '—'}")
        lines.append(f"- **Detalhe**: {finding.get('detail') or '—'}")
        lines.append(f"- **Sugestão**: {finding.get('suggestion') or '—'}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


# --------------------------------------------------------------------------
# Pipeline
# --------------------------------------------------------------------------


async def _publish_event(
    event_type: str,
    payload: dict,
    *,
    demand_id: str | None = None,
    artifact_id: str | None = None,
    actor: str | None = None,
) -> None:
    await _execute(
        _SQL_EVENT,
        as_uuid(demand_id),
        artifact_id,
        event_type,
        json.dumps(payload, ensure_ascii=False),
        as_uuid(actor),
    )


async def _publish_stage(
    artifact: Any,
    stage: dict,
    elapsed_ms: int,
    actor: str | None,
) -> None:
    await _publish_event(
        "pipeline_stage",
        {
            "stage": stage["stage"],
            "ok": stage["ok"],
            "findings": stage["findings"],
            "ms": elapsed_ms,
        },
        demand_id=_field(artifact, "demand_id"),
        artifact_id=_field(artifact, "id"),
        actor=actor,
    )


async def call_lifecycle_transition(
    fn_name: str,
    entity_id: str,
    target: str,
    actor_id: str | None = None,
    *,
    conn: Any | None = None,
) -> bool:
    """Aplica uma transição de status **via `services/lifecycle.py` (F4)**.

    O F4 define
    `apply_artifact_transition(conn, *, artifact_id, target, actor_id, payload)`
    (F4 §3.2) — recebe uma **conexão já dentro de transação**. A spec da F6
    escreve `(pool, artifact_id, target)`. O F6 entrega a conexão quando o pool
    sabe entregar, senão o pool; e só passa os kwargs que a função aceita.

    `conn` (opcional) é a conexão do chamador: a transição entra na transação
    do chamador — nada é gravado em parte.

    Devolve `True` quando a transição foi aplicada, `False` quando o F4 ainda
    não existe. Exceções do F4 (ex.: `IllegalTransition`) propagam.
    """
    try:
        lifecycle = importlib.import_module("app.services.lifecycle")
    except ImportError:
        return False

    fn = getattr(lifecycle, fn_name, None)
    if fn is None:
        return False

    params = inspect.signature(fn).parameters
    kwargs: dict[str, Any] = {"target": target, "actor_id": actor_id}
    if "artifact_id" in params:
        kwargs["artifact_id"] = entity_id
    elif "demand_id" in params:
        kwargs["demand_id"] = entity_id
    accepted = {k: v for k, v in kwargs.items() if k in params}

    if conn is not None:
        await fn(conn, **accepted)
        return True

    pool = await _pool()
    acquire = getattr(pool, "acquire", None)
    if acquire is not None:
        async with acquire() as acquired:
            async with acquired.transaction():
                await fn(acquired, **accepted)
    else:
        await fn(pool, **accepted)
    return True


async def _apply_approved(artifact_id: str, actor: str | None = None) -> bool:
    """Aplica `on agents review -> approved` **via lifecycle do F4**.

    - F4 ausente: UPDATE guardado em `status = 'on agents review'` (único
      estado de origem válido) — o fallback que a spec §5.7 autoriza.
    - F4 presente e recusando: **nada** é escrito (o lifecycle é o único
      caminho para escrever status).

    Devolve `True` quando o artefato foi promovido.
    """
    try:
        applied = await call_lifecycle_transition(
            "apply_artifact_transition", artifact_id, "approved", actor
        )
    except Exception:  # noqa: BLE001 — o F4 recusou: não escreve por fora dele
        return False
    if applied:
        return True
    await _execute(_SQL_SET_ARTIFACT_APPROVED, artifact_id, "approved")
    return True


async def run_pipeline(
    artifact: Any,
    *,
    client: Any | None = None,
    actor: str | None = None,
) -> PipelineResult:
    """Executa o pipeline de aprovação de um artefato.

    Não levanta exceção por indisponibilidade de LLM (vira `verdict="pending"`)
    nem por transição ilegal (a transição é aplicada por dentro, tolerando
    falha).
    """
    artifact_id = str(_field(artifact, "id"))
    kind = _field(artifact, "kind") or ("br" if artifact_id.startswith("BR-") else "spec")
    demand_id = _field(artifact, "demand_id")

    stages: list[dict] = []
    findings: list[dict] = []
    linter_findings: list[dict] = []
    review_artifacts: list[dict] = []
    blocking_reasons: list[str] = []
    doubts_written = 0
    llm_available = True
    error_type: str | None = None

    # ---- 1. LINTER -------------------------------------------------------
    started = time.monotonic()
    linter_findings, linter_error = await _run_linter(artifact)
    linter_errors = [f for f in linter_findings if f.get("severity") == "error"]
    linter_warnings = [f for f in linter_findings if f.get("severity") != "error"]
    stage = {
        "stage": "linter",
        "ok": linter_error is None,
        "findings": len(linter_findings),
    }
    stages.append(stage)
    await _publish_stage(artifact, stage, int((time.monotonic() - started) * 1000), actor)

    if linter_error is not None:
        blocking_reasons.append(f"linter: {linter_error}")
    elif linter_errors:
        blocking_reasons.extend(
            f"linter: {f.get('rule')} — {f.get('message')}" for f in linter_errors
        )

    # O linter barrou: pipeline para antes dos 3 revisores (spec D3).
    if linter_error is None and not linter_errors:
        # ---- 2..4. REVISORES ---------------------------------------------
        acs: list[str] = []
        documents: list[Any] = []
        spec_list: list[str] = []
        if client is None:
            try:
                from app.services.generator import build_client

                client = build_client()
            except Exception as exc:  # noqa: BLE001
                llm_available = False
                error_type = (
                    "LLMUnavailable"
                    if isinstance(exc, _llm_unavailable())
                    else type(exc).__name__
                )
        if client is not None:
            acs = await _origin_acs(artifact)
            documents = await _method_documents(artifact, kind)
            spec_list = await _spec_list(artifact)
        else:
            llm_available = False
            error_type = error_type or "LLMUnavailable"
            blocking_reasons.append("llm indisponível: cliente não construído")

        for reviewer in REVIEWERS:
            if not llm_available:
                stage = {
                    "stage": reviewer.slug,
                    "ok": False,
                    "findings": 0,
                }
                stages.append(stage)
                await _publish_stage(artifact, stage, 0, actor)
                break
            started = time.monotonic()
            try:
                reviewer_findings = await _call_reviewer(
                    client,
                    reviewer.system,
                    _user_prompt(artifact, reviewer, acs, documents, spec_list),
                )
            except Exception as exc:  # noqa: BLE001 — LLM fora, rede ou SDK
                llm_available = False
                error_type = (
                    "LLMUnavailable"
                    if isinstance(exc, _llm_unavailable())
                    else type(exc).__name__
                )
                blocking_reasons.append(f"llm indisponível: {exc}")
                stage = {"stage": reviewer.slug, "ok": False, "findings": 0}
                stages.append(stage)
                await _publish_stage(
                    artifact, stage, int((time.monotonic() - started) * 1000), actor
                )
                break

            findings.extend(reviewer_findings)
            stage = {
                "stage": reviewer.slug,
                "ok": True,
                "findings": len(reviewer_findings),
            }
            stages.append(stage)
            await _publish_stage(
                artifact, stage, int((time.monotonic() - started) * 1000), actor
            )
            content = _render_review_file(artifact, reviewer, reviewer_findings)
            review_artifacts.append(
                {
                    "reviewer": reviewer.slug,
                    "path": _review_artifact_path(artifact, reviewer),
                    "content": content,
                    "findings": len(reviewer_findings),
                }
            )

    # ---- Publicação dos artefatos de revisor ----------------------------
    for item in review_artifacts:
        await _publish_event(
            "review_artifact_written",
            {
                "reviewer": item["reviewer"],
                "path": item["path"],
                "content": item["content"],
                "sha": _sha256(item["content"]),
                "findings": item["findings"],
                "artifact_id": artifact_id,
            },
            demand_id=demand_id,
            artifact_id=artifact_id,
            actor=actor,
        )

    # ---- Pendências ------------------------------------------------------
    for warning in linter_warnings:
        await _insert_doubt(
            artifact_id, _linter_question(warning), "deferred", "linter"
        )
        doubts_written += 1

    for finding in findings:
        severity = finding.get("severity") or "deferred"
        status = FINDING_SEVERITY_TO_DOUBT_STATUS.get(severity, "deferred")
        await _insert_doubt(artifact_id, _finding_question(finding), status, "reviewer")
        doubts_written += 1

    # ---- Veredito (precedência D2) --------------------------------------
    blocking_findings = [f for f in findings if f.get("severity") == "blocking"]
    if linter_error is not None or linter_errors:
        verdict = "blocking"
    elif not llm_available:
        verdict = "pending"
    elif blocking_findings:
        verdict = "blocking"
    elif findings:
        verdict = "suggestions"
    else:
        verdict = "clean"

    for finding in blocking_findings:
        ac = (finding.get("ac") or "").strip()
        title = (finding.get("title") or "").strip()
        blocking_reasons.append(
            f"achado blocking: {title} ({ac})" if ac else f"achado blocking: {title}"
        )

    # ---- Approval gate (META-006 §8) ------------------------------------
    open_doubts = await list_open_doubts(artifact_id)
    for doubt in open_doubts:
        if doubt.status == "deferred":
            blocking_reasons.append("dúvida deferida ainda não resolvida")
        else:
            blocking_reasons.append(f"dúvida aberta: {doubt.id}")

    approval_ready = (
        linter_error is None
        and not linter_errors
        and llm_available
        and not blocking_findings
        and len(open_doubts) == 0
    )

    artifact_status = await _current_status(artifact_id)
    if approval_ready and artifact_status == "on agents review":
        promoted = await _apply_approved(artifact_id, actor)
        artifact_status = await _current_status(artifact_id)
        if not promoted or artifact_status != "approved":
            approval_ready = False
            blocking_reasons.append("transição para approved falhou")

    blocking_reasons = list(dict.fromkeys(blocking_reasons))

    # ---- Arquivo de dúvidas + catálogo (estado final do artefato) -------
    await publish_artifact_doubts(artifact_id, actor=actor)

    # ---- Evento final ---------------------------------------------------
    payload = {
        "verdict": verdict,
        "llm_available": llm_available,
        "doubts_written": doubts_written,
        "linter_findings": len(linter_findings),
        "approval_ready": approval_ready,
        "artifact_status": artifact_status,
    }
    if error_type:
        payload["error_type"] = error_type
    await _publish_event(
        "pipeline_completed",
        payload,
        demand_id=demand_id,
        artifact_id=artifact_id,
        actor=actor,
    )

    return PipelineResult(
        verdict=verdict,
        findings=findings,
        linter_findings=linter_findings,
        doubts_written=doubts_written,
        llm_available=llm_available,
        review_artifacts=review_artifacts,
        stages=stages,
        approval_ready=approval_ready,
        blocking_reasons=blocking_reasons,
        artifact_status=artifact_status,
    )


def _sha256(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
