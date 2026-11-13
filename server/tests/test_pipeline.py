"""Testes do pipeline de aprovação — fase F6.

As fases dependentes (F1, F2, F4, F5) são representadas por **dublês** que
implementam o contrato (Contrato Comum §2, §7.2, §7.3, §7.4). Os dublês são
instalados em `sys.modules` dentro do fixture e removidos no fim do teste
(`monkeypatch`), então nenhum outro módulo de teste do repositório é afetado.

Nada aqui toca Postgres nem a API da Anthropic: o cliente LLM é um fake.
"""

from __future__ import annotations

import json
import sys
import types
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Request

# `app` vive em server/app — coloca `server/` no path (o pacote do F1 ainda
# pode não estar instalado).
SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

NOW = datetime(2026, 11, 10, 12, 34, 56, tzinfo=timezone.utc)

BR_CONTENT = """---
id: BR-013
module: login
feature: login
type: Business Rule
title: Autenticação de usuários
description: Permite autenticação por e-mail e senha.
status: draft
timestamp: "2026-11-10T12:00:00Z"
doubtsIndex: docs/implementation-artifacts/duvidas-br/BR-013.md
version: 1.0.0
generatedBy: SK-001
---

# Objetivo

Permitir que usuários autenticuem.

# Acceptance Criteria

- AC-001: Credenciais válidas devolvem sessão.
- AC-002: Credenciais inválidas devolvem 401.
"""

SPEC_CONTENT = """---
id: SPEC-024
module: login
feature: login-api
type: Functional Specification
title: Endpoint de autenticação
description: Expõe a autenticação por e-mail e senha.
createdBy: SK-002
createdFrom: BR-013
technologyPack: TP-001
status: draft
timestamp: "2026-11-10T12:05:00Z"
doubtsIndex: docs/implementation-artifacts/duvidas-spec/SPEC-024.md
version: 1.0.0
---

# Objetivo

Autenticar o usuário.

# Acceptance Criteria atendidos

- AC-001
"""


# ===========================================================================
# Doublês das fases dependentes
# ===========================================================================


@dataclass(frozen=True)
class _Finding:
    """`app.lint.rules.Finding` (contrato §7.2)."""

    rule: str
    severity: str
    message: str
    path: str | None = None
    line: int | None = None
    detail: dict = field(default_factory=dict)


@dataclass
class _ArtifactDoc:
    """`app.lint.runner.ArtifactDoc` (contrato §7.2)."""

    path: str
    content: str
    frontmatter: dict
    body: str
    kind: str | None = None
    repo_id: str | None = None


@dataclass(frozen=True)
class _Doubt:
    """`app.models.Doubt` (contrato §3 da spec F6)."""

    id: str
    artifact_id: str
    question: str
    status: str
    source: str
    raised_at: datetime | None = None
    resolved_at: datetime | None = None


class _Universe:
    def __init__(self, root: Path | None = None, pool: Any = None):
        self.root = root
        self.pool = pool

    def exists(self, ref: str) -> bool:
        return False

    def resolve(self, ref: str) -> str | None:
        return None


class FakePool:
    """Pool asyncpg em memória — cobre apenas as queries usadas pelo F6."""

    def __init__(self) -> None:
        self.artifacts: dict[str, dict] = {}
        self.doubts: list[dict] = []
        self.events: list[dict] = []
        self.demands: dict[str, dict] = {}
        self.commits: dict[str, dict] = {}
        self.reviews: list[dict] = []
        self._seq = 0

    def _next(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq:04d}"

    # -- API asyncpg ---------------------------------------------------
    async def fetch(self, query: str, *args: Any) -> list[Any]:
        return self._select(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> Any:
        rows = self._select(query, *args)
        return rows[0] if rows else None

    async def fetchval(self, query: str, *args: Any) -> Any:
        rows = self._select(query, *args)
        return rows[0] if rows else None

    async def execute(self, query: str, *args: Any) -> str:
        self._mutate(query, *args)
        return "OK"

    # -- dispatch ------------------------------------------------------
    def _select(self, query: str, *args: Any) -> list[Any]:
        q = " ".join(query.split())
        if q.startswith("INSERT") or q.startswith("UPDATE"):
            return self._mutate(query, *args)
        if "FROM doubts" in q and "JOIN" not in q:
            rows = [d for d in self.doubts if d["artifact_id"] == args[0]]
            rows.sort(key=lambda d: (d["raised_at"], d["id"]))
            return rows
        if "JOIN doubts" in q:
            out = []
            for doubt in self.doubts:
                if doubt["status"] == "cleaned":
                    continue
                artifact = self.artifacts.get(doubt["artifact_id"])
                if artifact and artifact.get("kind") == args[0]:
                    out.append(
                        {
                            "id": artifact["id"],
                            "path": artifact["path"],
                            "updated_at": artifact.get("updated_at"),
                            "open_count": 1,
                        }
                    )
            out.sort(key=lambda r: r["id"])
            return out
        if "FROM artifacts" in q and "kind = 'spec'" in q:
            demand_id, artifact_id = args[0], args[1]
            rows = [
                a
                for a in self.artifacts.values()
                if a.get("demand_id") == demand_id
                and a.get("kind") == "spec"
                and a["id"] != artifact_id
            ]
            rows.sort(key=lambda a: a["id"])
            return rows
        if "FROM artifacts" in q:
            artifact = self.artifacts.get(args[0])
            return [artifact] if artifact else []
        if "FROM demands" in q:
            demand = self.demands.get(args[0])
            return [demand] if demand else []
        if "FROM commits" in q:
            for commit in self.commits.values():
                if commit["repo_id"] == args[0] and commit["sha"] == args[1]:
                    return [commit]
            return []
        if "FROM reviews" in q:
            out = []
            for review in self.reviews:
                if review["demand_id"] != args[0]:
                    continue
                commit = self.commits.get(review["commit_id"], {})
                out.append({**review, "sha": commit.get("sha")})
            out.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
            return out
        raise AssertionError(f"query não suportada pelo FakePool: {q}")

    def _mutate(self, query: str, *args: Any) -> list[Any]:
        q = " ".join(query.split())
        if "INSERT INTO doubts" in q:
            artifact_id, question, status, source = args
            row = {
                "id": self._next("doubt"),
                "artifact_id": artifact_id,
                "question": question,
                "status": status,
                "source": source,
                "raised_at": NOW,
                "resolved_at": None,
            }
            self.doubts.append(row)
            return [row]
        if "UPDATE doubts" in q:
            for doubt in self.doubts:
                if doubt["id"] == args[0]:
                    doubt["status"] = "cleaned"
                    doubt["resolved_at"] = NOW
                    return [doubt]
            return []
        if "INSERT INTO events" in q:
            demand_id, artifact_id, event_type, payload, actor = args
            self.events.append(
                {
                    "id": len(self.events) + 1,
                    "demand_id": demand_id,
                    "artifact_id": artifact_id,
                    "type": event_type,
                    "payload": json.loads(payload) if isinstance(payload, str) else payload,
                    "actor": actor,
                    "at": NOW,
                }
            )
            return []
        if "UPDATE artifacts" in q:
            artifact = self.artifacts.get(args[0])
            if artifact and artifact.get("status") == "on agents review":
                artifact["status"] = args[1]
                artifact["updated_at"] = NOW
            return []
        if "UPDATE demands" in q:
            demand = self.demands.get(args[0])
            if demand:
                demand["status"] = args[1]
            return []
        if "INSERT INTO commits" in q:
            demand_id, repo_id, sha, message, branch, author, files = args
            row = {
                "id": self._next("commit"),
                "demand_id": demand_id,
                "repo_id": repo_id,
                "sha": sha,
                "message": message,
                "branch": branch,
                "author": author,
                "files": files,
                "created_at": NOW,
            }
            self.commits[row["id"]] = row
            return [row]
        if "INSERT INTO reviews" in q:
            commit_id, demand_id, verdict, findings = args
            row = {
                "id": self._next("review"),
                "commit_id": commit_id,
                "demand_id": demand_id,
                "verdict": verdict,
                "findings": findings,
                "created_at": NOW,
            }
            self.reviews.append(row)
            return [row]
        raise AssertionError(f"query não suportada pelo FakePool: {q}")


def _install_doubles(monkeypatch: pytest.MonkeyPatch, state: dict) -> None:
    """Instala os dublês de F1/F2/F4/F5 em `sys.modules` (restaurados no fim)."""
    pool = state["pool"]

    # -- app.config (F1) ------------------------------------------------
    config = types.ModuleType("app.config")
    config.settings = SimpleNamespace(
        repo_root=SERVER_ROOT.parents[1], llm_model="claude-opus-5-5"
    )
    monkeypatch.setitem(sys.modules, "app.config", config)

    # -- app.models (F1) ------------------------------------------------
    models = types.ModuleType("app.models")
    models.Doubt = _Doubt
    monkeypatch.setitem(sys.modules, "app.models", models)

    # -- app.db (F1) ----------------------------------------------------
    db = types.ModuleType("app.db")

    async def get_pool() -> Any:
        return state["pool"]

    async def fetch(p: Any, query: str, *args: Any) -> list[Any]:
        return await p.fetch(query, *args)

    async def fetchrow(p: Any, query: str, *args: Any) -> Any:
        return await p.fetchrow(query, *args)

    async def fetchval(p: Any, query: str, *args: Any) -> Any:
        return await p.fetchval(query, *args)

    async def execute(p: Any, query: str, *args: Any) -> str:
        return await p.execute(query, *args)

    db.get_pool = get_pool
    db.fetch = fetch
    db.fetchrow = fetchrow
    db.fetchval = fetchval
    db.execute = execute
    monkeypatch.setitem(sys.modules, "app.db", db)

    # -- app.lint (F2) --------------------------------------------------
    lint = types.ModuleType("app.lint")
    lint.Finding = _Finding
    lint.ArtifactDoc = _ArtifactDoc
    lint.MethodCorpus = _Universe
    lint.SyncedArtifacts = _Universe
    lint.CompositeUniverse = _Universe

    def lint_batch(docs: list[Any], universe: Any) -> list[Any]:
        return list(state["lint_findings"])

    lint.lint_batch = lint_batch
    monkeypatch.setitem(sys.modules, "app.lint", lint)

    # -- app.services.generator (F5) ------------------------------------
    generator = types.ModuleType("app.services.generator")

    class LLMUnavailable(RuntimeError):
        """LLM indisponível."""

    generator.LLMUnavailable = LLMUnavailable

    def build_client() -> Any:
        raise LLMUnavailable("sem credencial")

    generator.build_client = build_client

    class _MethodContext:
        documents: tuple = ()

    def resolve_method_context(**kwargs: Any) -> _MethodContext:
        return _MethodContext()

    generator.resolve_method_context = resolve_method_context
    monkeypatch.setitem(sys.modules, "app.services.generator", generator)

    # -- app.services.lifecycle (F4) ------------------------------------
    lifecycle = types.ModuleType("app.services.lifecycle")

    class IllegalTransition(Exception):
        code = "illegal_transition"
        http_status = 409

        def __init__(self, entity: str, current: str, target: str):
            super().__init__(f"{current} -> {target}")
            self.entity = entity
            self.current = current
            self.target = target

    async def apply_artifact_transition(p: Any, artifact_id: str, target: str) -> str:
        artifact = p.artifacts.get(artifact_id)
        if artifact is None:
            raise IllegalTransition("artifact", "?", target)
        if artifact["status"] != "on agents review":
            raise IllegalTransition("artifact", artifact["status"], target)
        artifact["status"] = target
        return target

    async def apply_demand_transition(p: Any, demand_id: str, target: str) -> str:
        demand = p.demands.get(demand_id)
        if demand is None:
            raise IllegalTransition("demand", "?", target)
        current = demand["status"]
        if (current, target) not in {("in_progress", "review"), ("review", "in_progress")}:
            raise IllegalTransition("demand", current, target)
        demand["status"] = target
        return target

    lifecycle.IllegalTransition = IllegalTransition

    def can_transition(table: str, current: str, target: str) -> bool:
        if table == "demand":
            return (current, target) in {
                ("in_progress", "review"),
                ("review", "in_progress"),
            }
        if table == "artifact":
            return (current, target) in {("on agents review", "approved")}
        return False

    lifecycle.can_transition = can_transition
    lifecycle.apply_artifact_transition = apply_artifact_transition
    lifecycle.apply_demand_transition = apply_demand_transition
    monkeypatch.setitem(sys.modules, "app.services.lifecycle", lifecycle)

    # -- app.auth (F1) --------------------------------------------------
    auth = types.ModuleType("app.auth")

    @dataclass(frozen=True)
    class User:
        id: str
        github_id: int
        login: str
        email: str | None = None
        avatar_url: str | None = None

    @dataclass(frozen=True)
    class Token:
        id: str
        user_id: str
        repo_id: str | None
        scopes: tuple[str, ...]

    # `request` precisa da anotação `Request` — com `Any`, o FastAPI trata
    # como query param e a rota responde 422.
    async def require_user(request: Request) -> "User":
        return User(id="user-1", github_id=1, login="tester")

    def require_scope(scope: str):
        async def _dependency(request: Request) -> "Token":
            # `X-Token-Scopes` simula um token sem o escopo pedido (403).
            granted = request.headers.get("x-token-scopes")
            if granted is not None and scope not in [
                s.strip() for s in granted.split(",") if s.strip()
            ]:
                from fastapi import HTTPException

                raise HTTPException(
                    status_code=403,
                    detail={"code": "forbidden", "message": f"escopo {scope} ausente"},
                )
            return Token(id="token-1", user_id="user-1", repo_id=None, scopes=(scope,))

        return _dependency

    auth.User = User
    auth.Token = Token
    auth.require_user = require_user
    auth.require_scope = require_scope
    monkeypatch.setitem(sys.modules, "app.auth", auth)


# ===========================================================================
# Cliente Anthropic falso
# ===========================================================================


@dataclass
class _Block:
    type: str
    text: str = ""


@dataclass
class _Final:
    stop_reason: str
    content: list


_TITLES = {
    "blind-hunter": "Blind Hunter",
    "edge-case-hunter": "Edge Case Hunter",
    "acceptance-auditor": "Acceptance Auditor",
}


class _FakeStream:
    def __init__(self, response: Any):
        self._response = response

    async def __aenter__(self) -> "_FakeStream":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def get_final_message(self) -> _Final:
        response = self._response
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, dict) and "error" in response:
            raise response["error"]
        payload = response.get("payload", {"findings": []})
        text = payload if isinstance(payload, str) else json.dumps(payload)
        return _Final(
            stop_reason=response.get("stop_reason", "end_turn"),
            content=[_Block("text", text)],
        )


class _FakeMessages:
    def __init__(self, client: "FakeClient"):
        self._client = client

    def stream(self, **kwargs: Any) -> _FakeStream:
        self._client.calls.append(kwargs)
        system = kwargs.get("system", "")
        response = self._client.default
        for slug, title in _TITLES.items():
            if title in system:
                response = self._client.responses.get(slug, self._client.default)
                break
        return _FakeStream(response)


class FakeClient:
    """Cliente Anthropic falso: registra as chamadas e devolve payloads."""

    def __init__(self, responses: dict[str, Any] | None = None, default: Any = None):
        self.responses = responses or {}
        self.default = default if default is not None else {"payload": {"findings": []}}
        self.calls: list[dict] = []
        self.messages = _FakeMessages(self)


def finding(severity: str, title: str = "Achado", ac: str = "AC-001") -> dict:
    return {
        "severity": severity,
        "title": title,
        "detail": "detalhe do achado",
        "ac": ac,
        "suggestion": "sugestão do revisor",
    }


# ===========================================================================
# Fixtures
# ===========================================================================


def _make_artifact(pool: FakePool, **overrides: Any) -> dict:
    artifact = {
        "id": "SPEC-024",
        "demand_id": "demand-1",
        "repo_id": "repo-1",
        "kind": "spec",
        "module": "login",
        "feature": "login-api",
        "path": "docs/SPEC/login/login-api.md",
        "sha": "sha-spec",
        "status": "on agents review",
        "version": "1.0.0",
        "content": SPEC_CONTENT,
        "created_at": NOW,
        "updated_at": NOW,
    }
    artifact.update(overrides)
    pool.artifacts[artifact["id"]] = artifact
    return artifact


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    state = {"pool": FakePool(), "lint_findings": []}
    _install_doubles(monkeypatch, state)
    pool = state["pool"]
    pool.demands["demand-1"] = {
        "id": "demand-1",
        "status": "in_progress",
        "repo_id": "repo-1",
        "title": "Login",
    }
    pool.artifacts["BR-013"] = {
        "id": "BR-013",
        "demand_id": "demand-1",
        "repo_id": "repo-1",
        "kind": "br",
        "module": "login",
        "feature": "login",
        "path": "docs/BR/login/login.md",
        "sha": "sha-br",
        "status": "draft",
        "version": "1.0.0",
        "content": BR_CONTENT,
        "created_at": NOW,
        "updated_at": NOW,
    }
    artifact = _make_artifact(pool)

    from app.services import reviewers  # import tardio: precisa dos dublês

    return SimpleNamespace(
        pool=pool,
        state=state,
        artifact=artifact,
        reviewers=reviewers,
        events=lambda event_type: [e for e in pool.events if e["type"] == event_type],
    )


# ===========================================================================
# Testes — pipeline
# ===========================================================================


@pytest.mark.asyncio
async def test_linter_error_stops_pipeline_before_llm(env):
    """Linter com `error` barra: nenhum LLM é chamado (spec D3)."""
    env.state["lint_findings"] = [
        _Finding(rule="BR-001", severity="error", message="frontmatter ausente")
    ]
    client = FakeClient()

    result = await env.reviewers.run_pipeline(env.artifact, client=client)

    assert client.calls == []
    assert result.verdict == "blocking"
    assert result.llm_available is True
    assert result.approval_ready is False
    assert [s["stage"] for s in result.stages] == ["linter"]
    assert result.linter_findings[0]["rule"] == "BR-001"
    assert any(r.startswith("linter: BR-001 — frontmatter ausente") for r in result.blocking_reasons)


@pytest.mark.asyncio
async def test_linter_warning_becomes_deferred_doubt(env):
    """`warning` do linter vira dúvida `deferred` com `source='linter'`."""
    env.state["lint_findings"] = [
        _Finding(rule="BR-004", severity="warning", message="AC-002 sem cobertura")
    ]

    result = await env.reviewers.run_pipeline(env.artifact, client=FakeClient())

    linter_doubts = [d for d in env.pool.doubts if d["source"] == "linter"]
    assert len(linter_doubts) == 1
    assert linter_doubts[0]["status"] == "deferred"
    assert linter_doubts[0]["question"] == "[BR-004] AC-002 sem cobertura"
    assert result.doubts_written == 1
    # o linter não bloqueia o pipeline: os 3 revisores rodaram
    assert [s["stage"] for s in result.stages] == [
        "linter",
        "blind-hunter",
        "edge-case-hunter",
        "acceptance-auditor",
    ]


@pytest.mark.asyncio
async def test_reviewer_order_is_fixed(env):
    """Ordem Blind -> Edge -> Acceptance, registrada em `pipeline_stage`."""
    client = FakeClient(
        {
            "blind-hunter": {"payload": {"findings": [finding("suggestion", "B")]}},
            "edge-case-hunter": {"payload": {"findings": [finding("suggestion", "E")]}},
            "acceptance-auditor": {"payload": {"findings": [finding("suggestion", "A")]}},
        }
    )

    result = await env.reviewers.run_pipeline(env.artifact, client=client)

    stages = [e["payload"]["stage"] for e in env.events("pipeline_stage")]
    assert stages == ["linter", "blind-hunter", "edge-case-hunter", "acceptance-auditor"]
    assert [f["title"] for f in result.findings] == ["B", "E", "A"]
    assert [r["reviewer"] for r in result.review_artifacts] == [
        "blind-hunter",
        "edge-case-hunter",
        "acceptance-auditor",
    ]


@pytest.mark.asyncio
async def test_reviewer_output_schema_rejected_when_invalid(env):
    """Payload fora do schema -> LLM indisponível -> verdict `pending`."""
    client = FakeClient(
        {
            "blind-hunter": {
                "payload": {
                    "findings": [
                        {"severity": "blocking", "title": "sem ac", "detail": "d"}
                    ]
                }
            }
        }
    )

    result = await env.reviewers.run_pipeline(env.artifact, client=client)

    assert result.verdict == "pending"
    assert result.llm_available is False
    assert result.findings == []
    assert result.doubts_written == 0


@pytest.mark.asyncio
async def test_findings_have_contract_shape(env):
    """Todo achado tem as 5 chaves do contrato §7.4."""
    client = FakeClient(
        {
            "blind-hunter": {"payload": {"findings": [finding("blocking", "X")]}},
        }
    )

    result = await env.reviewers.run_pipeline(env.artifact, client=client)

    assert result.findings
    for item in result.findings:
        assert set(item) == {"severity", "title", "detail", "ac", "suggestion"}
        assert item["severity"] in {"blocking", "suggestion", "deferred"}
        assert isinstance(item["ac"], str)


@pytest.mark.asyncio
async def test_blocking_finding_creates_pending_doubt(env):
    client = FakeClient(
        {"blind-hunter": {"payload": {"findings": [finding("blocking")]}}}
    )

    await env.reviewers.run_pipeline(env.artifact, client=client)

    doubts = [d for d in env.pool.doubts if d["source"] == "reviewer"]
    assert doubts and doubts[0]["status"] == "pending"
    assert doubts[0]["question"] == "[AC-001] Achado — detalhe do achado"


@pytest.mark.asyncio
async def test_suggestion_finding_creates_deferred_doubt(env):
    client = FakeClient(
        {"blind-hunter": {"payload": {"findings": [finding("suggestion")]}}}
    )

    await env.reviewers.run_pipeline(env.artifact, client=client)

    doubts = [d for d in env.pool.doubts if d["source"] == "reviewer"]
    assert doubts and doubts[0]["status"] == "deferred"


@pytest.mark.asyncio
async def test_verdict_clean(env):
    result = await env.reviewers.run_pipeline(env.artifact, client=FakeClient())

    assert result.verdict == "clean"
    assert result.findings == []
    assert result.doubts_written == 0


@pytest.mark.asyncio
async def test_verdict_suggestions(env):
    client = FakeClient(
        {"blind-hunter": {"payload": {"findings": [finding("suggestion")]}}}
    )

    result = await env.reviewers.run_pipeline(env.artifact, client=client)

    assert result.verdict == "suggestions"


@pytest.mark.asyncio
async def test_verdict_blocking(env):
    client = FakeClient(
        {"blind-hunter": {"payload": {"findings": [finding("blocking")]}}}
    )

    result = await env.reviewers.run_pipeline(env.artifact, client=client)

    assert result.verdict == "blocking"
    assert any(r.startswith("achado blocking:") for r in result.blocking_reasons)


@pytest.mark.asyncio
async def test_llm_failure_returns_pending_and_blocks_nothing(env):
    """Falha de LLM: `pending`, nada promovido, duvidas só dos revisores que rodaram."""
    from app.services.generator import LLMUnavailable

    client = FakeClient(
        {
            "blind-hunter": {"payload": {"findings": [finding("suggestion", "B")]}},
            "edge-case-hunter": {"error": LLMUnavailable("proxy fora")},
        }
    )

    result = await env.reviewers.run_pipeline(env.artifact, client=client)

    assert result.verdict == "pending"
    assert result.llm_available is False
    assert result.approval_ready is False
    assert result.artifact_status == "on agents review"
    assert env.pool.artifacts["SPEC-024"]["status"] == "on agents review"
    # só o achado do revisor que rodou virou pendência
    assert [d["source"] for d in env.pool.doubts] == ["reviewer"]
    assert len(env.pool.doubts) == 1
    completed = env.events("pipeline_completed")[0]["payload"]
    assert completed["llm_available"] is False
    assert completed["error_type"] == "LLMUnavailable"


@pytest.mark.asyncio
async def test_review_artifacts_published_with_convention_paths(env):
    client = FakeClient()

    await env.reviewers.run_pipeline(env.artifact, client=client)

    events = env.events("review_artifact_written")
    assert len(events) == 3
    paths = [e["payload"]["path"] for e in events]
    assert paths == [
        "docs/implementation-artifacts/review-login-login-api-blind-hunter.md",
        "docs/implementation-artifacts/review-login-login-api-edge-case-hunter.md",
        "docs/implementation-artifacts/review-login-login-api-acceptance-auditor.md",
    ]
    for event in events:
        payload = event["payload"]
        assert payload["artifact_id"] == "SPEC-024"
        assert payload["sha"]
        assert payload["content"].startswith("---")


@pytest.mark.asyncio
async def test_doubts_file_published_in_canonical_v1(env):
    client = FakeClient(
        {"blind-hunter": {"payload": {"findings": [finding("blocking")]}}}
    )

    await env.reviewers.run_pipeline(env.artifact, client=client)

    event = env.events("doubts_file_rendered")[0]["payload"]
    content = event["content"]
    assert event["artifact_id"] == "SPEC-024"
    assert event["path"] == "docs/implementation-artifacts/duvidas-spec/SPEC-024.md"
    assert content.startswith("---\nid: SPEC-024\nartifactId: SPEC-024\n")
    assert "status: pending" in content
    assert 'updatedAt: "' in content
    assert "# Dúvidas — SPEC-024" in content
    assert "Pendências: 1" in content
    assert (
        "| id | status | source | question | raised_at | resolved_at |" in content
    )
    assert "| --- | --- | --- | --- | --- | --- |" in content


@pytest.mark.asyncio
async def test_doubts_file_reflects_final_artifact_status(env):
    """O arquivo de dúvidas é publicado **depois** da promoção (META-006 §6)."""
    result = await env.reviewers.run_pipeline(env.artifact, client=FakeClient())

    assert result.artifact_status == "approved"
    content = env.events("doubts_file_rendered")[-1]["payload"]["content"]
    assert "status: approved" in content
    assert "Pendências: 0" in content


@pytest.mark.asyncio
async def test_catalog_lists_only_open_artifacts(env):
    """Catálogo só lista artefato com pendência aberta."""
    closed = _make_artifact(
        env.pool,
        id="SPEC-030",
        feature="outro",
        path="docs/SPEC/login/outro.md",
        content=SPEC_CONTENT,
    )
    env.pool.doubts.append(
        {
            "id": "doubt-fechado",
            "artifact_id": closed["id"],
            "question": "já resolvida",
            "status": "cleaned",
            "source": "user",
            "raised_at": NOW,
            "resolved_at": NOW,
        }
    )
    client = FakeClient(
        {"blind-hunter": {"payload": {"findings": [finding("blocking")]}}}
    )

    await env.reviewers.run_pipeline(env.artifact, client=client)

    event = env.events("doubts_catalog_rendered")[0]["payload"]
    assert event["kind"] == "spec"
    assert event["path"] == "docs/implementation-artifacts/duvidas-spec.md"
    assert "SPEC-024" in event["content"]
    assert "SPEC-030" not in event["content"]


@pytest.mark.asyncio
async def test_approval_blocked_by_open_doubt(env):
    """Dúvida aberta (mesmo `deferred`) impede a promoção (META-006 §8)."""
    env.pool.doubts.append(
        {
            "id": "doubt-aberto",
            "artifact_id": "SPEC-024",
            "question": "pendência anterior",
            "status": "deferred",
            "source": "user",
            "raised_at": NOW,
            "resolved_at": None,
        }
    )

    result = await env.reviewers.run_pipeline(env.artifact, client=FakeClient())

    assert result.approval_ready is False
    assert result.artifact_status == "on agents review"
    assert env.pool.artifacts["SPEC-024"]["status"] == "on agents review"
    assert "dúvida deferida ainda não resolvida" in result.blocking_reasons


@pytest.mark.asyncio
async def test_approval_succeeds_when_all_cleaned(env):
    """Linter limpo + 3 revisores rodados + nenhuma dúvida -> `approved`."""
    result = await env.reviewers.run_pipeline(env.artifact, client=FakeClient())

    assert result.verdict == "clean"
    assert result.approval_ready is True
    assert result.artifact_status == "approved"
    assert env.pool.artifacts["SPEC-024"]["status"] == "approved"
    completed = env.events("pipeline_completed")[0]["payload"]
    assert completed["approval_ready"] is True
    assert completed["artifact_status"] == "approved"


@pytest.mark.asyncio
async def test_approval_requires_llm_available(env):
    """Com o LLM fora, nada é promovido."""
    from app.services.generator import LLMUnavailable

    client = FakeClient(default={"error": LLMUnavailable("proxy fora")})

    result = await env.reviewers.run_pipeline(env.artifact, client=client)

    assert result.llm_available is False
    assert result.approval_ready is False
    assert result.artifact_status == "on agents review"
    assert env.pool.artifacts["SPEC-024"]["status"] == "on agents review"


# ===========================================================================
# Testes — router de reviews
#
# A matriz de ownership (Contrato Comum §8) restringe o F6 a dois arquivos de
# teste — `test_pipeline.py` e `test_doubts.py` — então os testes das rotas
# (`POST /api/reviews`, `GET /api/reviews`) moram aqui.
# ===========================================================================


def _client(env) -> Any:
    import httpx
    from fastapi import FastAPI

    from app.routers.reviews import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


REVIEW_BODY = {
    "sha": "9f2c1ab4d7e5c6b8a0f1e2d3c4b5a697889900aa",
    "verdict": "clean",
    "findings": [
        {
            "severity": "suggestion",
            "title": "Falta teste de borda",
            "detail": "AC-003 não cobre e-mail com ponto no fim",
            "ac": "AC-003",
            "suggestion": 'Adicionar caso com "a@b."',
        }
    ],
    "demand_id": "demand-1",
    "message": "feat(login): adiciona validação de senha",
    "branch": "feat/login",
    "author": "brunosprotte",
    "files": ["src/auth/login.ts"],
}


@pytest.mark.asyncio
async def test_post_review_creates_review_and_transitions_demand(env):
    async with _client(env) as client:
        response = await client.post("/api/reviews", json=REVIEW_BODY)

    assert response.status_code == 201
    body = response.json()
    assert body["sha"] == REVIEW_BODY["sha"]
    assert body["verdict"] == "clean"
    assert body["demand_status"] == "review"
    assert body["findings"][0]["ac"] == "AC-003"
    assert env.pool.demands["demand-1"]["status"] == "review"
    assert len(env.pool.reviews) == 1
    assert len(env.pool.commits) == 1
    reported = env.events("review_reported")[0]["payload"]
    assert reported["verdict"] == "clean"
    assert reported["findings"] == 1


@pytest.mark.asyncio
async def test_post_review_blocking_transitions_back_to_in_progress(env):
    env.pool.demands["demand-1"]["status"] = "review"
    body = {**REVIEW_BODY, "verdict": "blocking"}

    async with _client(env) as client:
        response = await client.post("/api/reviews", json=body)

    assert response.status_code == 201
    assert response.json()["demand_status"] == "in_progress"
    assert env.pool.demands["demand-1"]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_post_review_demand_not_found(env):
    body = {**REVIEW_BODY, "demand_id": "nao-existe"}

    async with _client(env) as client:
        response = await client.post("/api/reviews", json=body)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert env.pool.reviews == []


@pytest.mark.asyncio
async def test_post_review_empty_sha_is_422(env):
    body = {**REVIEW_BODY, "sha": ""}

    async with _client(env) as client:
        response = await client.post("/api/reviews", json=body)

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_post_review_requires_scope(env):
    async with _client(env) as client:
        response = await client.post(
            "/api/reviews", json=REVIEW_BODY, headers={"X-Token-Scopes": "demand:claim"}
        )

    assert response.status_code == 403
    assert env.pool.reviews == []


@pytest.mark.asyncio
async def test_post_review_illegal_transition_is_409_without_writing(env):
    """Transição ilegal -> 409 e **nada** gravado (sem estado parcial)."""
    from app.services import lifecycle

    lifecycle.can_transition = lambda table, current, target: False

    async with _client(env) as client:
        response = await client.post("/api/reviews", json=REVIEW_BODY)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "illegal_transition"
    assert error["detail"]["current"] == "in_progress"
    assert error["detail"]["target"] == "review"
    assert env.pool.reviews == []
    assert env.pool.commits == {}
    assert env.pool.events == []


@pytest.mark.asyncio
async def test_post_review_without_lifecycle_keeps_demand_status(env):
    """Sem o F4 pronto, o status da demanda não muda (lifecycle é o único
    caminho para escrever status)."""
    import sys as _sys

    monkey_lifecycle = _sys.modules.pop("app.services.lifecycle", None)
    try:
        async with _client(env) as client:
            response = await client.post("/api/reviews", json=REVIEW_BODY)
    finally:
        if monkey_lifecycle is not None:
            _sys.modules["app.services.lifecycle"] = monkey_lifecycle

    assert response.status_code == 201
    assert response.json()["demand_status"] == "in_progress"
    assert env.pool.demands["demand-1"]["status"] == "in_progress"


@pytest.mark.asyncio
async def test_post_review_reuses_commit_for_same_sha(env):
    async with _client(env) as client:
        first = await client.post("/api/reviews", json=REVIEW_BODY)
        second = await client.post("/api/reviews", json=REVIEW_BODY)

    assert first.json()["commit_id"] == second.json()["commit_id"]
    assert len(env.pool.commits) == 1
    assert len(env.pool.reviews) == 2


@pytest.mark.asyncio
async def test_get_reviews_requires_demand_parameter(env):
    async with _client(env) as client:
        response = await client.get("/api/reviews")

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "missing_parameter"
    assert error["detail"] == {"parameter": "demand"}


@pytest.mark.asyncio
async def test_get_reviews_demand_not_found(env):
    async with _client(env) as client:
        response = await client.get("/api/reviews", params={"demand": "nao-existe"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_get_reviews_lists_newest_first(env):
    async with _client(env) as client:
        await client.post("/api/reviews", json=REVIEW_BODY)
        await client.post(
            "/api/reviews", json={**REVIEW_BODY, "sha": "abc123", "findings": []}
        )
        response = await client.get("/api/reviews", params={"demand": "demand-1"})

    assert response.status_code == 200
    body = response.json()
    assert body["demand_id"] == "demand-1"
    assert [r["sha"] for r in body["reviews"]] == ["abc123", REVIEW_BODY["sha"]]
    assert body["reviews"][0]["findings"] == []


@pytest.mark.asyncio
async def test_get_reviews_includes_findings_and_commit_sha(env):
    async with _client(env) as client:
        await client.post("/api/reviews", json=REVIEW_BODY)
        response = await client.get("/api/reviews", params={"demand": "demand-1"})

    review = response.json()["reviews"][0]
    assert review["sha"] == REVIEW_BODY["sha"]
    assert review["findings"][0]["title"] == "Falta teste de borda"
    assert review["created_at"]
