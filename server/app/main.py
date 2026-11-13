"""App FastAPI do servidor SDD — lifecycle, middleware, routers e site estático."""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

import asyncpg
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import db
from app.auth import router as auth_router
from app.config import settings
from app.routers import (
    admin,
    artifacts,
    claims,
    commits,
    demands,
    generation,
    knowledge,
    lint,
    method,
    reviews,
)

API_PREFIX = "/api"

#: Código do envelope de erro por status HTTP (Contrato Comum §3).
ERROR_CODES: dict[int, str] = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    500: "internal_error",
    503: "unavailable",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Sobe o pool e aplica as migrations; fecha o pool no shutdown."""
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=10)
    db.POOL = pool
    try:
        await db.run_migrations(pool)
        yield
    finally:
        db.POOL = None
        await pool.close()


app = FastAPI(title="SDD Server", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Gera um UUID4 por request e devolve no header `X-Request-Id`."""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


def _request_id(request: Request) -> str:
    """Request id gerado pelo middleware (string vazia fora dele)."""
    return getattr(request.state, "request_id", "")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Erro HTTP no envelope único: `{"error": {"code", "message", "detail"}}`."""
    detail = exc.detail
    if isinstance(detail, dict) and "code" in detail:
        error = {
            "code": detail.get("code"),
            "message": detail.get("message", ""),
            "detail": detail.get("detail", {}),
        }
    else:
        error = {
            "code": ERROR_CODES.get(exc.status_code, "error"),
            "message": str(detail),
            "detail": {},
        }
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": error},
        headers={"X-Request-Id": _request_id(request)},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Erro de schema (422) no mesmo envelope."""
    error = {
        "code": "validation_error",
        "message": "payload inválido",
        "detail": {
            "errors": [
                {"loc": list(err.get("loc", [])), "msg": err.get("msg", ""), "type": err.get("type", "")}
                for err in exc.errors()
            ]
        },
    }
    return JSONResponse(
        status_code=422,
        content={"error": error},
        headers={"X-Request-Id": _request_id(request)},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Erro interno não classificado (500) no mesmo envelope."""
    error = {
        "code": "internal_error",
        "message": "erro interno",
        "detail": {"type": type(exc).__name__},
    }
    return JSONResponse(
        status_code=500,
        content={"error": error},
        headers={"X-Request-Id": _request_id(request)},
    )


@app.get("/api/health")
async def health() -> JSONResponse:
    """Estado do servidor e do banco."""
    db_ok = False
    try:
        pool = await db.get_pool()
        db_ok = await db.fetchval(pool, "SELECT 1") == 1
    except Exception:
        db_ok = False
    if not db_ok:
        return JSONResponse(
            status_code=503, content={"status": "degraded", "db": False}
        )
    return JSONResponse({"status": "ok", "db": True})


# Routers — todos com prefixo `/api`. Stubs sem rota não respondem nada.
for _router in (
    method.router,
    demands.router,
    claims.router,
    artifacts.router,
    commits.router,
    lint.router,
    reviews.router,
    knowledge.router,
    admin.router,
    generation.router,
):
    app.include_router(_router, prefix=API_PREFIX)

app.include_router(auth_router, prefix=API_PREFIX)

# Site estático do Docusaurus (F10) — montado por último, em `/`.
_SITE_BUILD = settings.repo_root / "site" / "build"
if _SITE_BUILD.is_dir():
    app.mount("/", StaticFiles(directory=_SITE_BUILD, html=True), name="site")


__all__: list[str] = ["app"]
