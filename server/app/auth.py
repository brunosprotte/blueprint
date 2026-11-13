"""Autenticação e autorização — token de API, sessão via GitHub OAuth e escopos.

Única fonte de identidade do servidor (Contrato Comum §6). O token bruto
(`sdd_...`) nunca é persistido nem logado: só o sha256 vai para `tokens`.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from typing import Any, Callable, Mapping

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from app import db
from app.config import settings
from app.models import Token, User

ALL_USER_SCOPES: tuple[str, ...] = (
    "demand:claim",
    "demand:write",
    "artifact:sync",
    "artifact:approve",
    "review:write",
    "token:admin",
)

SESSION_COOKIE = "sdd_session"
OAUTH_STATE_COOKIE = "sdd_oauth_state"
SESSION_TTL_SECONDS = 7 * 24 * 3600

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"

router = APIRouter(prefix="/auth", tags=["auth"])


# --- envelope de erro (Contrato Comum §3) ------------------------------------


def error_detail(code: str, message: str, **detail: Any) -> dict[str, Any]:
    """Corpo do erro no formato `{"code", "message", "detail"}`."""
    return {"code": code, "message": message, "detail": detail}


def unauthorized(code: str, message: str, **detail: Any) -> HTTPException:
    """Erro 401 — credencial ausente ou inválida."""
    return HTTPException(401, detail=error_detail(code, message, **detail))


def forbidden(code: str, message: str, **detail: Any) -> HTTPException:
    """Erro 403 — credencial válida sem permissão."""
    return HTTPException(403, detail=error_detail(code, message, **detail))


async def _pool():
    """Pool do Postgres; 503 se o servidor não subiu."""
    try:
        return await db.get_pool()
    except RuntimeError as exc:
        raise HTTPException(
            503, detail=error_detail("database_unavailable", str(exc))
        ) from exc


# --- token de API -----------------------------------------------------------


def hash_token(raw: str) -> str:
    """sha256 hex do token bruto — é o que vai para `tokens.token_hash`."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_token() -> tuple[str, str]:
    """Cria um token opaco: devolve `(bruto, sha256)`."""
    raw = "sdd_" + secrets.token_urlsafe(32)
    return raw, hash_token(raw)


async def _token_by_raw(raw: str) -> Token:
    """Procura o token pelo hash; 401 se não existir, estiver revogado ou for inválido."""
    pool = await _pool()
    row = await db.fetchrow(
        pool,
        """
        SELECT id, user_id, repo_id, scopes, revoked_at
          FROM tokens
         WHERE token_hash = $1
        """,
        hash_token(raw),
    )
    if row is None:
        raise unauthorized("invalid_token", "token desconhecido")
    if row["revoked_at"] is not None:
        raise unauthorized("token_revoked", "token revogado")
    return Token.from_row(row)


# --- sessão (cookie assinado) ----------------------------------------------


def sign_session(session_id: str) -> str:
    """Assina um identificador: `f"{session_id}.{hmac_sha256(session_id)}"`."""
    mac = hmac.new(
        settings.secret_key.encode("utf-8"),
        session_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{session_id}.{mac}"


def verify_session_value(value: str) -> str | None:
    """Devolve o `session_id` se a assinatura conferir, senão None."""
    session_id, _, mac = value.partition(".")
    if not session_id or not mac:
        return None
    expected = hmac.new(
        settings.secret_key.encode("utf-8"),
        session_id.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(mac, expected):
        return None
    return session_id


def _secure_cookies() -> bool:
    """`secure=True` quando o servidor roda atrás de https."""
    return settings.base_url.startswith("https://")


def set_session_cookie(response: Response, session_id: str) -> None:
    """Grava o cookie de sessão `sdd_session`."""
    response.set_cookie(
        SESSION_COOKIE,
        sign_session(session_id),
        httponly=True,
        samesite="lax",
        secure=_secure_cookies(),
        path="/",
        max_age=SESSION_TTL_SECONDS,
    )


async def create_session(user_id: str) -> str:
    """Cria a linha em `sessions` (7 dias) e devolve o `session_id`."""
    pool = await _pool()
    session_id = secrets.token_urlsafe(32)
    await db.execute(
        pool,
        """
        INSERT INTO sessions (id, user_id, expires_at)
        VALUES ($1, $2, now() + interval '7 days')
        """,
        session_id,
        uuid.UUID(user_id),
    )
    return session_id


# --- resolução de credenciais ----------------------------------------------


async def _user_by_id(user_id: str) -> User:
    pool = await _pool()
    row = await db.fetchrow(
        pool,
        "SELECT id, github_id, login, email, avatar_url FROM users WHERE id = $1",
        uuid.UUID(user_id),
    )
    if row is None:
        raise unauthorized("unknown_user", "usuário da credencial não existe")
    return User.from_row(row)


async def resolve_identity(request: Request) -> tuple[User, Token | None]:
    """Resolve a credencial do request: Bearer tem prioridade sobre o cookie.

    Devolve `(usuário, token)`. O token é `None` quando a credencial é uma
    sessão web — sessão tem todos os escopos de usuário.
    """
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        raw = header[len("bearer ") :].strip()
        if not raw:
            raise unauthorized("invalid_token", "Bearer vazio")
        token = await _token_by_raw(raw)
        return await _user_by_id(token.user_id), token

    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        session_id = verify_session_value(cookie)
        if session_id is None:
            raise unauthorized("invalid_session", "assinatura de sessão inválida")
        pool = await _pool()
        row = await db.fetchrow(
            pool,
            """
            SELECT id, user_id
              FROM sessions
             WHERE id = $1 AND expires_at > now()
            """,
            session_id,
        )
        if row is None:
            raise unauthorized("invalid_session", "sessão expirada ou inexistente")
        return await _user_by_id(str(row["user_id"])), None

    raise unauthorized(
        "missing_credentials",
        "Authorization: Bearer sdd_... ou cookie sdd_session obrigatório",
    )


async def require_user(request: Request) -> User:
    """Dependência: exige credencial válida e devolve o usuário."""
    user, _ = await resolve_identity(request)
    return user


def require_scope(scope: str) -> Callable[..., Token]:
    """Dependência: exige o escopo. Token sem o escopo → 403."""

    async def dependency(request: Request) -> Token:
        user, token = await resolve_identity(request)
        if token is None:
            # Sessão web tem todos os escopos de usuário.
            return Token(
                id="session",
                user_id=user.id,
                repo_id=None,
                scopes=ALL_USER_SCOPES,
            )
        if scope not in token.scopes:
            raise forbidden(
                "forbidden", f"escopo ausente: {scope}", required_scope=scope
            )
        return token

    return dependency


async def current_repo(request: Request) -> str:
    """Repo do token em `owner/name`; string vazia quando o token vale para todos."""
    _, token = await resolve_identity(request)
    if token is None or not token.repo_id:
        return ""
    pool = await _pool()
    row = await db.fetchrow(
        pool, "SELECT owner, name FROM repos WHERE id = $1", uuid.UUID(token.repo_id)
    )
    if row is None:
        return ""
    return f"{row['owner']}/{row['name']}"


# --- OAuth GitHub -----------------------------------------------------------


async def exchange_github_code(code: str) -> dict[str, Any]:
    """Troca o `code` pelo token do GitHub e devolve `{access_token, user}`."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            token_resp = await client.post(
                GITHUB_TOKEN_URL,
                data={
                    "client_id": settings.github_client_id or "",
                    "client_secret": settings.github_client_secret or "",
                    "code": code,
                },
                headers={"Accept": "application/json"},
            )
            token_resp.raise_for_status()
            user_resp = await client.get(
                GITHUB_USER_URL,
                headers={
                    "Authorization": f"Bearer {token_resp.json().get('access_token', '')}",
                    "Accept": "application/json",
                },
            )
            user_resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(
                503,
                detail=error_detail("github_unavailable", f"GitHub inacessível: {exc}"),
            ) from exc

    access_token = token_resp.json().get("access_token")
    if not access_token:
        raise HTTPException(
            400,
            detail=error_detail("github_oauth_failed", "GitHub não devolveu access_token"),
        )
    return {"access_token": access_token, "user": user_resp.json()}


async def upsert_github_user(profile: Mapping[str, Any]) -> User:
    """Cria ou atualiza o usuário pelo `id` do GitHub."""
    pool = await _pool()
    row = await db.fetchrow(
        pool,
        """
        INSERT INTO users (github_id, login, email, avatar_url)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (github_id) DO UPDATE
           SET login = EXCLUDED.login,
               email = EXCLUDED.email,
               avatar_url = EXCLUDED.avatar_url
        RETURNING id, github_id, login, email, avatar_url
        """,
        int(profile["id"]),
        profile.get("login") or "github-user",
        profile.get("email"),
        profile.get("avatar_url"),
    )
    return User.from_row(row)


# --- rotas ------------------------------------------------------------------


@router.get("/github")
async def github_login() -> RedirectResponse:
    """Redireciona pro GitHub (Authorization Code)."""
    if not settings.github_client_id:
        raise HTTPException(
            503,
            detail=error_detail(
                "github_not_configured", "SDD_GITHUB_CLIENT_ID não configurado"
            ),
        )
    state = secrets.token_urlsafe(24)
    redirect_uri = f"{settings.base_url.rstrip('/')}/api/auth/github/callback"
    location = (
        f"{GITHUB_AUTHORIZE_URL}"
        f"?client_id={settings.github_client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=repo&state={state}"
    )
    response = RedirectResponse(location, status_code=302)
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        sign_session(state),
        httponly=True,
        samesite="lax",
        secure=_secure_cookies(),
        path="/api/auth",
        max_age=600,
    )
    return response


@router.get("/github/callback")
async def github_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
) -> RedirectResponse:
    """Troca o code por token, cria a sessão e volta pra `/`."""
    stored = request.cookies.get(OAUTH_STATE_COOKIE)
    if not stored or not state or not hmac.compare_digest(stored, sign_session(state)):
        raise HTTPException(
            400, detail=error_detail("invalid_state", "state do OAuth não confere")
        )
    if not code:
        raise HTTPException(
            400, detail=error_detail("missing_code", "code ausente no callback")
        )

    payload = await exchange_github_code(code)
    user = await upsert_github_user(payload["user"])
    session_id = await create_session(user.id)

    response = RedirectResponse("/", status_code=302)
    set_session_cookie(response, session_id)
    response.delete_cookie(OAUTH_STATE_COOKIE, path="/api/auth")
    return response


@router.post("/logout")
async def logout(request: Request) -> Response:
    """Apaga a sessão e limpa o cookie."""
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        session_id = verify_session_value(cookie)
        if session_id:
            pool = await _pool()
            await db.execute(pool, "DELETE FROM sessions WHERE id = $1", session_id)
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/me")
async def me(user: User = Depends(require_user)) -> dict[str, Any]:
    """Usuário da sessão ou do token."""
    return user.to_dict()


@router.post("/dev-login")
async def dev_login(payload: dict[str, Any] | None = None) -> JSONResponse:
    """Login local sem GitHub — só existe com `SDD_ALLOW_DEV_AUTH=true`."""
    if not settings.allow_dev_auth:
        raise HTTPException(
            404, detail=error_detail("not_found", "login de desenvolvimento desabilitado")
        )
    login = str((payload or {}).get("login") or "dev")
    pool = await _pool()
    row = await db.fetchrow(
        pool,
        """
        INSERT INTO users (github_id, login)
        VALUES ($1, $2)
        ON CONFLICT (github_id) DO UPDATE SET login = EXCLUDED.login
        RETURNING id, github_id, login, email, avatar_url
        """,
        -1,
        login,
    )
    user = User.from_row(row)
    session_id = await create_session(user.id)
    response = JSONResponse({"user": user.to_dict()})
    set_session_cookie(response, session_id)
    return response
