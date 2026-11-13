"""Dataclasses de domínio do servidor SDD (design master §8).

Não é ORM: cada dataclass sabe ler uma linha do Postgres (`from_row`) e
serializar para JSON (`to_dict`). Datas viram ISO 8601, uuid vira string e
colunas `jsonb` viram objeto.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass
from typing import Any, Mapping


def _get(row: Mapping[str, Any], key: str, default: Any = None) -> Any:
    """Lê uma coluna tolerando linhas incompletas."""
    return row[key] if key in row else default


def _json_value(value: Any) -> Any:
    """Normaliza `jsonb` (asyncpg devolve str) para objeto/lista."""
    if isinstance(value, (str, bytes)):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def _jsonable(value: Any) -> Any:
    """Converte datetime/uuid/jsonb para algo serializável em JSON."""
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class User:
    """Conta de usuário (login GitHub ou usuário de desenvolvimento)."""

    id: str
    github_id: int
    login: str
    email: str | None = None
    avatar_url: str | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "User":
        """Lê uma linha da tabela `users`."""
        return cls(
            id=str(_get(row, "id")),
            github_id=_get(row, "github_id"),
            login=_get(row, "login"),
            email=_get(row, "email"),
            avatar_url=_get(row, "avatar_url"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializa para JSON."""
        return {
            "id": self.id,
            "github_id": self.github_id,
            "login": self.login,
            "email": self.email,
            "avatar_url": self.avatar_url,
        }


@dataclass(frozen=True)
class Token:
    """Token de API opaco — só o sha256 do valor cru é persistido."""

    id: str
    user_id: str
    repo_id: str | None
    scopes: tuple[str, ...]

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Token":
        """Lê uma linha da tabela `tokens`."""
        return cls(
            id=str(_get(row, "id")),
            user_id=str(_get(row, "user_id")),
            repo_id=str(_get(row, "repo_id")) if _get(row, "repo_id") else None,
            scopes=tuple(_get(row, "scopes") or ()),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializa para JSON (sem o hash — nunca sai do servidor)."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "repo_id": self.repo_id,
            "scopes": list(self.scopes),
        }


@dataclass(frozen=True)
class Repo:
    """Repositório de dev registrado no servidor."""

    id: str
    owner: str
    name: str
    default_branch: str = "main"

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Repo":
        """Lê uma linha da tabela `repos`."""
        return cls(
            id=str(_get(row, "id")),
            owner=_get(row, "owner"),
            name=_get(row, "name"),
            default_branch=_get(row, "default_branch", "main"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializa para JSON."""
        return {
            "id": self.id,
            "owner": self.owner,
            "name": self.name,
            "default_branch": self.default_branch,
        }


@dataclass(frozen=True)
class Demand:
    """Demanda na fila compartilhada (design master §9.1)."""

    id: str
    title: str
    status: str
    repo_id: str | None = None
    module: str | None = None
    body: str | None = None
    claimed_by: str | None = None
    claimed_at: dt.datetime | None = None
    created_by: str | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Demand":
        """Lê uma linha da tabela `demands`."""
        return cls(
            id=str(_get(row, "id")),
            title=_get(row, "title"),
            status=_get(row, "status"),
            repo_id=str(_get(row, "repo_id")) if _get(row, "repo_id") else None,
            module=_get(row, "module"),
            body=_get(row, "body"),
            claimed_by=str(_get(row, "claimed_by")) if _get(row, "claimed_by") else None,
            claimed_at=_get(row, "claimed_at"),
            created_by=str(_get(row, "created_by")) if _get(row, "created_by") else None,
            created_at=_get(row, "created_at"),
            updated_at=_get(row, "updated_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializa para JSON."""
        return _jsonable(
            {
                "id": self.id,
                "title": self.title,
                "status": self.status,
                "repo_id": self.repo_id,
                "module": self.module,
                "body": self.body,
                "claimed_by": self.claimed_by,
                "claimed_at": self.claimed_at,
                "created_by": self.created_by,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            }
        )


@dataclass(frozen=True)
class Artifact:
    """Artefato BR/SPEC sincronizado de um repo de dev."""

    id: str
    kind: str
    path: str | None = None
    status: str = "draft"
    demand_id: str | None = None
    repo_id: str | None = None
    module: str | None = None
    feature: str | None = None
    sha: str | None = None
    version: str | None = None
    content: str | None = None
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Artifact":
        """Lê uma linha da tabela `artifacts`."""
        return cls(
            id=str(_get(row, "id")),
            kind=_get(row, "kind"),
            path=_get(row, "path"),
            status=_get(row, "status", "draft"),
            demand_id=str(_get(row, "demand_id")) if _get(row, "demand_id") else None,
            repo_id=str(_get(row, "repo_id")) if _get(row, "repo_id") else None,
            module=_get(row, "module"),
            feature=_get(row, "feature"),
            sha=_get(row, "sha"),
            version=_get(row, "version"),
            content=_get(row, "content"),
            created_at=_get(row, "created_at"),
            updated_at=_get(row, "updated_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializa para JSON."""
        return _jsonable(
            {
                "id": self.id,
                "kind": self.kind,
                "path": self.path,
                "status": self.status,
                "demand_id": self.demand_id,
                "repo_id": self.repo_id,
                "module": self.module,
                "feature": self.feature,
                "sha": self.sha,
                "version": self.version,
                "content": self.content,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            }
        )


@dataclass(frozen=True)
class Doubt:
    """Dúvida levantada sobre um artefato (META-006)."""

    id: str
    artifact_id: str
    question: str
    status: str = "pending"
    source: str | None = None
    raised_at: dt.datetime | None = None
    resolved_at: dt.datetime | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Doubt":
        """Lê uma linha da tabela `doubts`."""
        return cls(
            id=str(_get(row, "id")),
            artifact_id=str(_get(row, "artifact_id")),
            question=_get(row, "question"),
            status=_get(row, "status", "pending"),
            source=_get(row, "source"),
            raised_at=_get(row, "raised_at"),
            resolved_at=_get(row, "resolved_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializa para JSON."""
        return _jsonable(
            {
                "id": self.id,
                "artifact_id": self.artifact_id,
                "question": self.question,
                "status": self.status,
                "source": self.source,
                "raised_at": self.raised_at,
                "resolved_at": self.resolved_at,
            }
        )


@dataclass(frozen=True)
class Commit:
    """Commit reportado pelo kit após um push."""

    id: str
    sha: str
    demand_id: str | None = None
    repo_id: str | None = None
    message: str | None = None
    branch: str | None = None
    author: str | None = None
    files: list[Any] | None = None
    created_at: dt.datetime | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Commit":
        """Lê uma linha da tabela `commits`."""
        return cls(
            id=str(_get(row, "id")),
            sha=_get(row, "sha"),
            demand_id=str(_get(row, "demand_id")) if _get(row, "demand_id") else None,
            repo_id=str(_get(row, "repo_id")) if _get(row, "repo_id") else None,
            message=_get(row, "message"),
            branch=_get(row, "branch"),
            author=_get(row, "author"),
            files=_json_value(_get(row, "files")) or [],
            created_at=_get(row, "created_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializa para JSON."""
        return _jsonable(
            {
                "id": self.id,
                "sha": self.sha,
                "demand_id": self.demand_id,
                "repo_id": self.repo_id,
                "message": self.message,
                "branch": self.branch,
                "author": self.author,
                "files": self.files,
                "created_at": self.created_at,
            }
        )


@dataclass(frozen=True)
class Review:
    """Resultado de um pipeline de revisão."""

    id: str
    verdict: str
    commit_id: str | None = None
    demand_id: str | None = None
    findings: list[Any] | None = None
    created_at: dt.datetime | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Review":
        """Lê uma linha da tabela `reviews`."""
        return cls(
            id=str(_get(row, "id")),
            verdict=_get(row, "verdict"),
            commit_id=str(_get(row, "commit_id")) if _get(row, "commit_id") else None,
            demand_id=str(_get(row, "demand_id")) if _get(row, "demand_id") else None,
            findings=_json_value(_get(row, "findings")) or [],
            created_at=_get(row, "created_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializa para JSON."""
        return _jsonable(
            {
                "id": self.id,
                "verdict": self.verdict,
                "commit_id": self.commit_id,
                "demand_id": self.demand_id,
                "findings": self.findings,
                "created_at": self.created_at,
            }
        )


@dataclass(frozen=True)
class Chunk:
    """Trecho indexado de um artefato, commit ou review (contrato §7.6)."""

    id: str
    source_kind: str
    text: str
    corpus_id: str
    artifact_id: str | None = None
    demand_id: str | None = None
    heading: str | None = None
    token_count: int | None = None
    created_at: dt.datetime | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Chunk":
        """Lê uma linha da tabela `chunks`."""
        return cls(
            id=str(_get(row, "id")),
            source_kind=_get(row, "source_kind"),
            text=_get(row, "text"),
            corpus_id=_get(row, "corpus_id"),
            artifact_id=str(_get(row, "artifact_id")) if _get(row, "artifact_id") else None,
            demand_id=str(_get(row, "demand_id")) if _get(row, "demand_id") else None,
            heading=_get(row, "heading"),
            token_count=_get(row, "token_count"),
            created_at=_get(row, "created_at"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializa para JSON (sem `tsv` — é índice interno do Postgres)."""
        return _jsonable(
            {
                "id": self.id,
                "source_kind": self.source_kind,
                "text": self.text,
                "corpus_id": self.corpus_id,
                "artifact_id": self.artifact_id,
                "demand_id": self.demand_id,
                "heading": self.heading,
                "token_count": self.token_count,
                "created_at": self.created_at,
            }
        )


@dataclass(frozen=True)
class Event:
    """Evento da timeline (design master §8, forma consumida pelo painel F10)."""

    id: int
    type: str
    payload: dict[str, Any] | None = None
    demand_id: str | None = None
    artifact_id: str | None = None
    actor: str | None = None
    at: dt.datetime | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "Event":
        """Lê uma linha da tabela `events`."""
        payload = _json_value(_get(row, "payload"))
        return cls(
            id=int(_get(row, "id")),
            type=_get(row, "type"),
            payload=payload if isinstance(payload, dict) else {},
            demand_id=str(_get(row, "demand_id")) if _get(row, "demand_id") else None,
            artifact_id=str(_get(row, "artifact_id")) if _get(row, "artifact_id") else None,
            actor=str(_get(row, "actor")) if _get(row, "actor") else None,
            at=_get(row, "at"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serializa para JSON — forma `{id, demand_id, artifact_id, type, payload, at}`."""
        return {
            "id": self.id,
            "demand_id": self.demand_id,
            "artifact_id": self.artifact_id,
            "type": self.type,
            "payload": self.payload or {},
            "at": _jsonable(self.at),
        }


__all__: list[str] = [
    "Artifact",
    "Chunk",
    "Commit",
    "Demand",
    "Doubt",
    "Event",
    "Repo",
    "Review",
    "Token",
    "User",
]
