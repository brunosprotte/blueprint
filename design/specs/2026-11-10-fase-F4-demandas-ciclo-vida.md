# Fase F4 — Demandas e Ciclo de Vida

| Campo | Valor |
| --- | --- |
| **Fase** | F4 |
| **Data** | 2026-11-10 |
| **Depende de** | F1, F2 |
| **Bloqueia** | F5, F6, F7, F10 |
| **Onda** | 2 (sozinho) |
| **Contrato** | `design/specs/2026-11-10-contrato-comum.md` §7.1, §8.1, §8.2 |

> Reler o **Contrato Comum** §7.1, §8.1 e §8.2 antes de começar. Esta spec define *o que
> construir*; o Contrato Comum define as convenções que prevalecem.

## 1. Objetivo

Entregar o **ciclo de vida** do servidor SDD: a fila de demandas, o **claim atômico**, a
máquina de estados (demanda e artefato), o **sync** repo→servidor e o registro de
commits.

**Critério de sucesso da fase:** dois agentes disputando a mesma demanda → **exatamente um**
vence; `POST /api/artifacts/sync` promove `draft → pending` quando o sha casa e o lint
passa, devolve 409 com os dois hashes quando diverge, e é idempotente; toda transição
gera evento em `events` e passa por `services/lifecycle.py`.

**Fora de escopo:** geração de BR/SPEC (F5), pipeline de revisores (F6), RAG/dossiê (F7),
kit (F8), hook (F9), painel (F10).

## 2. Arquivos que esta fase pode criar/editar

```
server/app/services/lifecycle.py
server/app/services/demands.py
server/app/services/claims.py
server/app/services/artifacts.py
server/app/services/commits.py
server/app/routers/demands.py
server/app/routers/claims.py
server/app/routers/artifacts.py
server/app/routers/commits.py
server/migrations/002_demands.sql
server/migrations/003_artifacts.sql
server/migrations/004_commits.sql
server/tests/test_lifecycle.py
server/tests/test_claim.py
server/tests/test_sync.py
```

**Pode ler, não editar:** `server/app/db.py`, `server/app/config.py`, `server/app/auth.py`,
`server/app/models.py`, `server/app/main.py`, `server/app/lint/` (F2), `server/migrations/001_bootstrap.sql`
(F1), `server/tests/conftest.py` (F1).

**Não tocar:** `tools/`, `docs/`, `skills/`, `server/migrations/001_bootstrap.sql`,
`server/migrations/005_*.sql` (F7), `plugin/`, `site/`, qualquer `design/specs/`.

**Nota de schema.** F1 já cria **todas** as tabelas do design master §8 (`demands`,
`artifacts`, `spec_edges`, `doubts`, `commits`, `reviews`, `events`) em
`001_bootstrap.sql`. As migrations desta fase são **aditivas** (Contrato Comum §4):
índices que faltam e **colunas extras** — nunca reescrevem tabela.

## 3. Contratos a implementar

### 3.1 `server/app/services/lifecycle.py` — dono da máquina de estados

```python
DEMAND_STATUSES = ("open", "claimed", "in_progress", "review", "merged", "done", "blocked")
ARTIFACT_STATUSES = ("draft", "pending", "on user review", "on agents review", "approved", "stable")

DEMAND_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "open":        ("claimed", "blocked"),
    "claimed":     ("in_progress", "open", "blocked"),
    "in_progress": ("review", "blocked"),
    "review":      ("in_progress", "merged", "blocked"),
    "merged":      ("done", "blocked"),
    "done":        ("blocked",),
    "blocked":     ("open",),
}

ARTIFACT_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "draft":            ("pending",),
    "pending":          ("on user review",),
    "on user review":   ("on agents review",),
    "on agents review": ("approved",),
    "approved":         ("stable",),
    "stable":           (),
}

class IllegalTransition(Exception):
    code = "illegal_transition"
    http_status = 409
    def __init__(self, entity: str, current: str, target: str): ...

def can_transition(table: str, current: str, target: str) -> bool: ...
def allowed_targets(table: str, current: str) -> list[str]: ...
```

- `table` ∈ `{"demand", "artifact"}`. `can_transition` com `table`, `current` ou `target`
  inválido → `False` (nunca levanta).
- `allowed_targets` devolve `list` (não tuple), na ordem de `DEMAND_TRANSITIONS`.
- `IllegalTransition.__init__(entity, current, target)` guarda `self.entity`,
  `self.current`, `self.target` e monta `self.message = f"{current} -> {target}"`.

**Transições de demanda (design master §9.1)** — a tabela acima é a implementação exata
dessas regras:

| De | Para | Gatilho | Condição |
| --- | --- | --- | --- |
| — | `open` | `POST /api/demands` | body não vazio |
| `open` | `claimed` | `POST /api/claims` | atômico; token tem `demand:claim`; repo bate |
| `claimed` | `in_progress` | `POST /api/demands/{id}/start` | `claimed_by` == usuário do token |
| `in_progress` | `review` | `POST /api/reviews` (F6) | commit reportada |
| `review` | `in_progress` | `POST /api/reviews` (F6) | `verdict = blocking` |
| `review` | `merged` | `POST /api/demands/{id}/merge` | review mais recente = `clean`/`suggestions` |
| `merged` | `done` | `POST /api/demands/{id}/close` | — |
| `claimed` | `open` | `POST /api/demands/{id}/release` | `claimed_by` == usuário do token |
| qualquer | `blocked` | `POST /api/demands/{id}/block` | motivo obrigatório |

**Transições de artefato (design master §9.2)** — implementadas por
`ARTIFACT_TRANSITIONS` acima; gatilhos:

| De | Para | Gatilho | Condição |
| --- | --- | --- | --- |
| — | `draft` | geração (F5) ou sync | arquivo de dúvidas criado e indexado |
| `draft` | `pending` | `POST /api/artifacts/sync` | sha do arquivo casa com o conteúdo do servidor + lint estrutural passa |
| `pending` | `on user review` | `POST /api/artifacts/{id}/request-review` | ACs completos, sem dúvida `pending` |
| `on user review` | `on agents review` | `POST /api/artifacts/{id}/approve` | usuário autenticado |
| `on agents review` | `approved` | pipeline de aprovação (F6) | 3 revisores rodaram, linter limpo, dúvidas `cleaned` |
| `approved` | `stable` | `POST /api/artifacts/{id}/stabilize` | ≥1 RI passa |

**Aplicação da transição.** O lifecycle é o **único** caminho para escrever status
(invariante 2 do design master §7.1):

```python
async def apply_demand_transition(conn, *, demand_id: str, target: str,
                                  actor_id: str | None,
                                  payload: dict | None = None) -> dict: ...
async def apply_artifact_transition(conn, *, artifact_id: str, target: str,
                                    actor_id: str | None,
                                    payload: dict | None = None) -> dict: ...
```

- Recebem uma **conexão** (`asyncpg.Connection`) já dentro de transação — a transição
  escreve o status **e** o evento `events` na mesma transação (sem estado parcial).
- Validam com `can_transition`; se ilegal → levantam `IllegalTransition`.
- Fazem `SELECT ... FOR UPDATE` na linha antes de escrever (serializa transições
  concorrentes da mesma linha).
- Devolvem a linha atualizada (`dict`).
- **Nunca** escrevem status fora daqui — exceto o `UPDATE` atômico do claim (§3.3), cuja
  *decisão* de transição passa por `can_transition("demand", "open", "claimed")`.

**Envelope de erro.** O Contrato Comum §3 exige `{"error": {"code", "message", "detail"}}`
e o `HTTPException` do FastAPI produz `{"detail": ...}` — incompatível. F4 centraliza o
envelope no lifecycle, que é o dono dos códigos:

```python
class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, detail: dict | None = None): ...

def error_payload(code: str, message: str, detail: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "detail": detail or {}}}

def error_response(err: ApiError) -> JSONResponse: ...
```

Routers de F4 **não** usam `HTTPException`: devolvem
`error_response(ApiError(...))`, garantindo o envelope canônico.

### 3.2 `server/app/services/demands.py`

```python
async def create_demand(pool, *, repo: str, module: str, title: str, body: str,
                         created_by: str) -> dict: ...
async def list_demands(pool, *, repo: str | None, status: str | None,
                        limit: int = 50, offset: int = 0) -> list[dict]: ...
async def get_demand(pool, demand_id: str) -> dict | None: ...
async def start_demand(pool, *, demand_id: str, actor_id: str) -> dict: ...
async def merge_demand(pool, *, demand_id: str, actor_id: str) -> dict: ...
async def close_demand(pool, *, demand_id: str, actor_id: str) -> dict: ...
async def block_demand(pool, *, demand_id: str, reason: str, actor_id: str) -> dict: ...
async def release_demand(pool, *, demand_id: str, actor_id: str) -> dict: ...
async def reconcile_demand(pool, *, demand_id: str, branch: str | None,
                            actor_id: str) -> dict: ...
```

- `create_demand` resolve/cria o `repos` (§3.6), insere `demands` com `status='open'` e
  grava o evento `demand.created` **na mesma transação**.
- `merge_demand` lê a review mais recente em `reviews` (§5.4) e só transiciona se o
  verdict permitir.
- `release_demand` libera `claimed → open` **e** `blocked → open` (§5.6, decisão D2).
- `reconcile_demand` (§5.5) — a chamada ao GitHub é **best-effort** e nunca bloqueia.

### 3.3 `server/app/services/claims.py` — claim atômico (MUSTROUX)

```python
async def claim_next(pool, *, repo: str, user_id: str) -> dict | None: ...
async def current_claim(pool, *, user_id: str, repo: str | None) -> dict | None: ...
```

**SQL exato** (design master §9.1 — sem alteração):

```sql
UPDATE demands
   SET status='claimed', claimed_by=$1, claimed_at=now(), updated_at=now()
 WHERE id = (
     SELECT id FROM demands
      WHERE repo_id=$2 AND status='open'
      ORDER BY created_at
      FOR UPDATE SKIP LOCKED
      LIMIT 1
 )
 RETURNING *;
```

Regras:

1. Roda dentro de `async with pool.acquire() as conn: async with conn.transaction():`.
2. `$1` = `user_id` (uuid do usuário do token), `$2` = `repo_id` (uuid, resolvido do
   `owner/name` do token ou do corpo).
3. **Antes** do `UPDATE`, a decisão passa pelo lifecycle:
   `can_transition("demand", "open", "claimed")` — se `False` → `IllegalTransition`.
   A atomicidade exige que status e ownership sejam gravados na **mesma** instrução;
   por isso o `UPDATE` atômico é a única escrita de status fora de
   `apply_demand_transition`.
4. Se o `UPDATE` retorna 0 linhas → **404** `{"error":{"code":"empty","message":"não há
   demanda disponível"}}` (Contrato Comum §3: "fila vazia (`code: "empty"`)"; design
   master §19).
5. Se retorna 1 linha → grava o evento `demand.claimed` na **mesma** transação e
   devolve a demanda.
6. `current_claim` devolve a demanda com `status IN ('claimed','in_progress')` e
   `claimed_by = user_id` (mais recente primeiro). `None` se não houver.

**Por que `SKIP LOCKED`:** resolve a corrida no Postgres, sem lock em aplicação, sem
retry loop, sem estado intermediário — e permite vários agentes consumindo a fila em
paralelo sem serializar.

### 3.4 `server/app/services/artifacts.py`

```python
async def list_artifacts(pool, *, demand_id: str | None, repo: str | None,
                          limit: int = 100, offset: int = 0) -> list[dict]: ...
async def get_artifact(pool, artifact_id: str) -> dict | None: ...
async def sync(pool, *, repo: str, docs: list[dict], actor_id: str | None) -> dict: ...
async def request_review(pool, *, artifact_id: str, actor_id: str) -> dict: ...
async def approve(pool, *, artifact_id: str, actor_id: str) -> dict: ...
async def stabilize(pool, *, artifact_id: str, actor_id: str) -> dict: ...
async def list_doubts(pool, artifact_id: str) -> list[dict]: ...
async def ensure_repo(pool, repo: str) -> str: ...   # devolve repo_id (uuid)
```

**`approve` — o corpo que F6 substitui.** O Contrato Comum §8.1 exige a rota existindo
desde F4, devolvendo 503 enquanto F6 não existe, com **import tardio** para não quebrar
o import do módulo:

```python
@router.post("/artifacts/{artifact_id}/approve")
async def approve(artifact_id: str, ...):
    ...
    try:
        from app.services import reviewers          # F6 — import tardio, dentro do handler
    except ImportError:
        return error_response(ApiError("pipeline_unavailable",
                                        "pipeline de aprovação indisponível", 503))
    result = await reviewers.run_pipeline(artifact)
    ...
```

- O `503` **não** muda status do artefato: a transição `on user review → on agents review`
  só é aplicada **depois** que o pipeline está disponível.
- Quando F6 existir, **o corpo do handler não muda**: basta `app/services/reviewers.py`
  existir com `run_pipeline(artifact) -> PipelineResult`. F6 **não** edita
  `app/routers/artifacts.py` (ownership de F4 — Contrato Comum §8.1).
- O `try/except ImportError` fica no código do F4 desde já; F6 não precisa tocar no
  router.

**`sync` — o algoritmo** (§5.1).

### 3.5 `server/app/services/commits.py`

```python
async def record_commit(pool, *, repo: str, sha: str, message: str, branch: str,
                         files: list[dict], demand_id: str, actor_id: str | None) -> dict: ...
async def list_commits(pool, *, demand_id: str | None, repo: str | None,
                        include_orphaned: bool = False, limit: int = 100,
                        offset: int = 0) -> list[dict]: ...
```

- **Idempotente por `(repo_id, sha)`** — migration 004 cria o índice único. Implementação:
  `INSERT ... ON CONFLICT (repo_id, sha) DO NOTHING RETURNING *`; se não voltou linha →
  `SELECT` da existente e devolve `created: false`.
- `files` normalizado para `[{"path": str, "additions": int | None, "deletions": int | None}]`.
- `sha` validado por `^[0-9a-f]{7,40}$` → senão **400** `code: "invalid_sha"`.
- `demand_id` obrigatório (coluna `NOT NULL` no DDL de §8) e deve existir e pertencer ao
  repo → senão **404** `code: "demand_not_found"`.

### 3.6 Migrations (aditivas)

**`server/migrations/002_demands.sql`**

```sql
-- F4 — índices de fila e de ownership.
CREATE INDEX IF NOT EXISTS demands_open_queue_idx
    ON demands (repo_id, created_at)
    WHERE status = 'open';

CREATE INDEX IF NOT EXISTS demands_claimed_by_idx
    ON demands (claimed_by)
    WHERE claimed_by IS NOT NULL;
```

**`server/migrations/003_artifacts.sql`**

```sql
-- F4 — colunas aditivas de artefato + índices de sync e de grafo.
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS doubts_index  text;
ALTER TABLE artifacts ADD COLUMN IF NOT EXISTS doubts_content text;

CREATE UNIQUE INDEX IF NOT EXISTS artifacts_repo_path_uniq
    ON artifacts (repo_id, path)
    WHERE repo_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS artifacts_demand_status_idx
    ON artifacts (demand_id, status);

CREATE UNIQUE INDEX IF NOT EXISTS spec_edges_uniq
    ON spec_edges (parent_id, child_id, type);

CREATE INDEX IF NOT EXISTS spec_edges_child_idx
    ON spec_edges (child_id);

CREATE INDEX IF NOT EXISTS doubts_artifact_idx
    ON doubts (artifact_id);
```

- `artifacts.doubts_index` = path do arquivo de dúvidas (META-004 §13).
- `artifacts.doubts_content` = conteúdo bruto do arquivo de dúvidas — o servidor não
  escreve no repo de dev (invariante 1), então guarda o conteúdo para o `sdd.py pull`
  entregar (F8). F6 mantém esse campo em dia via `render_doubts_file`.
- `artifacts_repo_path_uniq` garante a unicidade do **upsert por `(repo_id, path)`**
  (§5.1) mesmo sob sync concorrente.

**`server/migrations/004_commits.sql`**

```sql
-- F4 — status do commit (reconcile) + idempotência por (repo_id, sha).
ALTER TABLE commits ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'present';

ALTER TABLE commits DROP CONSTRAINT IF EXISTS commits_status_check;
ALTER TABLE commits ADD CONSTRAINT commits_status_check CHECK (status IN ('present','orphaned'));

CREATE UNIQUE INDEX IF NOT EXISTS commits_repo_sha_uniq
    ON commits (repo_id, sha);

CREATE INDEX IF NOT EXISTS commits_repo_created_idx
    ON commits (repo_id, created_at DESC);
```

- `commits.status` ∈ `{'present','orphaned'}` — `orphaned` = commit registrado que não
  existe no remoto (design master §13). F7 **exclui** `orphaned` do dossiê.

## 4. Rotas da API

Convenções (Contrato Comum §3): base `/api`; sucesso = **200** com JSON direto (o
contrato não lista 201 — F4 usa 200 em toda criação); erro = envelope canônico §3.1.

### 4.1 `server/app/routers/demands.py`

| Rota | Escopo | Body |
| --- | --- | --- |
| `POST /api/demands` | `demand:write` | `{repo, module, title, body}` |
| `GET /api/demands?repo=&status=&limit=&offset=` | autenticado | — |
| `GET /api/demands/{id}` | autenticado | — |
| `POST /api/demands/{id}/start` | `demand:write` | — |
| `POST /api/demands/{id}/merge` | `demand:write` | — |
| `POST /api/demands/{id}/close` | `demand:write` | — |
| `POST /api/demands/{id}/block` | `demand:write` | `{reason}` |
| `POST /api/demands/{id}/release` | `demand:write` | — |
| `POST /api/demands/{id}/reconcile` | `demand:write` | `{branch?}` |

**`POST /api/demands`** → 200:

```json
{"id":"8f2c…","repo_id":"…","repo":"owner/name","module":"login","title":"…",
 "body":"…","status":"open","claimed_by":null,"claimed_at":null,
 "created_by":"…","created_at":"2026-11-10T12:00:00Z","updated_at":"2026-11-10T12:00:00Z"}
```

- `body` vazio (só espaços) → **400** `code: "empty_body"`.
- `repo` fora do token → **403** `code: "repo_forbidden"`.
- Evento: `demand.created`.

**`GET /api/demands`** → 200 `{"demands": [...]}`, ordenadas por `created_at ASC`
(fila). `repo` filtra por `owner/name`; `status` filtra pelo status (status inválido →
**400** `code: "invalid_status"`). `limit` default 50, máx. 200.

**`GET /api/demands/{id}`** → 200 com o objeto da demanda **mais** `artifacts`
(lista `{id, kind, path, status}`) e `events` (últimos 20, ordem cronológica).
Demanda inexistente → **404** `code: "not_found"`.

**`POST /api/demands/{id}/start`** — `claimed → in_progress`.
Condição: `demands.claimed_by == usuário do token` → senão **403**
`code: "not_claim_owner"`. Transição ilegal → **409** `code: "illegal_transition"`,
`message` = `"claimed -> in_progress"` (ou o par real). Evento: `demand.started`.

**`POST /api/demands/{id}/merge`** — `review → merged`.
Condição (design master §9.1): a review mais recente da demanda tem `verdict` ∈
`{'clean','suggestions'}`:

| Situação | Status | Code |
| --- | --- | --- |
| nenhuma review | 409 | `review_required` |
| verdict = `blocking` | 409 | `review_blocking` |
| verdict = `pending` | 409 | `review_pending` |
| verdict ∈ `clean`/`suggestions` | 200 | — |

Evento: `demand.merged`.

**`POST /api/demands/{id}/close`** — `merged → done`. Evento: `demand.closed`.

**`POST /api/demands/{id}/block`** — `qualquer → blocked`.
- `reason` ausente ou vazio → **400** `code: "reason_required"`.
- O motivo **não** vira coluna: vai no `payload` do evento
  (`demand.blocked`, `payload = {"reason": "..."}`), conforme design master §9.1
  ("com motivo em events").

**`POST /api/demands/{id}/release`** — `claimed → open` (e `blocked → open`, decisão D2).
Zera `claimed_by`/`claimed_at`. Condição: `claimed_by` == usuário do token → senão
**403** `code: "not_claim_owner"`. Evento: `demand.released`.

**`POST /api/demands/{id}/reconcile`** — §5.5. Evento: `demand.reconciled` (sucesso) ou
`demand.reconcile_failed` (GitHub indisponível).

### 4.2 `server/app/routers/claims.py`

| Rota | Escopo | Body |
| --- | --- | --- |
| `POST /api/claims` | `demand:claim` | `{repo?}` |
| `GET /api/claims/current` | autenticado | — |

**`POST /api/claims`** → 200:

```json
{"demand": {"id":"…","repo_id":"…","repo":"owner/name","module":"login","title":"…",
            "body":"…","status":"claimed","claimed_by":"…","claimed_at":"2026-11-10T12:00:00Z",
            "created_by":"…","created_at":"…","updated_at":"…"}}
```

- `repo` opcional: se ausente, usa `current_repo(request)` (repo do token). Se presente e
  ≠ repo do token → **403** `code: "repo_forbidden"`.
- Fila vazia → **404** `code: "empty"` (§3.3).
- Evento: `demand.claimed`, `payload = {"demand_id": …, "repo": "owner/name"}`.

> **`POST /api/claims/{id}/release` NÃO EXISTE.** O design master §17 lista a rota, mas o
> Contrato Comum §8.2 a removeu: `release` mora em `POST /api/demands/{id}/release`.
> F4 **não** cria essa rota — evitar semântica ambígua e rota duplicada.

**`GET /api/claims/current`** → 200 `{"demand": {...} | null}`. Sem claim do usuário →
200 com `demand: null` (**não** 404: é consulta de estado, não erro). Filtra por
`claimed_by = usuário do token` e repo do token (quando houver).

### 4.3 `server/app/routers/artifacts.py`

| Rota | Escopo | Body |
| --- | --- | --- |
| `GET /api/artifacts?demand=&repo=` | autenticado | — |
| `GET /api/artifacts/{id}` | autenticado | — |
| `GET /api/artifacts/pending?repo=&demand=` | autenticado | — |
| `POST /api/artifacts/sync` | `artifact:sync` | `{repo, docs:[{path, content}]}` |
| `POST /api/artifacts/{id}/request-review` | `artifact:approve` | — |
| `POST /api/artifacts/{id}/approve` | `artifact:approve` | — |
| `POST /api/artifacts/{id}/stabilize` | `artifact:approve` | — |
| `GET /api/artifacts/{id}/doubts` | autenticado | — |

**`GET /api/artifacts`** → 200 `{"artifacts": [...]}`, ordenadas por `updated_at DESC`.
Cada item: `{id, demand_id, repo_id, kind, module, feature, path, sha, status, version,
doubts_index, created_at, updated_at}`.

**`GET /api/artifacts/{id}`** → 200 com os campos do artefato **mais**
`edges: [{"child_id": "SPEC-002", "type": "depends_on"}]`.
404 `code: "not_found"`.

**`POST /api/artifacts/sync`** → §5.1. Response 200:

```json
{"repo":"owner/name",
 "artifacts":[{"path":"docs/BR/login/login.md","id":"BR-001","status":"pending",
               "created":true,"promoted":true,"changed":true,"sha":"…",
               "lint":{"error":0,"warning":1}}],
 "summary":{"docs":2,"artifacts":1,"created":1,"promoted":1,"changed":1,
            "ignored":1,"lint_error":0,"lint_warning":1}}
```

**`POST /api/artifacts/{id}/request-review`** — `pending → on user review`.
Condições (design master §9.2):
- lint estrutural **sem** finding `error` (F2) → senão **409** `code: "lint_failed"`,
  `detail.findings` = lista de findings.
- nenhuma dúvida em `status='pending'` para o artefato → senão **409**
  `code: "open_doubts"`.
Evento: `artifact.review_requested`.

**`POST /api/artifacts/{id}/approve`** — §3.4.
- `503` `{"error":{"code":"pipeline_unavailable", …}}` enquanto F6 não existir, **sem**
  mudar status.
- Com F6: transiciona `on user review → on agents review` (evento
  `artifact.agents_review_started`) e chama `reviewers.run_pipeline(artifact)`.
- F6 é quem promove `on agents review → approved` (dentro do pipeline), via
  `apply_artifact_transition` do lifecycle.
- `status` fora de `on user review` → **409** `code: "illegal_transition"`.

**`POST /api/artifacts/{id}/stabilize`** — `approved → stable`.
Condição "≥1 RI passa" (§5.3). Sem RI → **409** `code: "ri_required"`.
Evento: `artifact.stabilized`.

**`GET /api/artifacts/{id}/doubts`** → 200:

```json
{"artifact_id":"BR-001","doubts_index":"docs/implementation-artifacts/duvidas-br/BR-001.md",
 "doubts":[{"id":"…uuid…","question":"…","status":"pending","source":"linter",
            "raised_at":"…","resolved_at":null}]}
```

**`GET /api/artifacts/pending`** — rota **obrigatória** desta fase, exigida pelo kit
(F8): `sdd.py pull` → `GET /api/artifacts/pending?repo=<owner/name>` (e
`&demand=<demand_id>` quando há demanda corrente).

Não está no §17 do design master, mas está no fluxo do §10 e é o único ponto de
escrita do kit no repo de dev. Sem essa rota, `pull` responde exit 4 com o
diagnóstico `servidor sem GET /api/artifacts/pending`.

- Query: `repo` (obrigatório, `owner/name`), `demand` (opcional).
- Filtra artefatos do repo cujo `status` **não** é `stable` — o kit escreve o
  `content` de volta no `path` relativo ao repo de dev.
- `content` vem do banco (`artifacts.content`), já com o frontmatter atualizado
  (o `status` do banco é a fonte; o frontmatter é espelho — §5.7).
- 200:

```json
{"artifacts": [
  {"id": "BR-001", "kind": "br", "path": "docs/BR/login/login.md",
   "status": "pending", "content": "---\nid: BR-001\n…\n---\n\n# …"}
]}
```

- `artifacts` vazio → 200 com `{"artifacts": []}` (não 404).
- `repo` ausente → **400** `code: "invalid_request"`.
- A rota é `authenticated` (qualquer token com `repo` correspondente).

### 4.4 `server/app/routers/commits.py`

| Rota | Escopo | Body |
| --- | --- | --- |
| `POST /api/commits` | `review:write` | `{sha, message, branch, files, demand_id}` |
| `GET /api/commits?demand=&repo=&include_orphaned=` | autenticado | — |

**`POST /api/commits`** → 200:

```json
{"id":"…uuid…","repo_id":"…","demand_id":"…","sha":"a1b2c3d","message":"feat: login",
 "branch":"main","author":"…","files":[{"path":"src/auth.ts","additions":12,"deletions":3}],
 "status":"present","created_at":"…","created":true}
```

- Idempotente por `(repo_id, sha)`: segunda chamada → 200 com o **mesmo** `id` e
  `created: false`. Sem duplicar linha.
- `sha` inválido → **400** `code: "invalid_sha"`.
- `demand_id` inexistente ou de outro repo → **404** `code: "demand_not_found"`.
- `repo` vem do token (o corpo **não** aceita `repo` — o token define o repo).
- Evento: `commit.recorded` (só na criação; reenvio **não** duplica evento).

**`GET /api/commits`** → 200 `{"commits": [...]}`, ordenadas por `created_at DESC`.
`include_orphaned` (default `false`) → commits `orphaned` são omitidos por padrão
(F7 exclui do dossiê — §5.5).

### 4.5 Correções ao design master aplicadas nesta fase (Contrato Comum §8.2)

| Onde | Master | F4 implementa |
| --- | --- | --- |
| §9.1 / §17 | `POST /api/claims/{id}/start` | `POST /api/demands/{id}/start` |
| §9.1 / §17 | `POST /api/claims/{id}/release` | `POST /api/demands/{id}/release` — e `POST /api/claims/{id}/release` **não existe** |
| §17 | `POST /api/artifacts/{id}/approve` | rota criada em F4 com import tardio (§3.4) |

## 5. Detalhes de implementação

### 5.1 Algoritmo do `POST /api/artifacts/sync`

Entrada:

```json
{"repo": "owner/name",
 "docs": [{"path": "docs/BR/login/login.md", "content": "---\nid: BR-001\n…\n---\n\n# Login\n…"}]}
```

**Uma transação só** (`async with pool.acquire() as conn: async with conn.transaction():`).
Qualquer divergência aborta **tudo** — sem estado parcial (Contrato Comum §6).

Algoritmo, por documento `d` da lista:

1. `path` relativo à raiz do repo de dev, separado por `/`, sem `..`, sem caminho
   absoluto → senão **400** `code: "invalid_path"`.
2. `sha = sha256(d.content.encode("utf-8")).hexdigest()`.
3. Frontmatter parseado com `yaml.safe_load` (mesma rotina do F2); sem frontmatter →
   tratado como `{}` (o linter aponta `BR-001`/`SPEC-001`).
4. Classificação do path:
   - `docs/BR/**` → `kind='br'`
   - `docs/SPEC/**` → `kind='spec'`
   - `docs/RI/**` → `kind='ri'`
   - qualquer outro path → o documento é **ignorado** (respondido em `summary.ignored`);
     o servidor não indexa `README.md`, `AGENTS.md` nem arquivos de dúvida.
5. Procura a linha por `(repo_id, path)`.
   - **Não existe** → nasce o artefato (§5.2). `status='draft'`.
   - **Existe e `status='draft'`** → compara `sha` reportado com `artifacts.sha`:
     - **iguais** → é o arquivo que o servidor gerou: roda o linter estrutural (§5.3) e,
       se não houver finding `error`, promove `draft → pending` via
       `apply_artifact_transition` (evento `artifact.promoted`).
     - **diferentes** → **409** `code: "content_diverged"` com os dois hashes
       (§5.6). A transação inteira é abortada.
   - **Existe e `status != 'draft'`** → o repo é autoritativo para o **conteúdo**
     (design master §21): atualiza `artifacts.content` e `artifacts.sha`, **sem** mudar
     `artifacts.status` (o status é do banco — §5.7). Evento `artifact.synced`.
6. Grava as arestas do grafo a partir do frontmatter (§5.8).
7. Evento `artifact.synced` gravado uma vez por documento tocado, com
   `payload = {"path", "id", "sha", "status", "promoted", "changed"}`.

**Idempotência.** Sync 2× com o mesmo conteúdo → mesma linha, mesmo `sha`, mesma
`version`, **zero** linhas novas em `events` (evento só quando algo muda) e **zero**
transições extras. `test_sync.py` verifica isso (design master §20).

**Ordem de processamento:** os documentos são processados na ordem recebida; o
`summary` é ordenado por `path` (determinismo).

### 5.2 Nascimento do artefato (invariante 3)

Quando um path novo de BR/SPEC/RI entra no sync:

- `id`: frontmatter `id` se casar `^(BR|SPEC)-\d{3}$`; senão gerado por tipo —
  `BR-001`, `BR-002`, … / `SPEC-001`, … — com
  `SELECT COALESCE(MAX((regexp_match(id, '(\d+)$'))[1]::int), 0) + 1 FROM artifacts WHERE id LIKE $1 || '-%'`,
  protegido por `pg_advisory_xact_lock(hashtext(kind))` para não colidir entre syncs
  concorrentes.
- `status='draft'`, `sha` = sha do conteúdo reportado, `content` = conteúdo reportado.
- `module`/`feature`: do frontmatter (`module`, `feature`); default = nome do diretório
  pai e stem do arquivo.
- `version`: frontmatter `version` ou `'1.0.0'`.
- `demand_id`: `NULL` — artefato do repo ainda não vinculado a demanda. A vinculação
  acontece pelo `POST /api/commits` (que valida a demanda) ou por update futuro (F5).
- **`doubts_index`** = `docs/implementation-artifacts/duvidas-<br|spec>/<ID>.md`
  (META-004 §13, META-006 §3) — **sempre preenchido**.
- **`doubts_content`** = arquivo de dúvidas inicial (META-006 §5), template:

```markdown
---
type: Dúvidas
artifact: BR-001
artifactStatus: draft
updatedAt: 2026-11-10T12:00:00Z
---

# Dúvidas — BR-001

## Estado

Nenhuma pendência registrada.

## Histórico

- 2026-11-10T12:00:00Z — arquivo inicializado.
```

- A tabela `doubts` **não** recebe linha no nascimento: `doubts.source` só admite
  `reviewer | linter | user` (design master §8) e a pendência real nasce quando o
  linter ou o reviewer encontra algo (F6). O arquivo, porém, já existe e está
  espelhado em `artifacts.doubts_content`.
- Evento `artifact.created`.

### 5.3 Lint estrutural (F2) no sync e no request-review

F4 **importa** (não reimplementa) o linter do F2:

```python
from app.lint.runner import ArtifactDoc, lint_document, CompositeUniverse, MethodCorpus, SyncedArtifacts
```

- `universe = CompositeUniverse(MethodCorpus(settings.repo_root / "docs"), SyncedArtifacts(pool))`
  — confirmar a assinatura de `MethodCorpus` em `app/lint/runner.py` (F2) e ajustar
  apenas a linha de chamada.
- `doc = ArtifactDoc(path=..., content=..., frontmatter=..., body=..., kind=..., repo_id=...)`
- `findings = lint_document(doc, universe)`; o sync considera **bloqueante** apenas
  `severity == "error"`. `warning` não bloqueia (Contrato Comum §7.2, design master
  §11.3).
- **No sync**: finding `error` → o artefato **permanece em `draft`**, `promoted=false`, e
  os findings entram em `summary` e no payload do evento `artifact.synced`. O sync
  **não** aborta por lint (os demais documentos seguem) — lint é gate de transição,
  não de requisição. A resposta é **200**; o kit (F8) decide pelo código de saída.
- **No request-review**: finding `error` → **409** `code: "lint_failed"` com
  `detail.findings`.

### 5.4 `merge` e a review mais recente

```sql
SELECT verdict FROM reviews
 WHERE demand_id = $1
 ORDER BY created_at DESC, id DESC
 LIMIT 1;
```

- Sem review → **409** `code: "review_required"`.
- `verdict='blocking'` → **409** `code: "review_blocking"`.
- `verdict='pending'` → **409** `code: "review_pending"`.
- `verdict IN ('clean','suggestions')` → transiciona `review → merged`.

A tabela `reviews` é do F1 (schema) e o registro é escrito por F6/F9
(`POST /api/reviews`). F4 só **consulta**.

### 5.5 `reconcile` — best-effort

1. Demanda → `repo` (via `repos`), `branch` do corpo ou `repos.default_branch`.
2. `GET https://api.github.com/repos/{owner}/{name}/commits?sha={branch}&per_page=100`
   via `httpx` com timeout de 10 s. Sem token: repositório público. `403`/`429`/erro de
   rede → **indisponível**.
3. Indisponível → **503** `{"error":{"code":"github_unavailable", …}}` + evento
   `demand.reconcile_failed` com `payload={"branch","reason"}`. **Nenhum** commit muda
   de status. A indisponibilidade externa **não bloqueia** o fluxo (Contrato Comum §3,
   design master §19).
4. Disponível → para cada commit da demanda cujo `sha` **não** está na lista do
   remoto: `UPDATE commits SET status='orphaned' WHERE id=$1`. Evento
   `demand.reconciled` com `payload={"branch","orphaned":[sha…],"kept":[sha…]}`.
5. `GET /api/commits` e o dossiê (F7) **omitem** `status='orphaned'` por padrão
   (`include_orphaned=true` para listar).

**Escopo de F4:** o registro e a consulta. F4 não implementa revisão automática nem
altera o remoto.

### 5.6 Formato do 409 de divergência

```json
{"error": {"code": "content_diverged",
           "message": "conteúdo divergente do servidor",
           "detail": {"path": "docs/BR/login/login.md",
                      "server_sha": "3f9a…", "client_sha": "c02b…",
                      "server_status": "draft"}}}
```

- `server_sha` = `artifacts.sha` (o que o servidor tem).
- `client_sha` = sha do conteúdo reportado no sync.
- Nenhum documento do sync é aplicado (transação abortada) — sem estado parcial.
- `409` também para `resource_conflict` quando dois syncs concorrentes tentam promover o
  mesmo artefato (o `SELECT ... FOR UPDATE` serializa; o segundo vê `status='pending'` e
  apenas espelha).

### 5.7 `artifacts.status` é a fonte; o frontmatter é espelho

- O `status` do frontmatter do arquivo **nunca** define o status do artefato. Se o
  arquivo trouxer `status:` diferente de `artifacts.status`, o servidor **não** muda
  status e registra a divergência em `events` (`artifact.synced` com
  `payload.frontmatter_status`).
- O espelho (reescrever o frontmatter do arquivo) é do lado do repo, via
  `sdd.py pull` (F8) — o servidor nunca escreve no repo de dev (invariante 1).

### 5.8 Arestas do grafo

No sync, o frontmatter define as arestas de `spec_edges`:

| Frontmatter | Aresta |
| --- | --- |
| `createdFrom: BR-001` | `(parent=spec, child=BR-001, type='derives_from')` |
| `dependsOn: [SPEC-002]` | `(parent=spec, child=SPEC-002, type='depends_on')` |
| `tests: [RI-001]` | `(parent=spec, child=RI-001, type='tests')` |

- Só arestas cujo `child_id` exista em `artifacts` são gravadas (FK).
- `ON CONFLICT (parent_id, child_id, type) DO NOTHING` — o índice único
  `spec_edges_uniq` (migration 003) garante idempotência.
- `type` ∈ `depends_on | derives_from | tests` (design master §8).

### 5.9 Eventos

Toda transição grava uma linha em `events` **na mesma transação** da mudança:

| `type` | Momento | `payload` mínimo |
| --- | --- | --- |
| `demand.created` | criação da demanda | `{demand_id, module, title}` |
| `demand.claimed` | claim atômico | `{demand_id, repo, claimed_by}` |
| `demand.started` | `claimed → in_progress` | `{demand_id, from, to}` |
| `demand.merged` | `review → merged` | `{demand_id, from, to}` |
| `demand.closed` | `merged → done` | `{demand_id, from, to}` |
| `demand.blocked` | `→ blocked` | `{demand_id, from, to, reason}` |
| `demand.released` | `→ open` | `{demand_id, from, to}` |
| `demand.reconciled` | reconcile ok | `{demand_id, branch, orphaned[], kept[]}` |
| `demand.reconcile_failed` | GitHub indisponível | `{demand_id, branch, reason}` |
| `artifact.created` | nascimento no sync | `{path, id, kind}` |
| `artifact.synced` | sync aplicou mudança | `{path, id, sha, status, promoted, changed}` |
| `artifact.promoted` | `draft → pending` | `{path, id, from, to}` |
| `artifact.review_requested` | `pending → on user review` | `{id, from, to}` |
| `artifact.agents_review_started` | `on user review → on agents review` | `{id, from, to}` |
| `artifact.approved` | `on agents review → approved` (F6) | `{id, from, to}` |
| `artifact.stabilized` | `approved → stable` | `{id, from, to}` |
| `commit.recorded` | commit novo | `{commit_id, sha, demand_id, branch}` |

- `events.demand_id`/`events.artifact_id` preenchidos quando aplicável.
- `events.actor` = uuid do usuário do token (null em sync sem usuário).
- Nomenclatura: `<entidade>.<ação>` — a mesma usada pelo SSE do F1.

### 5.10 Ordem de checagem (autorização)

Contrato Comum §6 — toda rota de escrita, nesta ordem:

1. token válido e não revogado → **401**;
2. escopo exigido → **403** (`code: "forbidden_scope"`);
3. repo do token == repo do recurso → **403** (`code: "repo_forbidden"`);
4. transição legal → **409** (`code: "illegal_transition"`).

Falha em qualquer elo → **sem estado parcial**.

Escopos por rota:

| Rota | Escopo |
| --- | --- |
| `POST /api/demands` | `demand:write` |
| `POST /api/demands/{id}/{start,merge,close,block,release,reconcile}` | `demand:write` |
| `POST /api/claims` | `demand:claim` |
| `POST /api/artifacts/sync` | `artifact:sync` |
| `POST /api/artifacts/{id}/{request-review,approve,stabilize}` | `artifact:approve` |
| `POST /api/commits` | `review:write` |
| `GET /api/demands`, `GET /api/artifacts`, `GET /api/claims/current`, `GET /api/commits`, `GET /api/artifacts/{id}/doubts` | autenticado (sem escopo específico) |

### 5.11 Decisões tomadas onde o contrato não cobria

| # | Decisão | Justificativa |
| --- | --- | --- |
| D1 | `blocked → open` permitido, e `release` também libera de `blocked` | §9.1 só desenha `→ blocked`; sem volta, a demanda fica travada para sempre |
| D2 | `approved → stable` exige `spec_edges (type='tests')` para um artefato com `kind='ri'` (path sob `docs/RI/`) | "≥1 RI passa" (design master §9.2) não tem coluna própria; a aresta `tests` é o encaixe natural do DDL de §8 |
| D3 | 409 de divergência só para artefatos em `draft` | design master §21: o repo é autoritativo para **conteúdo**; divergência só importa na detecção `draft → pending` (§9.2) |
| D4 | Lint com `error` no sync não aborta a requisição: o artefato fica em `draft` e o sync responde 200 | lint é **gate de transição** (design master §11.3), não gate de requisição; abortar o sync inteiro por um documento quebrado perde o trabalho dos outros |
| D5 | `artifacts.id` gerado por tipo quando o frontmatter não tem `id` | `artifacts.id` é `text` no formato `BR-013`/`SPEC-024` (Contrato Comum §4) e precisa existir mesmo sem frontmatter |
| D6 | Nascimento do artefato cria o arquivo de dúvidas mas **não** linha em `doubts` | `doubts.source` só admite `reviewer|linter|user`; a linha nasce quando há achado real (F6) |
| D7 | Chamada ao GitHub sem token (repositório público); `403`/`429`/rede = indisponível | nenhum token GitHub de leitura está no contrato (§5); 10 s de timeout |
| D8 | `reconcile` responde 200 com resumo quando o GitHub responde, e 503 só quando o GitHub está indisponível | 503 = dependência externa indisponível (Contrato Comum §3) |
| D9 | `done → blocked` é permitido; `stable` e `done`… `done` aceita voltar a `blocked`, `stable` é terminal | §9.1 diz "qualquer → blocked" |
| D10 | `GET /api/claims/current` responde 200 com `demand: null` quando não há claim | é consulta de estado, não erro |

### 5.12 Tarefas

1. `server/app/services/lifecycle.py` — status, tabelas de transição, `IllegalTransition`,
   `ApiError`, `error_payload`/`error_response`, `can_transition`, `allowed_targets`,
   `apply_demand_transition`, `apply_artifact_transition` (evento na mesma transação).
2. `server/app/services/demands.py` — create/list/get/start/merge/close/block/release/reconcile.
3. `server/app/services/claims.py` — `claim_next` (SQL `FOR UPDATE SKIP LOCKED`),
   `current_claim`.
4. `server/app/services/artifacts.py` — sync (§5.1), nascimento (§5.2), lint (§5.3),
   request-review, approve (import tardio), stabilize, list_doubts, ensure_repo.
5. `server/app/services/commits.py` — record_commit (idempotente), list_commits.
6. `server/app/routers/{demands,claims,artifacts,commits}.py` — as rotas de §4, com
   dependências de `app/auth.py` (`require_user`, `require_scope`, `current_repo`).
7. `server/migrations/00{2,3,4}_*.sql` — §3.6.
8. `server/tests/{test_lifecycle,test_claim,test_sync}.py` — §7.

## 6. Critérios de aceitação

- [ ] `can_transition("demand", "open", "claimed")` → `True`;
      `can_transition("demand", "open", "merged")` → `False`.
- [ ] `allowed_targets("artifact", "pending")` → `["on user review"]`.
- [ ] `IllegalTransition` tem `code="illegal_transition"` e `http_status=409`.
- [ ] `POST /api/demands` cria demanda `open` e grava evento `demand.created`.
- [ ] `POST /api/demands` com `body` vazio → 400 `code: "empty_body"`.
- [ ] `POST /api/claims` com 1 demanda `open` → 200, status `claimed`, `claimed_by` = usuário.
- [ ] **N** claims concorrentes sobre **1** demanda → exatamente **1** vence; os outros
      recebem **404** `code: "empty"`. (design master §20 — o teste mais importante)
- [ ] `POST /api/demands/{id}/start` por quem não é o dono do claim → 403
      `code: "not_claim_owner"`.
- [ ] `POST /api/demands/{id}/merge` sem review → 409 `code: "review_required"`.
- [ ] `POST /api/demands/{id}/merge` com review `blocking` → 409 `code: "review_blocking"`.
- [ ] `POST /api/demands/{id}/block` sem `reason` → 400 `code: "reason_required"`.
- [ ] `POST /api/demands/{id}/block` grava o motivo no `payload` do evento.
- [ ] `POST /api/demands/{id}/release` devolve a demanda para `open` e zera
      `claimed_by`/`claimed_at`.
- [ ] **`POST /api/claims/{id}/release` responde 404** (a rota não existe — Contrato
      Comum §8.2).
- [ ] `POST /api/artifacts/sync` com BR nova → cria `artifacts` com `status='draft'`,
      `doubts_index` preenchido e `doubts_content` com o template inicial.
- [ ] `POST /api/artifacts/sync` com o **mesmo** sha do servidor → `draft → pending`
      (evento `artifact.promoted`) **e** lint limpo.
- [ ] `POST /api/artifacts/sync` com sha **divergente** → **409**
      `code: "content_diverged"` com `server_sha` e `client_sha`, e **nenhuma** linha
      alterada (inclusive os outros docs do lote).
- [ ] `POST /api/artifacts/sync` com BR que tem link quebrado → permanece `draft`,
      `promoted=false`, findings no `summary`.
- [ ] `POST /api/artifacts/sync` 2× com o mesmo conteúdo → idempotente: 1 linha em
      `artifacts`, 0 eventos duplicados, `version` inalterada.
- [ ] `POST /api/artifacts/sync` com path não-BR/SPEC/RI → `summary.ignored` conta.
- [ ] `POST /api/artifacts/{id}/request-review` com dúvida `pending` → 409
      `code: "open_doubts"`.
- [ ] `POST /api/artifacts/{id}/approve` sem o F6 → **503**
      `{"error":{"code":"pipeline_unavailable"}}` e o status **não** muda.
- [ ] `POST /api/artifacts/{id}/stabilize` sem RI ligado por `tests` → 409
      `code: "ri_required"`.
- [ ] `POST /api/commits` grava em `commits`; reenvio do mesmo `(repo_id, sha)` → mesmo
      `id`, `created: false`, 1 linha na tabela.
- [ ] `POST /api/commits` com sha inválido → 400 `code: "invalid_sha"`.
- [ ] `POST /api/demands/{id}/reconcile` com GitHub fora → 503
      `code: "github_unavailable"` + evento `demand.reconcile_failed`, e **nenhum**
      commit marcado `orphaned`.
- [ ] `GET /api/commits` **omite** `orphaned` por padrão.
- [ ] Toda transição aparece em `events` com `type` no formato `<entidade>.<ação>`.
- [ ] Nenhum handler escreve `status` direto — toda mudança passa por
      `app/services/lifecycle.py`.
- [ ] `pytest server/tests` verde; `git diff --stat tools/ docs/` vazio.

## 7. Testes

| Arquivo | Teste | Verifica |
| --- | --- | --- |
| `test_lifecycle.py` | `test_demand_transitions_legal` | toda transição de §3.1 passa em `can_transition` |
| | `test_demand_transitions_illegal` | transição fora da tabela → `False` e `IllegalTransition` com `http_status=409` |
| | `test_artifact_transitions_legal` | tabela de §3.1 do artefato |
| | `test_allowed_targets` | `allowed_targets` bate com a tabela, para todos os status |
| | `test_illegal_transition_via_api` | `POST /api/demands/{id}/merge` em demanda `open` → 409 `illegal_transition` |
| | `test_block_requires_reason` | 400 `reason_required` |
| | `test_block_reason_in_event` | motivo no `payload` de `demand.blocked` |
| | `test_release_by_non_owner_403` | 403 `not_claim_owner` |
| | `test_events_recorded` | uma linha em `events` por transição, com `type` correto |
| `test_claim.py` | `test_claim_single_winner` | **N** claims concorrentes → 1 vencedor, N−1 com 404 `empty` |
| | `test_claim_sets_owner` | `claimed_by`, `claimed_at` e `status='claimed'` |
| | `test_claim_event` | evento `demand.claimed` gravado |
| | `test_claim_empty_queue` | 404 `code: "empty"` |
| | `test_claim_skips_locked_row` | com a linha travada (`FOR UPDATE`), o claim pega a próxima |
| | `test_claims_route_release_absent` | `POST /api/claims/{id}/release` → 404 |
| | `test_current_claim` | `GET /api/claims/current` devolve a demanda do usuário |
| `test_sync.py` | `test_sync_creates_artifact_draft` | nasce `draft`, com `doubts_index` e `doubts_content` |
| | `test_sync_promotes_when_sha_matches` | `draft → pending` + evento `artifact.promoted` |
| | `test_sync_409_on_divergence` | 409 com `server_sha`/`client_sha`; **nada** persistido |
| | `test_sync_idempotent` | 2× → 1 linha, 0 eventos duplicados, `version` igual |
| | `test_sync_lint_error_blocks_promotion` | BR com link quebrado fica `draft` |
| | `test_sync_ignores_non_artifact_paths` | `README.md` → `summary.ignored` |
| | `test_sync_status_source_is_db` | frontmatter com `status: stable` **não** muda `artifacts.status` |
| | `test_sync_creates_graph_edges` | `dependsOn`/`createdFrom` viram `spec_edges` |
| | `test_commit_recorded_idempotent` | 2× → 1 linha, mesmo `id` |
| | `test_commit_invalid_sha_400` | 400 `invalid_sha` |
| | `test_reconcile_marks_orphaned` | sha ausente do remoto → `status='orphaned'` |
| | `test_reconcile_github_down_503` | 503 `github_unavailable` + evento `demand.reconcile_failed` |

**Concorrência do `test_claim.py`:** N corrotinas asyncio com o **mesmo** pool e tokens
de usuários distintos; `asyncio.gather` sobre N requests HTTP via `httpx.AsyncClient`
(ASGI transport). Resultado esperado: exatamente 1 com 200, os demais 404 `empty`.
N = 8. Este é o teste que garante a invariante "duas pessoas não pegam a mesma demanda".

**Mark `postgres`:** os testes que tocam o banco usam a fixture `pool` do F1 e são
pulados com `pytest.skip` se o Postgres não estiver de pé.

## 8. Referências

- Contrato Comum §2 (dependências entre módulos), §3 (convenções de API e erros),
  §4 (convenções de banco e migrations), §5 (env), §6 (auth, escopos, ordem de checagem),
  §7.1 (lifecycle), §7.2 (linter do F2), §8 (matriz de ownership), §8.1 (stub do
  approve), §8.2 (correções ao design master), §9 (ondas).
- Design master §8 (DDL canônico), §8.1 (índices), §9.1 (ciclo da demanda + SQL do
  claim), §9.2 (ciclo do artefato + direção dos comandos), §12 (pipeline de aprovação),
  §13 (reconcile), §16 (auth), §17 (superfície de API), §19 (erros), §20 (testes),
  §21 (fontes de verdade).
- META-004 §8 (metadados), §13 (ciclo e pendências).
- META-006 §3 (arquivo de dúvidas por artefato), §5 (sincronização inicial),
  §6 (mapeamento de status), §9 (regras do arquivo).
- Specs irmãs: `2026-11-10-fase-F1-core-servidor.md` (schema, auth, db),
  `2026-11-10-fase-F2-linter-artefatos.md` (regras, `ArtifactDoc`, universos),
  `2026-11-10-fase-F5-*` (geração, usa `artifacts.py`),
  `2026-11-10-fase-F6-*` (pipeline, substitui o corpo de `approve`),
  `2026-11-10-fase-F7-*` (dossiê, filtra `orphaned`).
