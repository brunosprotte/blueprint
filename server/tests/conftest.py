"""Fixtures da fase F1 — banco de teste, app ASGI e tokens reais."""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress
from urllib.parse import urlsplit, urlunsplit

# O banco de teste é SEMPRE separado do banco de dev: a suíte trunca tabelas.
TEST_DSN = os.environ.get(
    "SDD_TEST_DATABASE_URL", "postgresql://sdd:sdd@localhost:5432/sdd_test"
)
os.environ["SDD_DATABASE_URL"] = TEST_DSN
os.environ.setdefault("SDD_SECRET_KEY", "test-secret-key-f1")

import asyncpg  # noqa: E402
import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app import db  # noqa: E402
from app.auth import ALL_USER_SCOPES, generate_token  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

TRUNCATE_EXCLUDE = {"schema_migrations"}


@pytest.fixture
def settings_fixture() -> "settings":
    """Settings do servidor já carregadas com SDD_SECRET_KEY de teste."""
    return settings


@pytest_asyncio.fixture(scope="session")
async def _test_database() -> str:
    """Garante que o banco de teste existe (pulando a suíte se o Postgres não estiver de pé)."""
    parts = urlsplit(TEST_DSN)
    admin_dsn = urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, parts.fragment))
    db_name = parts.path.lstrip("/")
    try:
        conn = await asyncpg.connect(admin_dsn)
    except Exception as exc:  # pragma: no cover - depende do ambiente
        pytest.skip(f"Postgres indisponível em {parts.netloc}: {exc}")
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{db_name}"')
    finally:
        await conn.close()
    return TEST_DSN


async def _truncate(pool: asyncpg.Pool) -> None:
    rows = await pool.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    )
    names = [r["tablename"] for r in rows if r["tablename"] not in TRUNCATE_EXCLUDE]
    if names:
        quoted = ", ".join(f'"{n}"' for n in names)
        await pool.execute(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")


@pytest_asyncio.fixture
async def pool(_test_database: str) -> asyncpg.Pool:
    """Pool do Postgres de teste, com migrations aplicadas e tabelas truncadas."""
    pool = await asyncpg.create_pool(TEST_DSN, min_size=1, max_size=5)
    try:
        await db.run_migrations(pool)
        await _truncate(pool)
        db.POOL = pool
        yield pool
    finally:
        db.POOL = None
        await pool.close()


@pytest_asyncio.fixture
async def client(pool: asyncpg.Pool):
    """Cliente httpx sobre o app ASGI (sem lifespan — o pool vem da fixture `pool`)."""
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def auth_token(pool: asyncpg.Pool) -> str:
    """Token de API real gravado no banco (valor cru devolvido)."""
    raw, token_hash = generate_token()
    user_id = await pool.fetchval(
        "INSERT INTO users (github_id, login) VALUES ($1, $2) RETURNING id",
        424242,
        "tester",
    )
    await pool.execute(
        "INSERT INTO tokens (user_id, token_hash, scopes) VALUES ($1, $2, $3)",
        user_id,
        token_hash,
        list(ALL_USER_SCOPES),
    )
    return raw


async def collect_sse(
    path: str,
    headers: dict[str, str] | None = None,
    *,
    timeout: float = 10.0,
) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
    """Lê um stream SSE direto no app ASGI.

    O ASGITransport do httpx bufferiza o corpo inteiro, então um stream
    infinito (SSE) nunca voltaria. Aqui falamos o protocolo ASGI na mão e
    cortamos assim que o primeiro evento chega.
    """
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "state": {},
    }
    queue: asyncio.Queue = asyncio.Queue()
    body = bytearray()
    status: int | None = None
    response_headers: list[tuple[bytes, bytes]] = []
    request_sent = False

    async def receive() -> dict:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.sleep(3600)
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        await queue.put(message)

    task = asyncio.create_task(app(scope, receive, send))
    try:
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout)
            except asyncio.TimeoutError:  # pragma: no cover - stream sem evento
                break
            if message["type"] == "http.response.start":
                status = message["status"]
                response_headers = message.get("headers", [])
            elif message["type"] == "http.response.body":
                body.extend(message.get("body", b""))
                if not message.get("more_body", False) or b"data:" in body:
                    break
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
    assert status is not None, "stream SSE não respondeu"
    return status, response_headers, bytes(body)


@pytest.fixture
def sse():
    """Acesso ao leitor SSE cru (o transport do httpx bufferiza)."""
    return collect_sse
