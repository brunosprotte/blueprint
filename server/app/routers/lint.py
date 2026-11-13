"""Router de lint de artefatos. Implementado na fase F2.

`POST /api/lint` — valida documentos BR/SPEC contra o padrão Blueprint.
O linter é puro e determinístico: mesmo input → mesma saída.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import Token, require_scope
from app.config import settings
from app.db import get_pool
from app.lint.runner import (
    CompositeUniverse,
    MethodCorpus,
    SyncedArtifacts,
    lint_batch,
    parse_document,
)

router = APIRouter()

# Dependência de escopo — nomeada em módulo para que os testes possam
# sobrescrever (`app.dependency_overrides[require_artifact_sync]`).
require_artifact_sync = require_scope("artifact:sync")


# --------------------------------------------------------------------------- #
# Contrato HTTP
# --------------------------------------------------------------------------- #


class LintDoc(BaseModel):
    path: str
    content: str


class LintRequest(BaseModel):
    repo: str | None = None
    docs: list[LintDoc] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)


class LintFinding(BaseModel):
    rule: str
    severity: str
    message: str
    path: str | None = None
    line: int | None = None
    detail: dict = Field(default_factory=dict)


class LintSummary(BaseModel):
    error: int = 0
    warning: int = 0


class LintResponse(BaseModel):
    findings: list[LintFinding] = Field(default_factory=list)
    summary: LintSummary = Field(default_factory=LintSummary)


# --------------------------------------------------------------------------- #
# Universo de links
# --------------------------------------------------------------------------- #

# Índice do corpus do método em memória (construído no primeiro uso).
_METHOD_CORPUS: dict[str, MethodCorpus] = {}


def method_corpus(root: Path) -> MethodCorpus:
    """Corpus do método indexado em memória, reaproveitado entre requests."""
    key = str(root)
    if key not in _METHOD_CORPUS:
        _METHOD_CORPUS[key] = MethodCorpus(root)
    return _METHOD_CORPUS[key]


async def _pool() -> Any:
    """Pool do banco.

    ``app.db.get_pool`` é da F1, escrita em paralelo: aceita tanto a forma
    assíncrona (``await get_pool()``) quanto a síncrona (pool global).
    """
    pool = get_pool()
    if inspect.isawaitable(pool):
        pool = await pool
    return pool


# --------------------------------------------------------------------------- #
# Endpoint
# --------------------------------------------------------------------------- #


@router.post("/lint", response_model=LintResponse)
async def lint_artifacts(
    request: LintRequest,
    token: Token = Depends(require_artifact_sync),
) -> LintResponse | JSONResponse:
    """Valida os documentos enviados contra o padrão Blueprint.

    `docs` traz path + conteúdo. `paths` sozinho não serve: o servidor nunca lê
    o repo de dev — o kit manda o conteúdo junto.
    """
    if not request.docs:
        code = "paths_without_content" if request.paths else "no_documents"
        message = (
            "paths sem conteúdo: envie {docs: [{path, content}]}"
            if request.paths
            else "nenhum documento para validar"
        )
        return JSONResponse(
            status_code=400,
            content={"error": {"code": code, "message": message, "detail": {}}},
        )

    docs = [
        parse_document(doc.path, doc.content, repo_id=request.repo)
        for doc in request.docs
    ]

    synced = SyncedArtifacts(await _pool())
    await synced.refresh()
    universe = CompositeUniverse(
        method_corpus(settings.repo_root),
        synced,
    )

    findings = lint_batch(docs, universe)
    summary = LintSummary(
        error=sum(1 for finding in findings if finding.severity == "error"),
        warning=sum(1 for finding in findings if finding.severity == "warning"),
    )
    return LintResponse(
        findings=[LintFinding(**vars(finding)) for finding in findings],
        summary=summary,
    )
