"""Serviço de dúvidas (META-006) — implementado na fase F6.

Responsável por:
  - levantar / resolver pendências (tabela `doubts`);
  - renderizar o arquivo de dúvidas do artefato no **formato canônico v1**
    (mesmo do gerador, F5 §5.7);
  - renderizar o catálogo central (`duvidas-br.md` / `duvidas-spec.md`), que
    lista **apenas** artefatos com pendência aberta (META-006 §3/§9);
  - publicar o conteúdo em `events.payload` (jsonb) para o `pull` do F4
    escrever os arquivos no repo de dev (contrato D5/D10/D11).

Todas as dependências de outras fases (`app.db`, `app.models`) são importadas
**tardiamente**, dentro das funções: o módulo carrega mesmo antes de F1 existir,
e uma fase pendente vira `ImportError` no ponto de uso — nunca no import.

Contrato: Contrato Comum §7.5. Spec da fase: §5.5.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - só para o type checker
    from app.models import Doubt

__all__ = [
    "ArtifactNotFound",
    "DOUBT_SOURCES",
    "DoubtNotFound",
    "catalog_path",
    "doubts_file_path",
    "list_doubts",
    "list_open_doubts",
    "publish_artifact_doubts",
    "publish_catalog",
    "publish_doubts_file",
    "raise_doubt",
    "render_catalog",
    "render_doubts_file",
    "resolve_doubt",
    "to_iso",
]

#: Origem aceita pela coluna `doubts.source` (DDL §8 do design master).
DOUBT_SOURCES = ("reviewer", "linter", "user")

#: META-006 §6 — status do artefato -> status do arquivo de dúvidas.
_FILE_STATUS = {
    "draft": "draft",
    "pending": "pending",
    "on user review": "pending",
    "on agents review": "pending",
    "approved": "approved",
    "stable": "approved",
}

#: A pergunta truncada (F5 §5.7 / spec §5.5).
_QUESTION_MAX = 500

#: Caminho do catálogo central por kind (META-005 "Convenção de arquivos").
_CATALOG = {"br": "duvidas-br", "spec": "duvidas-spec"}


class DoubtNotFound(LookupError):
    """Dúvida inexistente. O handler mapeia para 404."""

    def __init__(self, doubt_id: str):
        super().__init__(f"dúvida {doubt_id} não existe")
        self.doubt_id = doubt_id


class ArtifactNotFound(LookupError):
    """Artefato inexistente. O handler mapeia para 404."""

    def __init__(self, artifact_id: str):
        super().__init__(f"artefato {artifact_id} não existe")
        self.artifact_id = artifact_id


# --------------------------------------------------------------------------
# SQL
# --------------------------------------------------------------------------

_SQL_INSERT_DOUBT = """
INSERT INTO doubts (artifact_id, question, status, source, raised_at)
VALUES ($1, $2, $3, $4, now())
RETURNING id, artifact_id, question, status, source, raised_at, resolved_at
"""

_SQL_RESOLVE_DOUBT = """
UPDATE doubts
   SET status = 'cleaned', resolved_at = now()
 WHERE id = $1
RETURNING id, artifact_id, question, status, source, raised_at, resolved_at
"""

_SQL_LIST_DOUBTS = """
SELECT id, artifact_id, question, status, source, raised_at, resolved_at
  FROM doubts
 WHERE artifact_id = $1
 ORDER BY raised_at, id
"""

_SQL_ARTIFACT_META = """
SELECT id, kind, path, status, demand_id, updated_at
  FROM artifacts
 WHERE id = $1
"""

_SQL_CATALOG = """
SELECT a.id, a.path, a.updated_at, COUNT(*) AS open_count
  FROM artifacts a
  JOIN doubts d ON d.artifact_id = a.id
 WHERE a.kind = $1 AND d.status <> 'cleaned'
 GROUP BY a.id, a.path, a.updated_at
 ORDER BY a.id
"""

_SQL_EVENT = """
INSERT INTO events (demand_id, artifact_id, type, payload, actor, at)
VALUES ($1, $2, $3, $4::jsonb, $5, now())
"""


# --------------------------------------------------------------------------
# Helpers de acesso (import tardio — F1)
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
    """Lê um campo de dataclass, dict, asyncpg.Record ou Mapping."""
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


def to_iso(value: datetime | None) -> str | None:
    """Datetime -> ISO 8601 UTC com sufixo `Z` (segundo de precisão)."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _escape_cell(text: str | None) -> str:
    """Normaliza o texto de uma célula de tabela markdown."""
    value = (text or "").replace("\r\n", "\n").replace("\n", " ").replace("|", "\\|")
    value = " ".join(value.split())
    if len(value) > _QUESTION_MAX:
        value = value[: _QUESTION_MAX - 1] + "…"
    return value


def _doubt_from_row(row: Any) -> "Doubt":
    """Constroi o `Doubt` do F1 a partir da linha do banco."""
    from app.models import Doubt

    fields = {
        "id": str(_field(row, "id")),
        "artifact_id": _field(row, "artifact_id"),
        "question": _field(row, "question"),
        "status": _field(row, "status"),
        "source": _field(row, "source"),
        "raised_at": _field(row, "raised_at"),
        "resolved_at": _field(row, "resolved_at"),
    }
    from_row = getattr(Doubt, "from_row", None)
    if from_row is not None:
        return from_row(row)
    params = inspect.signature(Doubt).parameters
    return Doubt(**{k: v for k, v in fields.items() if k in params})


# --------------------------------------------------------------------------
# Caminhos (META-005 "Convenção de arquivos")
# --------------------------------------------------------------------------


def doubts_file_path(artifact_id: str, kind: str) -> str:
    """`docs/implementation-artifacts/duvidas-{br,spec}/<ID>.md`."""
    folder = _CATALOG.get(kind, "duvidas-spec")
    return f"docs/implementation-artifacts/{folder}/{artifact_id}.md"


def catalog_path(kind: str) -> str:
    """`docs/implementation-artifacts/duvidas-{br,spec}.md`."""
    folder = _CATALOG.get(kind, "duvidas-spec")
    return f"docs/implementation-artifacts/{folder}.md"


# --------------------------------------------------------------------------
# API pública (Contrato Comum §7.5)
# --------------------------------------------------------------------------


async def raise_doubt(artifact_id: str, question: str, source: str) -> "Doubt":
    """Levanta uma pendência `pending` e publica o arquivo + o catálogo."""
    if source not in DOUBT_SOURCES:
        raise ValueError(
            f"source inválida: {source!r} (aceito: {', '.join(DOUBT_SOURCES)})"
        )
    doubt = await _insert_doubt(artifact_id, question, "pending", source)
    await publish_artifact_doubts(artifact_id)
    return doubt


async def resolve_doubt(doubt_id: str) -> "Doubt":
    """Marca a pendência como `cleaned` e republica arquivo + catálogo."""
    row = await _fetchrow(_SQL_RESOLVE_DOUBT, doubt_id)
    if row is None:
        raise DoubtNotFound(doubt_id)
    doubt = _doubt_from_row(row)
    await publish_artifact_doubts(doubt.artifact_id)
    return doubt


async def list_doubts(artifact_id: str) -> list["Doubt"]:
    """Todas as pendências do artefato, em ordem de levantamento."""
    rows = await _fetch(_SQL_LIST_DOUBTS, artifact_id)
    return [_doubt_from_row(row) for row in rows]


async def list_open_doubts(artifact_id: str) -> list["Doubt"]:
    """Pendências que ainda não estão `cleaned` (bloqueiam o approval gate)."""
    return [d for d in await list_doubts(artifact_id) if d.status != "cleaned"]


def render_doubts_file(
    artifact_id: str,
    doubts: list["Doubt"],
    artifact_status: str | None = None,
) -> str:
    """Renderiza o arquivo de dúvidas no **formato canônico v1** (F5 §5.7).

    Função síncrona e pura: não toca o banco. `artifact_status` é o status do
    artefato (META-006 §6); quando omitido, infere `pending` (há pendência) ou
    `approved` (nenhuma pendência).
    """
    if artifact_status is None:
        artifact_status = (
            "pending" if any(d.status != "cleaned" for d in doubts) else "approved"
        )
    file_status = _FILE_STATUS.get(artifact_status, "pending")
    open_count = sum(1 for d in doubts if d.status != "cleaned")

    lines = [
        "---",
        f"id: {artifact_id}",
        f"artifactId: {artifact_id}",
        f"status: {file_status}",
        f'updatedAt: "{to_iso(datetime.now(timezone.utc))}"',
        "---",
        "",
        f"# Dúvidas — {artifact_id}",
        "",
        f"Pendências: {open_count}",
        "",
        "| id | status | source | question | raised_at | resolved_at |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for doubt in doubts:
        lines.append(
            "| {id} | {status} | {source} | {question} | {raised} | {resolved} |".format(
                id=doubt.id,
                status=doubt.status,
                source=doubt.source,
                question=_escape_cell(doubt.question),
                raised=to_iso(doubt.raised_at) or "—",
                resolved=to_iso(doubt.resolved_at) or "—",
            )
        )
    return "\n".join(lines) + "\n"


async def render_catalog(kind: str) -> str:
    """Catálogo central: só artefatos com **pendência aberta** (META-006 §9)."""
    rows = await _fetch(_SQL_CATALOG, kind)
    title = "BR" if kind == "br" else "SPEC"
    lines = [
        f"# Dúvidas de {title} — pendências abertas",
        "",
        "| artifact_id | path | abertas | atualizado_em |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {id} | {path} | {count} | {updated} |".format(
                id=_field(row, "id"),
                path=_field(row, "path"),
                count=_field(row, "open_count"),
                updated=to_iso(_field(row, "updated_at")) or "—",
            )
        )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Publicação (contrato D5/D10/D11)
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
        demand_id,
        artifact_id,
        event_type,
        json.dumps(payload, ensure_ascii=False),
        actor,
    )


async def publish_doubts_file(artifact_id: str, actor: str | None = None) -> str:
    """Renderiza e publica o arquivo de dúvidas (evento `doubts_file_rendered`)."""
    meta = await _fetchrow(_SQL_ARTIFACT_META, artifact_id)
    if meta is None:
        raise ArtifactNotFound(artifact_id)
    doubts = await list_doubts(artifact_id)
    content = render_doubts_file(artifact_id, doubts, _field(meta, "status"))
    await _publish_event(
        "doubts_file_rendered",
        {
            "artifact_id": artifact_id,
            "path": doubts_file_path(artifact_id, _field(meta, "kind") or "spec"),
            "content": content,
            "sha": _sha256(content),
        },
        demand_id=_field(meta, "demand_id"),
        artifact_id=artifact_id,
        actor=actor,
    )
    return content


async def publish_catalog(kind: str, actor: str | None = None) -> str:
    """Renderiza e publica o catálogo central (evento `doubts_catalog_rendered`)."""
    content = await render_catalog(kind)
    await _publish_event(
        "doubts_catalog_rendered",
        {
            "kind": kind,
            "path": catalog_path(kind),
            "content": content,
            "sha": _sha256(content),
        },
        actor=actor,
    )
    return content


async def publish_artifact_doubts(artifact_id: str, actor: str | None = None) -> bool:
    """Publica o arquivo de dúvidas do artefato + o catálogo do kind.

    Devolve `False` (sem exceção) quando o artefato não existe: o arquivo é
    espelho — a pendência já está gravada na tabela `doubts`.
    """
    meta = await _fetchrow(_SQL_ARTIFACT_META, artifact_id)
    if meta is None:
        return False
    await publish_doubts_file(artifact_id, actor=actor)
    await publish_catalog(_field(meta, "kind") or "spec", actor=actor)
    return True


# --------------------------------------------------------------------------
# Interno
# --------------------------------------------------------------------------


async def _insert_doubt(
    artifact_id: str, question: str, status: str, source: str
) -> "Doubt":
    """Insere uma pendência com status explícito.

    A API pública `raise_doubt` sempre grava `pending`; o pipeline de revisão
    usa esta função para gravar `deferred` (achado `suggestion`/`deferred` do
    revisor, ou `warning` do linter).
    """
    if source not in DOUBT_SOURCES:
        raise ValueError(
            f"source inválida: {source!r} (aceito: {', '.join(DOUBT_SOURCES)})"
        )
    row = await _fetchrow(
        _SQL_INSERT_DOUBT, artifact_id, question, status, source
    )
    if row is None:
        raise RuntimeError("INSERT em doubts não retornou linha")
    return _doubt_from_row(row)
