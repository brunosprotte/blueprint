"""Testes de bootstrap da fase F1 — saúde, migrations, tokens, escopos, eventos e SSE."""

from __future__ import annotations

import hashlib
import json
import uuid

from app import db
from app.auth import ALL_USER_SCOPES, generate_token, hash_token
from app.config import settings
from app.main import app

ADMIN = "/api/admin/tokens"


def _auth(raw: str) -> dict[str, str]:
    """Cabeçalho de Authorization com um token de API."""
    return {"Authorization": f"Bearer {raw}"}


async def test_health(client):
    """GET /api/health responde 200 com o estado do banco."""
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": True}


async def test_migrations_idempotent(pool):
    """Rodar as migrations 2x não duplica linhas nem erra."""
    before = await pool.fetch("SELECT version FROM schema_migrations ORDER BY version")
    assert before, "nenhuma migration aplicada"

    assert await db.run_migrations(pool) == []
    assert await db.run_migrations(pool) == []

    after = await pool.fetch("SELECT version FROM schema_migrations ORDER BY version")
    assert [r["version"] for r in after] == [r["version"] for r in before]

    tables = await pool.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    names = {r["tablename"] for r in tables}
    assert {
        "users",
        "repos",
        "tokens",
        "sessions",
        "demands",
        "artifacts",
        "spec_edges",
        "doubts",
        "commits",
        "reviews",
        "chunks",
        "events",
        "schema_migrations",
    } <= names


async def test_token_created_and_hashed(client, pool, auth_token):
    """Token criado pela admin: só o sha256 vai pro banco, o bruto autentica."""
    resp = await client.post(
        ADMIN, json={"scopes": ["demand:claim"]}, headers=_auth(auth_token)
    )
    assert resp.status_code == 200
    body = resp.json()
    raw = body["token"]
    assert raw.startswith("sdd_")
    assert body["scopes"] == ["demand:claim"]
    assert uuid.UUID(body["id"])

    row = await pool.fetchrow(
        "SELECT token_hash FROM tokens WHERE id = $1", uuid.UUID(body["id"])
    )
    assert row["token_hash"] == hashlib.sha256(raw.encode()).hexdigest()
    assert raw != row["token_hash"]

    me = await client.get("/api/auth/me", headers=_auth(raw))
    assert me.status_code == 200
    assert me.json()["login"] == "tester"


async def test_token_revoked_401(client, auth_token):
    """Token revogado responde 401."""
    created = await client.post(
        ADMIN, json={"scopes": ["demand:claim"]}, headers=_auth(auth_token)
    )
    raw = created.json()["token"]
    token_id = created.json()["id"]
    assert (await client.get("/api/auth/me", headers=_auth(raw))).status_code == 200

    revoked = await client.delete(f"{ADMIN}/{token_id}", headers=_auth(auth_token))
    assert revoked.status_code == 204

    after = await client.get("/api/auth/me", headers=_auth(raw))
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "token_revoked"


async def test_scope_forbidden(client, pool):
    """Token sem o escopo token:admin recebe 403 na criação de token."""
    raw, token_hash = generate_token()
    user_id = await pool.fetchval(
        "INSERT INTO users (github_id, login) VALUES ($1, $2) RETURNING id",
        999001,
        "limited",
    )
    await pool.execute(
        "INSERT INTO tokens (user_id, token_hash, scopes) VALUES ($1, $2, $3)",
        user_id,
        token_hash,
        ["demand:claim"],
    )

    resp = await client.post(ADMIN, json={"scopes": ["demand:claim"]}, headers=_auth(raw))
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "forbidden"


async def test_events_sse(pool, sse, auth_token):
    """O stream SSE emite os eventos existentes com id incremental."""
    event_id = await pool.fetchval(
        "INSERT INTO events (type, payload) VALUES ($1, $2::jsonb) RETURNING id",
        "demand.created",
        json.dumps({"title": "demanda de teste"}),
    )

    status, headers, body = await sse("/api/events/stream", _auth(auth_token))

    assert status == 200
    assert any(h[0] == b"content-type" and b"text/event-stream" in h[1] for h in headers)
    text = body.decode()
    assert f"id: {event_id}" in text
    assert "data:" in text
    assert "demand.created" in text


async def test_events_list(pool, client, auth_token):
    """GET /api/events devolve os eventos filtrados por demanda."""
    demand_id = await pool.fetchval(
        "INSERT INTO demands (title, created_by) "
        "SELECT $1, id FROM users WHERE login = 'tester' RETURNING id",
        "demanda listada",
    )
    await pool.execute(
        "INSERT INTO events (demand_id, type, payload) VALUES ($1, $2, $3::jsonb)",
        demand_id,
        "claim",
        json.dumps({"repo": "owner/name"}),
    )

    resp = await client.get("/api/events", params={"demand": str(demand_id)}, headers=_auth(auth_token))
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert len(events) == 1
    assert events[0]["type"] == "claim"
    assert events[0]["demand_id"] == str(demand_id)
    assert events[0]["payload"] == {"repo": "owner/name"}
    assert set(events[0]) == {"id", "demand_id", "artifact_id", "type", "payload", "at"}


async def test_routers_registered():
    """Todas as rotas /api do F1 existem — sem 404 por typo."""
    paths = set(app.openapi()["paths"])
    expected = {
        "/api/health",
        "/api/auth/github",
        "/api/auth/github/callback",
        "/api/auth/logout",
        "/api/auth/me",
        "/api/auth/dev-login",
        "/api/admin/tokens",
        "/api/admin/tokens/{token_id}",
        "/api/events",
        "/api/events/stream",
    }
    assert expected <= paths


async def test_request_id_header(client):
    """Toda resposta tem X-Request-Id e o valor é único por request."""
    first = await client.get("/api/health")
    second = await client.get("/api/health")
    assert first.headers["X-Request-Id"]
    assert second.headers["X-Request-Id"]
    assert first.headers["X-Request-Id"] != second.headers["X-Request-Id"]
    uuid.UUID(first.headers["X-Request-Id"])


async def test_error_envelope(client):
    """Erro de auth usa o envelope único do contrato §3."""
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401
    assert set(resp.json()["error"]) == {"code", "message", "detail"}
    assert resp.headers["X-Request-Id"]


def test_generate_token_roundtrip():
    """generate_token devolve (raw, sha256) — o bruto nunca é o hash."""
    raw, token_hash = generate_token()
    assert raw.startswith("sdd_")
    assert token_hash == hash_token(raw)
    assert token_hash == hashlib.sha256(raw.encode()).hexdigest()
    assert raw != token_hash
    assert hash_token(raw) == hash_token(raw)


def test_all_user_scopes_contains_token_admin():
    """A sessão web tem todos os escopos, incluindo token:admin."""
    assert "token:admin" in ALL_USER_SCOPES
    assert set(ALL_USER_SCOPES) == {
        "demand:claim",
        "demand:write",
        "artifact:sync",
        "artifact:approve",
        "review:write",
        "token:admin",
    }


async def test_dev_login_disabled_by_default(client):
    """Sem SDD_ALLOW_DEV_AUTH a rota dev-login responde 404."""
    resp = await client.post("/api/auth/dev-login", json={"login": "dev"})
    assert resp.status_code == 404


async def test_dev_login_creates_session(client, monkeypatch):
    """Com dev auth ligado, dev-login cria sessão e o cookie autentica."""
    monkeypatch.setattr(settings, "allow_dev_auth", True)
    resp = await client.post("/api/auth/dev-login", json={"login": "dev"})
    assert resp.status_code == 200
    assert "sdd_session" in resp.cookies

    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["login"] == "dev"


async def test_github_redirect(client, monkeypatch):
    """GET /api/auth/github redireciona pro GitHub sem chamar a rede."""
    monkeypatch.setattr(settings, "github_client_id", "client-id-de-teste")
    resp = await client.get("/api/auth/github", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"].startswith("https://github.com/login/oauth/authorize")
    assert "client_id=client-id-de-teste" in resp.headers["location"]
