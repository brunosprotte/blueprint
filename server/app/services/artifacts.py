"""Serviço de artefatos — sync repo→servidor, promoção e ciclo de vida. F4.

O banco é a autoridade do **status**; o repo de dev é a autoridade do
**conteúdo** (design master §21). O servidor nunca escreve no repo (invariante 1).
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import yaml

from app.db import fetch, fetchrow
from app.services.lifecycle import (
    ApiError,
    apply_artifact_transition,
    as_uuid,
    jsonable,
    record_event,
    row_to_dict,
    split_repo,
)

ID_PATTERN = re.compile(r"^(BR|SPEC)-\d{3}$")
KINDS = {"br": "BR", "spec": "SPEC", "ri": "RI"}
DOUBTS_DIR = {"br": "duvidas-br", "spec": "duvidas-spec", "ri": "duvidas-ri"}
ARTIFACT_LIST_COLUMNS = (
    "a.id, a.demand_id, a.repo_id, a.kind, a.module, a.feature, a.path, a.sha, "
    "a.status, a.version, a.doubts_index, a.created_at, a.updated_at"
)


# --------------------------------------------------------------------------
# Repos
# --------------------------------------------------------------------------
async def ensure_repo(pool, repo: str) -> str:
    """Resolve (ou cria) o repo `owner/name` e devolve o `repo_id` (uuid)."""
    owner, name = split_repo(repo)
    row = await fetchrow(
        pool,
        """
        INSERT INTO repos (owner, name)
        VALUES ($1, $2)
        ON CONFLICT (owner, name) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        owner,
        name,
    )
    return str(row["id"])


async def _ensure_repo_conn(conn, repo: str):
    """Mesmo contrato de `ensure_repo`, dentro da transação do chamador."""
    owner, name = split_repo(repo)
    row = await conn.fetchrow(
        """
        INSERT INTO repos (owner, name)
        VALUES ($1, $2)
        ON CONFLICT (owner, name) DO UPDATE SET name = EXCLUDED.name
        RETURNING id
        """,
        owner,
        name,
    )
    return row["id"]


# --------------------------------------------------------------------------
# Leitura
# --------------------------------------------------------------------------
async def list_artifacts(
    pool,
    *,
    demand_id: str | None,
    repo: str | None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    args: list[object] = []
    where: list[str] = []
    if demand_id:
        args.append(as_uuid(demand_id))
        where.append(f"a.demand_id = ${len(args)}")
    if repo:
        owner, name = split_repo(repo)
        args.extend([owner, name])
        where.append(f"r.owner = ${len(args) - 1} AND r.name = ${len(args)}")
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    args.extend([min(max(int(limit), 1), 200), max(int(offset), 0)])

    rows = await fetch(
        pool,
        f"""
        SELECT {ARTIFACT_LIST_COLUMNS}, r.owner, r.name
          FROM artifacts a
          LEFT JOIN repos r ON r.id = a.repo_id
          {clause}
         ORDER BY a.updated_at DESC
         LIMIT ${len(args) - 1} OFFSET ${len(args)}
        """,
        *args,
    )
    return [_artifact_row(r) for r in rows]


def _artifact_row(row) -> dict:
    data = row_to_dict(row)
    owner = data.pop("owner", None)
    name = data.pop("name", None)
    if owner and name:
        data["repo"] = f"{owner}/{name}"
    return data


async def get_artifact(pool, artifact_id: str) -> dict | None:
    row = await fetchrow(
        pool,
        """
        SELECT a.*, r.owner, r.name
          FROM artifacts a
          LEFT JOIN repos r ON r.id = a.repo_id
         WHERE a.id = $1
        """,
        artifact_id,
    )
    if row is None:
        return None

    artifact = _artifact_row(row)
    edges = await fetch(
        pool,
        "SELECT child_id, type FROM spec_edges WHERE parent_id = $1 ORDER BY child_id",
        artifact_id,
    )
    artifact["edges"] = [row_to_dict(e) for e in edges]
    return artifact


async def list_pending(pool, *, repo: str, demand_id: str | None = None) -> list[dict]:
    """Artefatos do repo que o kit (`sdd.py pull`) ainda precisa escrever."""
    owner, name = split_repo(repo)
    args: list[object] = [owner, name]
    clause = "r.owner = $1 AND r.name = $2 AND a.status <> 'stable'"
    if demand_id:
        args.append(as_uuid(demand_id))
        clause += f" AND a.demand_id = ${len(args)}"
    args.append(100)

    rows = await fetch(
        pool,
        f"""
        SELECT a.id, a.kind, a.path, a.status, a.content
          FROM artifacts a
          JOIN repos r ON r.id = a.repo_id
         WHERE {clause}
         ORDER BY a.updated_at DESC
         LIMIT ${len(args)}
        """,
        *args,
    )
    return [
        {
            "id": r["id"],
            "kind": r["kind"],
            "path": r["path"],
            "status": r["status"],
            "content": r["content"] or "",
        }
        for r in rows
    ]


async def list_doubts(pool, artifact_id: str) -> list[dict]:
    rows = await fetch(
        pool,
        """
        SELECT id, question, status, source, raised_at, resolved_at
          FROM doubts
         WHERE artifact_id = $1
         ORDER BY raised_at ASC, id ASC
        """,
        artifact_id,
    )
    return [row_to_dict(r) for r in rows]


# --------------------------------------------------------------------------
# Frontmatter / path
# --------------------------------------------------------------------------
def parse_frontmatter(content: str) -> tuple[dict, str]:
    """`yaml.safe_load` do bloco inicial. Sem frontmatter → `({}, content)`."""
    if not content.startswith("---"):
        return {}, content
    parts = content.split("\n")
    end = None
    for index in range(1, len(parts)):
        if parts[index].strip() == "---":
            end = index
            break
    if end is None:
        return {}, content
    try:
        data = yaml.safe_load("\n".join(parts[1:end])) or {}
    except yaml.YAMLError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data, "\n".join(parts[end + 1 :])


def classify_path(path: str) -> str | None:
    """`docs/BR/**` → `br`; `docs/SPEC/**` → `spec`; `docs/RI/**` → `ri`."""
    parts = PurePosixPath(path).parts
    if len(parts) < 3 or parts[0] != "docs":
        return None
    mapping = {"BR": "br", "SPEC": "spec", "RI": "ri"}
    return mapping.get(parts[1])


def validate_path(path: str) -> str:
    """Path relativo, sem `..`, sem absoluto. 400 `invalid_path` se inválido."""
    if not path or path.startswith("/") or "\\" in path:
        raise ApiError("invalid_path", "path deve ser relativo ao repo", 400, {"path": path})
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts:
        raise ApiError("invalid_path", "path não pode conter '..'", 400, {"path": path})
    return str(pure)


def sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _next_artifact_id(conn, kind: str) -> str:
    prefix = KINDS[kind]
    await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", f"artifact-id:{prefix}")
    row = await conn.fetchrow(
        """
        SELECT COALESCE(MAX((regexp_match(id, '(\\d+)$'))[1]::int), 0) + 1 AS next
          FROM artifacts
         WHERE id LIKE $1 || '-%'
        """,
        prefix,
    )
    return f"{prefix}-{int(row['next']):03d}"


def doubts_index_path(kind: str, artifact_id: str) -> str:
    return f"docs/implementation-artifacts/{DOUBTS_DIR[kind]}/{artifact_id}.md"


def render_doubts_template(kind: str, artifact_id: str, timestamp: str) -> str:
    """Template inicial do arquivo de dúvidas (META-006 §5)."""
    return f"""---
type: Dúvidas
artifact: {artifact_id}
artifactStatus: draft
updatedAt: {timestamp}
---

# Dúvidas — {artifact_id}

## Estado

Nenhuma pendência registrada.

## Histórico

- {timestamp} — arquivo inicializado.
"""


# --------------------------------------------------------------------------
# Lint (F2) — gate de transição, não gate de requisição
# --------------------------------------------------------------------------
def _repo_root() -> Path:
    """Raiz do repo blueprint (mesmo default de `app/config.py`)."""
    try:
        from app.config import settings

        return Path(settings.repo_root)
    except Exception:
        return Path(__file__).resolve().parents[3]


def build_universe(pool):
    """Universo de links: corpus do método (F2) + artefatos sincronizados."""
    try:
        from app.lint.runner import CompositeUniverse, MethodCorpus, SyncedArtifacts
    except ImportError:
        return None
    try:
        return CompositeUniverse(
            MethodCorpus(_repo_root() / "docs"),
            SyncedArtifacts(pool),
        )
    except Exception:
        return None


def _lint_doc(path, content, frontmatter, body, kind, repo_id, universe):
    """Roda o linter do F2. `None` = linter indisponível (não promote)."""
    if universe is None:
        return None
    try:
        from app.lint.runner import ArtifactDoc, lint_document
    except ImportError:
        return None
    doc = ArtifactDoc(
        path=path,
        content=content,
        frontmatter=frontmatter,
        body=body,
        kind=kind,
        repo_id=repo_id,
    )
    try:
        return lint_document(doc, universe)
    except Exception:
        return None


def _finding_dict(finding) -> dict:
    if isinstance(finding, dict):
        return {k: jsonable(v) for k, v in finding.items()}
    data = getattr(finding, "__dict__", None)
    if data:
        return {k: jsonable(v) for k, v in data.items()}
    return {
        "rule": getattr(finding, "rule", ""),
        "severity": getattr(finding, "severity", ""),
        "message": getattr(finding, "message", ""),
    }


def _lint_counts(findings) -> dict:
    if findings is None:
        return {"error": 0, "warning": 0, "available": False}
    errors = sum(1 for f in findings if getattr(f, "severity", None) == "error")
    warnings = sum(1 for f in findings if getattr(f, "severity", None) == "warning")
    return {"error": errors, "warning": warnings, "available": True}


# --------------------------------------------------------------------------
# Sync
# --------------------------------------------------------------------------
async def sync(pool, *, repo: str, docs: list[dict], actor_id: str | None) -> dict:
    """Upsert por `(repo_id, path)`. Uma transação só; divergência aborta tudo."""
    results: list[dict] = []
    summary = {
        "docs": len(docs),
        "artifacts": 0,
        "created": 0,
        "promoted": 0,
        "changed": 0,
        "ignored": 0,
        "lint_error": 0,
        "lint_warning": 0,
    }

    async with pool.acquire() as conn:
        async with conn.transaction():
            repo_id = await _ensure_repo_conn(conn, repo)
            universe = build_universe(pool)

            for doc in docs:
                path = validate_path(doc.get("path") or "")
                content = doc.get("content") or ""
                sha = sha256(content)
                kind = classify_path(path)

                if kind is None:
                    summary["ignored"] += 1
                    continue

                frontmatter, body = parse_frontmatter(content)
                row, created = await _upsert_artifact(conn, repo_id, path, content, sha, kind, frontmatter)

                artifact_id = row["id"]
                status = row["status"]
                promoted = False
                changed = created

                findings = _lint_doc(path, content, frontmatter, body, kind, str(repo_id), universe)
                lint_result = _lint_counts(findings)

                if not created:
                    if status == "draft":
                        if row["sha"] == sha:
                            if lint_result["available"] and lint_result["error"] == 0:
                                await apply_artifact_transition(
                                    conn,
                                    artifact_id,
                                    "pending",
                                    actor_id=actor_id,
                                    event_type="artifact.promoted",
                                )
                                promoted = True
                                status = "pending"
                        else:
                            raise ApiError(
                                "content_diverged",
                                "conteúdo divergente do servidor",
                                409,
                                {
                                    "path": path,
                                    "server_sha": row["sha"],
                                    "client_sha": sha,
                                    "server_status": row["status"],
                                },
                            )
                    elif row["sha"] != sha or (row["content"] or "") != content:
                        # O repo é autoritativo para o **conteúdo**; o status é do banco.
                        await conn.execute(
                            """
                            UPDATE artifacts
                               SET content = $2, sha = $3, updated_at = now()
                             WHERE id = $1
                            """,
                            artifact_id,
                            content,
                            sha,
                        )
                        changed = True

                await _sync_edges(conn, artifact_id, frontmatter)

                summary["artifacts"] += 1
                summary["created"] += int(created)
                summary["promoted"] += int(promoted)
                summary["changed"] += int(changed)
                summary["lint_error"] += lint_result["error"]
                summary["lint_warning"] += lint_result["warning"]

                if created:
                    await record_event(
                        conn,
                        type="artifact.created",
                        artifact_id=artifact_id,
                        payload={"path": path, "id": artifact_id, "kind": kind},
                        actor_id=actor_id,
                    )

                if created or changed or promoted:
                    payload = {
                        "path": path,
                        "id": artifact_id,
                        "sha": sha,
                        "status": status,
                        "promoted": promoted,
                        "changed": changed,
                        "lint": lint_result,
                    }
                    frontmatter_status = frontmatter.get("status")
                    if frontmatter_status and frontmatter_status != status:
                        payload["frontmatter_status"] = frontmatter_status
                    await record_event(
                        conn,
                        type="artifact.synced",
                        artifact_id=artifact_id,
                        payload=payload,
                        actor_id=actor_id,
                    )

                results.append(
                    {
                        "path": path,
                        "id": artifact_id,
                        "status": status,
                        "created": created,
                        "promoted": promoted,
                        "changed": changed,
                        "sha": sha,
                        "lint": {"error": lint_result["error"], "warning": lint_result["warning"]},
                    }
                )

    results.sort(key=lambda item: item["path"])
    return {"repo": repo, "artifacts": results, "summary": summary}


async def _upsert_artifact(conn, repo_id, path, content, sha, kind, frontmatter):
    """Lê (ou cria) a linha do artefato. Devolve `(row, created)`."""
    row = await conn.fetchrow(
        """
        SELECT * FROM artifacts
         WHERE repo_id = $1 AND path = $2
         FOR UPDATE
        """,
        as_uuid(repo_id),
        path,
    )
    if row is not None:
        return row, False

    artifact_id = _id_from_frontmatter(frontmatter)
    if artifact_id is not None:
        taken = await conn.fetchval("SELECT 1 FROM artifacts WHERE id = $1", artifact_id)
        if taken:
            # Frontmatter com id já usado por outro artefato — gera novo (decisão D5).
            artifact_id = None
    if artifact_id is None:
        artifact_id = await _next_artifact_id(conn, kind)

    timestamp = _now_iso()
    module = frontmatter.get("module") or PurePosixPath(path).parent.name
    feature = frontmatter.get("feature") or PurePosixPath(path).stem
    version = str(frontmatter.get("version") or "1.0.0")
    doubts_index = doubts_index_path(kind, artifact_id)
    doubts_content = render_doubts_template(kind, artifact_id, timestamp)

    inserted = await conn.fetchrow(
        """
        INSERT INTO artifacts
            (id, demand_id, repo_id, kind, module, feature, path, sha,
             status, version, content, doubts_index, doubts_content)
        VALUES ($1, NULL, $2, $3, $4, $5, $6, $7, 'draft', $8, $9, $10, $11)
        ON CONFLICT (repo_id, path) WHERE repo_id IS NOT NULL DO NOTHING
        RETURNING *
        """,
        artifact_id,
        as_uuid(repo_id),
        kind,
        module,
        feature,
        path,
        sha,
        version,
        content,
        doubts_index,
        doubts_content,
    )
    if inserted is not None:
        return inserted, True

    # Outro sync criou a linha no meantime — serializa e lê a versão existente.
    row = await conn.fetchrow(
        """
        SELECT * FROM artifacts
         WHERE repo_id = $1 AND path = $2
         FOR UPDATE
        """,
        as_uuid(repo_id),
        path,
    )
    if row is None:
        raise ApiError("sync_conflict", "artefato criado por outro sync", 409, {"path": path})
    return row, False


def _id_from_frontmatter(frontmatter: dict) -> str | None:
    value = frontmatter.get("id")
    if isinstance(value, str) and ID_PATTERN.match(value):
        return value
    return None


async def _sync_edges(conn, artifact_id: str, frontmatter: dict) -> None:
    """Arestas do grafo a partir do frontmatter (spec §5.8)."""
    edges: list[tuple[str, str]] = []
    created_from = frontmatter.get("createdFrom")
    if isinstance(created_from, str) and created_from:
        edges.append((created_from, "derives_from"))
    for child in frontmatter.get("dependsOn") or []:
        if isinstance(child, str) and child:
            edges.append((child, "depends_on"))
    for child in frontmatter.get("tests") or []:
        if isinstance(child, str) and child:
            edges.append((child, "tests"))

    for child_id, edge_type in edges:
        exists = await conn.fetchval("SELECT 1 FROM artifacts WHERE id = $1", child_id)
        if not exists:
            continue
        await conn.execute(
            """
            INSERT INTO spec_edges (parent_id, child_id, type)
            VALUES ($1, $2, $3)
            ON CONFLICT (parent_id, child_id, type) DO NOTHING
            """,
            artifact_id,
            child_id,
            edge_type,
        )


# --------------------------------------------------------------------------
# Transições de artefato
# --------------------------------------------------------------------------
async def _lint_for_artifact(pool, artifact: dict):
    """Lint estrutural do artefato — `None` se o linter (F2) não existir."""
    universe = build_universe(pool)
    if universe is None:
        return None
    frontmatter, body = parse_frontmatter(artifact.get("content") or "")
    return _lint_doc(
        artifact.get("path") or "",
        artifact.get("content") or "",
        frontmatter,
        body,
        artifact.get("kind"),
        artifact.get("repo_id"),
        universe,
    )


async def request_review(pool, *, artifact_id: str, actor_id: str) -> dict:
    artifact = await get_artifact(pool, artifact_id)
    if artifact is None:
        raise ApiError("not_found", "artefato inexistente", 404, {"id": artifact_id})

    findings = await _lint_for_artifact(pool, artifact)
    if findings is not None:
        errors = [f for f in findings if getattr(f, "severity", None) == "error"]
        if errors:
            raise ApiError(
                "lint_failed",
                "lint estrutural reprovou o artefato",
                409,
                {"findings": [_finding_dict(f) for f in errors]},
            )

    open_doubts = await fetch(
        pool,
        "SELECT id FROM doubts WHERE artifact_id = $1 AND status = 'pending'",
        artifact_id,
    )
    if open_doubts:
        raise ApiError(
            "open_doubts",
            "o artefato tem dúvidas pendentes",
            409,
            {"doubts": [str(d["id"]) for d in open_doubts]},
        )

    return await apply_artifact_transition(
        pool,
        artifact_id,
        "on user review",
        actor_id=actor_id,
        event_type="artifact.review_requested",
    )


async def approve(pool, *, artifact_id: str, actor_id: str) -> dict:
    """`on user review` → `on agents review` + pipeline do F6.

    O 503 do pipeline indisponível **não** muda status: a transição só é
    aplicada depois que o F6 existe (contrato §8.1).
    """
    artifact = await get_artifact(pool, artifact_id)
    if artifact is None:
        raise ApiError("not_found", "artefato inexistente", 404, {"id": artifact_id})
    if artifact.get("status") != "on user review":
        raise ApiError(
            "illegal_transition",
            f"{artifact.get('status')} -> on agents review",
            409,
            {"from": artifact.get("status"), "to": "on agents review"},
        )

    try:
        from app.services import reviewers  # F6 — import tardio
    except ImportError:
        raise ApiError(
            "pipeline_unavailable",
            "pipeline de aprovação indisponível",
            503,
            {"id": artifact_id},
        ) from None

    await apply_artifact_transition(
        pool,
        artifact_id,
        "on agents review",
        actor_id=actor_id,
        event_type="artifact.agents_review_started",
    )
    result = await reviewers.run_pipeline(artifact)
    to_dict = getattr(result, "to_dict", None)
    return {
        "artifact": await get_artifact(pool, artifact_id),
        "pipeline": to_dict() if to_dict else result,
    }


async def stabilize(pool, *, artifact_id: str, actor_id: str) -> dict:
    """`approved` → `stable`. Exige ≥1 RI ligado por `tests` (decisão D2)."""
    artifact = await get_artifact(pool, artifact_id)
    if artifact is None:
        raise ApiError("not_found", "artefato inexistente", 404, {"id": artifact_id})

    row = await fetchrow(
        pool,
        """
        SELECT e.child_id
          FROM spec_edges e
          JOIN artifacts c ON c.id = e.child_id
         WHERE e.parent_id = $1 AND e.type = 'tests' AND c.kind = 'ri'
         LIMIT 1
        """,
        artifact_id,
    )
    if row is None:
        raise ApiError(
            "ri_required",
            "o artefato não tem RI ligado por 'tests'",
            409,
            {"id": artifact_id},
        )

    return await apply_artifact_transition(
        pool,
        artifact_id,
        "stable",
        actor_id=actor_id,
        event_type="artifact.stabilized",
    )
