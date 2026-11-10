# Fase F1 — Core do Servidor

| Campo | Valor |
| --- | --- |
| **Fase** | F1 |
| **Data** | 2026-11-10 |
| **Depende de** | — |
| **Bloqueia** | F2, F3, F4, F8, F10 |
| **Onda** | 0 (sozinho) |
| **Contrato** | `design/specs/2026-11-10-contrato-comum.md` |

> Reler o **Contrato Comum** antes de começar. Ele define convenções de API, banco,
> env, auth e a matriz de ownership. Esta spec define *o que construir*.

## 1. Objetivo

Levantar o servidor FastAPI com Postgres, schema completo, auth (GitHub OAuth + API token)
e o esqueleto completo de módulos — de modo que F2–F10 possam ser implementadas em
paralelo sem ninguém colidir num mesmo arquivo.

**Critério de sucesso da fase:** `docker compose up` sobe o banco, `uvicorn` sobe o
servidor, `GET /api/health` responde, um token de API é criado pela rota admin e
autentica uma chamada, e todos os routers/services declarados existem como stub.

## 2. Arquivos que esta fase pode criar/editar

```
server/pyproject.toml
server/app/__init__.py
server/app/main.py
server/app/config.py
server/app/db.py
server/app/models.py
server/app/auth.py
server/app/routers/__init__.py
server/app/routers/{method,demands,claims,artifacts,commits,lint,reviews,knowledge,admin,generation}.py
server/app/services/__init__.py
server/app/services/{method,skills,lifecycle,demands,artifacts,claims,commits,generator,reviewers,doubts,indexer,retriever}.py
server/app/lint/__init__.py
server/migrations/001_bootstrap.sql
server/tests/__init__.py
server/tests/conftest.py
server/tests/test_bootstrap.py
db/docker-compose.yml
```

**Não tocar:** `tools/`, `docs/`, `plugin/`, `site/`, qualquer `design/specs/`.

## 3. Contratos a implementar

### 3.1 `db/docker-compose.yml`

Postgres 16, porta 5432, volume persistente, healthcheck, usuário `sdd` / senha `sdd`,
db `sdd`. Extension `vector` (pgvector) instalada no init — a imagem
`pgvector/pgvector:pg16` já traz.

```yaml
services:
  db:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_USER: sdd
      POSTGRES_PASSWORD: sdd
      POSTGRES_DB: sdd
    ports: ["5432:5432"]
    volumes: ["sdd_pgdata:/var/lib/postgresql/data"]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U sdd"]
      interval: 5s
      timeout: 3s
      retries: 10
volumes:
  sdd_pgdata:
```

### 3.2 `server/migrations/001_bootstrap.sql`

DDL **exatamente** como §8 do design master, com os índices de §8.1, mais:

```sql
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    text primary key,
    applied_at timestamptz not null default now()
);
```

Tabela `sessions` do design master: `id text pk, user_id uuid fk references users(id) on delete cascade, expires_at timestamptz not null`.

### 3.3 `server/app/db.py`

```python
POOL: asyncpg.Pool            # criado no startup, fechado no shutdown

async def get_pool() -> asyncpg.Pool: ...
async def run_migrations(pool: asyncpg.Pool) -> list[str]:
    """Aplica server/migrations/*.sql em ordem lexicográfica, ignora já aplicadas."""
async def fetch(pool, query, *args) -> list[asyncpg.Record]: ...
async def fetchrow(pool, query, *args) -> asyncpg.Record | None: ...
async def fetchval(pool, query, *args): ...
async def execute(pool, query, *args) -> str: ...
```

`run_migrations` cria `schema_migrations` se não existir, lê os arquivos com
`Path(__file__).resolve().parents[1] / "migrations"`, ordena por nome, e pra cada um
não aplicado: executa o SQL inteiro num `transaction()` e insere a versão.

### 3.4 `server/app/config.py`

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SDD_", env_file=".env", extra="ignore")
    database_url: str = "postgresql://sdd:sdd@localhost:5432/sdd"
    secret_key: str
    repo_root: Path = Path(__file__).resolve().parents[2]
    base_url: str = "http://localhost:8000"
    github_client_id: str | None = None
    github_client_secret: str | None = None
    allow_dev_auth: bool = False
    llm_model: str = "claude-opus-5-5"
settings = Settings()
```

`secret_key` é obrigatório — sem default. `repo_root` default = raiz do repo blueprint
(parents[2] a partir de `server/app/config.py` → `blueprint/`).

### 3.5 `server/app/auth.py`

```python
@dataclass(frozen=True)
class User:  id: str; github_id: int; login: str; email: str | None; avatar_url: str | None
@dataclass(frozen=True)
class Token: id: str; user_id: str; repo_id: str | None; scopes: tuple[str, ...]

def hash_token(raw: str) -> str: ...          # sha256 hex
def generate_token() -> tuple[str, str]: ...   # (raw, hash) — raw = "sdd_" + token_urlsafe(32)

async def require_user(request) -> User: ...
def require_scope(scope: str) -> Callable: ...
async def current_repo(request) -> str: ...
```

Regras:
- `Authorization: Bearer sdd_...` → token. Ausente → cookie de sessão.
- Token: sha256 do valor cru bate com `tokens.token_hash`? não bate → 401.
- Token revogado (`revoked_at not null`) → 401.
- `require_scope("demand:claim")` → token sem o escopo → 403. Sessão de web (usuário
  logado) tem **todos** os escopos de usuário — só tokens são escopados.
- `SDD_ALLOW_DEV_AUTH=true` → `POST /api/auth/dev-login` cria sessão para um usuário
  de desenvolvimento. Rota só existe se a flag estiver ligada; caso contrário 404.
- Sessão: cookie `sdd_session`, valor `f"{session_id}.{hmac_sha256(session_id)}"`,
  `httpOnly`, `SameSite=Lax`, `secure` quando `base_url` começa com `https://`.
  HMAC com `secret_key`. `sessions.expires_at` = now + 7 dias.

### 3.6 `server/app/models.py`

Dataclasses de domínio (não ORM): `User`, `Token`, `Repo`, `Demand`, `Artifact`,
`Doubt`, `Commit`, `Review`, `Chunk`, `Event`. Cada uma com `from_row(row)` quando
aplicável e `to_dict()` serializando para JSON (datas em ISO 8601, uuid em str).

### 3.7 `server/app/main.py`

```python
app = FastAPI(title="SDD Server", version="0.1.0")

@app.on_event("startup")  → pool = create_pool(settings.database_url); await run_migrations(pool)
@app.on_event("shutdown") → await pool.close()
```

- Middleware que gera e devolve `X-Request-Id`.
- Registra **todos** os routers, com prefixo `/api`:
  `method, demands, claims, artifacts, commits, lint, reviews, knowledge, admin, generation`.
- `GET /api/health` → `{"status": "ok", "db": true}` (ping no banco).
- Monta o app de estático do Docusaurus **depois** das rotas `/api`:
  `app.mount("/", StaticFiles(directory=site/build, html=True), name="site")` — só se
  `site/build` existir (F10 cria). Sem isso, 404 limpo.
- `GET /api/auth/*` definido em `auth.py` via `APIRouter` próprio montado em `main.py`.

### 3.8 Stubs

Todo router: `router = APIRouter()` + docstring `"""Router de <assunto>. Implementado na fase F<n>."""`.
Todo service: docstring com a fase + `__all__: list[str] = []`.

Rotas que **F1 já implementa** (não são stub):

| Rota | Fase | Comportamento |
| --- | --- | --- |
| `GET /api/health` | F1 | `{"status":"ok","db":true}` |
| `GET /api/auth/github` | F1 | 302 pro `https://github.com/login/oauth/authorize?...` |
| `GET /api/auth/github/callback` | F1 | troca code por token, cria sessão, 302 pro `/` |
| `POST /api/auth/logout` | F1 | apaga sessão, 204 |
| `GET /api/auth/me` | F1 | usuário da sessão/token, 401 se não houver |
| `POST /api/auth/dev-login` | F1 | só se `allow_dev_auth` |
| `POST /api/admin/tokens` | F1 | cria token, devolve `{"token": "sdd_...", "id": ..., "scopes": [...]}` **uma única vez** |
| `DELETE /api/admin/tokens/{id}` | F1 | revoga, 204 |
| `GET /api/events` | F1 | eventos com filtro `demand`/`since` |
| `GET /api/events/stream` | F1 | SSE: a cada 2s emite eventos novos desde o último id |

`POST /api/admin/tokens` exige `require_scope("token:admin")` — sessão web tem escopo
total; token só cria token se tiver `token:admin`.

## 4. Tarefas

1. `server/pyproject.toml` — deps: `fastapi`, `uvicorn[standard]`, `asyncpg`,
   `pydantic`, `pydantic-settings`, `httpx`, `pyyaml`. Dev: `pytest`, `pytest-asyncio`,
   `pytest-cov`. `requires-python = ">=3.12"`. Entry point `sdd-server = "app.main:app"`.
   `tool.pytest.ini_options` com `asyncio_mode = "auto"` e `testpaths = ["tests"]`.
2. `db/docker-compose.yml` (acima).
3. `server/migrations/001_bootstrap.sql` — DDL do design master §8 + §8.1 + `schema_migrations`.
4. `server/app/config.py`.
5. `server/app/db.py` — pool, `run_migrations`, helpers.
6. `server/app/models.py`.
7. `server/app/auth.py` — hash, geração, deps, OAuth, dev-login.
8. `server/app/routers/admin.py` — tokens, events, SSE.
9. `server/app/main.py` — app, lifespan, middleware, routers, estático, `/api/health`.
10. **Todos os stubs** de routers e services (§3.8 e matriz do contrato §8).
11. `server/tests/conftest.py` — fixtures:
    - `settings` com `SDD_SECRET_KEY` de teste via `monkeypatch`/env
    - `pool` — Postgres de teste, migrations aplicadas, **truncada por teste**
    - `client` — `httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")`
    - `auth_token` — token real inserido no banco
    - marca `postgres` para `pytest.skip` se o banco não estiver de pé (`docker compose up -d`).
12. `server/tests/test_bootstrap.py` — ver §5.

## 5. Critérios de aceitação

- [ ] `docker compose -f db/docker-compose.yml up -d` sobe e `psql` conecta.
- [ ] `pip install -e "server[dev]"` e `uvicorn app.main:app --app-dir server` sobem.
- [ ] `GET /api/health` → 200 `{"status":"ok","db":true}`.
- [ ] `run_migrations` rodando duas vezes não duplica nada e não erra.
- [ ] `POST /api/admin/tokens` devolve `sdd_...` uma vez; o valor bruto nunca é
      gravado em log nem em banco — só o sha256.
- [ ] `Authorization: Bearer sdd_...` autentica `GET /api/auth/me`.
- [ ] Token com escopo `demand:claim` chamando rota que exige `token:admin` → 403.
- [ ] Token revogado → 401.
- [ ] `GET /api/events/stream` emite SSE com `data: {...}` e `id:` incremental.
- [ ] Todos os 10 routers e 13 services existem e são importáveis.
- [ ] `pytest server/tests` verde.

## 6. Testes (`server/tests/test_bootstrap.py`)

| Teste | Verifica |
| --- | --- |
| `test_health` | 200 + `db: true` |
| `test_migrations_idempotent` | rodar 2× → mesmas tabelas, `schema_migrations` com 1 linha |
| `test_token_created_and_hashed` | banco guarda só sha256; raw funciona como Bearer |
| `test_token_revoked_401` | revogar → 401 |
| `test_scope_forbidden` | escopo ausente → 403 |
| `test_events_sse` | stream emite evento criado antes |
| `test_routers_registered` | todas as rotas `/api/...` listadas em `app.routes` sem 404 por typo |
| `test_request_id_header` | header presente e único por request |

## 7. Fora de escopo

Gerar BR/SPEC, linter, RAG, Docusaurus, plugin, hook. F1 entrega **infraestrutura**.

## 8. Referências

- Contrato Comum §2, §3, §4, §5, §6, §8.
- Design master §7 (árvore do servidor), §8 (modelo de dados), §16 (auth), §17 (API).
- `docs/META/META-005` §"Convenção de arquivos" — os routers F4+ registram eventos
  com o mesmo formato de `events`.
