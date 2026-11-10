# Contrato Comum — Ambiente SDD Multi-Agentes

| Campo | Valor |
| --- | --- |
| **Data** | 2026-11-10 |
| **Status** | Contrato de referência (vinculante para F1–F10) |
| **Owner** | Bruno Cesar Sprotte |
| **Escopo** | Interfaces, convenções e fronteiras de ownership entre as fases |

> Este documento existe porque F1–F10 são implementadas **em paralelo** por agentes
> diferentes. Onde duas fases tocam o mesmo arquivo, este contrato diz quem é dono.
> Em conflito, **este contrato prevalece sobre o design master** e sobre qualquer
> spec de fase.

Design master: `design/specs/2026-11-10-ambiente-sdd-multi-agentes-design.md`.

---

## 1. Repositório e toolchain

| Item | Valor |
| --- | --- |
| Repo | `C:\Users\Bruno\Desktop\projeto\blueprint` |
| Branch | `feat/sdd-multi-agent-server` |
| Python | 3.12+ (dev local tem 3.14.6) |
| Servidor | `server/` — FastAPI + asyncpg + pydantic-settings |
| Banco | Postgres 16 em `db/docker-compose.yml` |
| Front | `site/` — Docusaurus 3 (F10) |
| Plugin | `plugin/` — fonte do kit que o dev copia pro repo dele (F8) |
| Testes | pytest + pytest-asyncio + httpx (ASGI transport) — sem mock framework pesado |

Instalação e banco subem com `docker compose -f db/docker-compose.yml up -d` e
`pip install -e server[dev]`.

## 2. Regras de dependência entre módulos

```
routers/  →  services/  →  db.py
   ↓            ↓
lint/    →  db.py
```

- **Router** só valida entrada, chama um service e serializa a resposta. Nunca SQL.
- **Service** contém regra de negócio e fala com o banco via `app/db.py`.
- `app/lint/` é biblioteca pura: recebe documento in-memory, devolve findings. Não fala
  com banco nem com rede.
- `app/auth.py` é a única fonte de identidade/autorização.

Proibido: import de `routers` dentro de `services`; import entre services que não
estejam listados na matriz da §9.

## 3. Convenções de API

Base: `/api`. Resposta de sucesso = JSON direto (sem envelope). Erro = envelope único:

```json
{"error": {"code": "illegal_transition", "message": "open -> merged", "detail": {}}}
```

| Status | Uso |
| --- | --- |
| 400 | erro de uso do cliente (parâmetro inválido que passou pelo schema) |
| 401 | ausente ou inválido `Authorization` |
| 403 | token sem escopo, ou token de outro repo, ou recurso não permitido |
| 404 | recurso inexistente **ou** fila vazia (`code: "empty"`) |
| 409 | transição ilegal, recurso já claimado, conteúdo divergente no sync |
| 422 | validação de schema (pydantic) |
| 500 | erro interno não classificado |
| 503 | dependência externa indisponível (LLM) — **não bloqueia commit** |

Headers: `X-Request-Id` em toda resposta (UUID4).

## 4. Convenções de banco

- Tabelas no plural, snake_case. PK `uuid` com `gen_random_uuid()`, exceto `artifacts.id`
  (`text`, formato `BR-013` / `SPEC-024`) e `sessions.id` (`text`).
- Timestamps: `created_at timestamptz not null default now()`, `updated_at timestamptz not null default now()`.
- FK com `on delete cascade`, exceto `users` (que é referenciado por `demands.created_by`).
- Índices conforme §8.1 do design master.
- **Migrations**: SQL puro em `server/migrations/NNN_descricao.sql`, aplicadas em ordem
  lexicográfica, controladas pela tabela `schema_migrations(version text primary key, applied_at timestamptz not null default now())`.
  Runner próprio em `server/app/db.py` (~40 linhas). **Sem Alembic** — revisão de migration
  manual é mais simples de auditar e o schema é pequeno.

DDL canônico: §8 do design master. As fases que criam tabela usam exatamente o DDL de lá;
se precisarem de coluna extra, **adicionam coluna**, nunca reescrevem a tabela.

### 4.1 Coluna `chunks.tsv` — regra única (F1, F3, F7)

O design master §8 declara `tsv tsvector` — **coluna simples**, não generated.
Postgres **recusa** atribuição a coluna `GENERATED ALWAYS` (inclusive via trigger), então
`generated` quebraria o bootstrap.

Regra vinculante:

- **F1** cria `tsv tsvector` (coluna simples, sem default), exatamente como §8.
- **F3** escreve o valor no `INSERT`: `to_tsvector('portuguese', coalesce(heading,'') || ' ' || coalesce(text,''))`.
  F3 não cria trigger (não é dona de migration) e não depende de F7.
- **F7** cria o trigger `chunks_tsv` (`BEFORE INSERT OR UPDATE OF heading, text`) na
  migration `005`, com a **mesma** expressão do F3 — assim qualquer chunk escrito por
  fora do F3 (dúvidas, commits, reviews) também tem `tsv` coerente.

A expressão é a mesma nos três lugares. Divergência entre F3 e F7 produziria `tsv`
inconsistente e busca errada.

### 4.2 Rotas de coordination entre fases (respostas às dúvidas do F8)

Respostas do maestro (2026-11-10) às dúvidas do agente da F8. **Vinculantes.**

| Dúvida | Resposta |
| --- | --- |
| (a) `GET /api/artifacts/pending` — é escopo do F4? | **Sim.** É rota do F4 (`app/routers/artifacts.py`). O F4 a expõe. Enquanto não existir, `pull` responde exit 4 com o diagnóstico — comportamento correto e esperado. |
| (b) `POST /api/reviews` aceita o shape completo do kit? | **Sim.** O F6 aceita `sha` + `demand_id` (obrigatórios) e ignora campos extras (`verdict`, `findings`). O kit manda os 4. |
| (c) `GET /api/skills/{id}` devolve markdown cru ou JSON? | **JSON**, conforme F3 §3.9: `{id, version, hash, description, path, content, files}`. O `content` é o markdown bruto do `SKILL.md` dentro do JSON. O kit aceitar os 3 formatos é tolerância extra, sem problema. |
| (d) O hash do manifesto é sha256 ou md5? | **sha256 hex**, conforme F3 §3.8 / dataclass `Skill` (`hash: str  # sha256 hex da árvore da skill`). O exemplo de 32 chars da spec F8 é abreviação de doc, não md5. |
| (e) O manifest de `/api/skills/manifest` é o mesmo corpus do repo blueprint? | **Sim.** F3 serve o diretório `skills/` do repo blueprint (`SDD_REPO_ROOT`). O kit espelha em `.claude/skills/` do repo de dev. Mesmo corpus, hash verificável. |
| (f) O F9 pode consumir o kit assumindo JSON em stdout + exit code? | **Sim.** Contrato do kit: JSON em stdout, diagnóstico legível em stderr, decisão por exit code (0/1/2/3/4/5). O F9 consome `plugin/kit/sdd.py` por subprocesso, nunca por import. |

**Decisões do F8 aceitas** (não exigem mudança): `sync` 400 → exit 4; `status` 404 →
exit 0; normalização do `SDD_URL` (remove `/api` final); `report` sem `author` e sem
exit 1; erros locais também em JSON no stdout.

### 4.3 `commits.status` — dono é o F4 (resolvido 2026-11-10)

A coluna `commits.status` é **do F4** (migration `004_commits.sql`), não do F7:

```sql
ALTER TABLE commits ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'present';
ALTER TABLE commits DROP CONSTRAINT IF EXISTS commits_status_check;
ALTER TABLE commits ADD CONSTRAINT commits_status_check CHECK (status IN ('present','orphaned'));
CREATE UNIQUE INDEX IF NOT EXISTS commits_repo_sha_uniq ON commits (repo_id, sha);
```

- Valores canônicos: **`present` | `orphaned`**. `orphaned` = commit registrado que
  não existe no remoto (reconcile, design master §13).
- **O F7 não cria a coluna.** A migration `005` do F7 **não** faz
  `ADD COLUMN commits.status` — ela apenas **consome** a coluna, filtrando
  `status <> 'orphaned'` no dossiê. Se o F7 criar a coluna, o `ADD COLUMN IF NOT
  EXISTS` é inofensivo, mas o `CHECK` com valores diferentes quebraria o F4.
- O default `'present'` garante que commits já gravados não somem do dossiê.
- O F7 filtra por `status <> 'orphaned'` (não por `= 'reported'`).

## 5. Variáveis de ambiente

Lidas por `app/config.py` (pydantic-settings). Prefixo `SDD_`.

| Variável | Obrigatória | Default | Nota |
| --- | --- | --- | --- |
| `SDD_DATABASE_URL` | sim | `postgresql://sdd:sdd@localhost:5432/sdd` | |
| `SDD_SECRET_KEY` | sim | — | assina cookie de sessão (HMAC) |
| `SDD_REPO_ROOT` | não | raiz do repo blueprint | onde estão `docs/` e `skills/` |
| `SDD_BASE_URL` | não | `http://localhost:8000` | callback OAuth |
| `SDD_GITHUB_CLIENT_ID` | prod | — | |
| `SDD_GITHUB_CLIENT_SECRET` | prod | — | |
| `SDD_ALLOW_DEV_AUTH` | não | `false` | login local sem GitHub, só dev |
| `SDD_LLM_MODEL` | não | `claude-opus-5-5` | |
| `ANTHROPIC_API_KEY` | prod | — | lida nativamente pelo SDK `anthropic` |
| `ANTHROPIC_BASE_URL` | não | — | proxy (o usuário tem `http://127.0.0.1:20128/v1`) |

`app/config.py` é **read-only**: nenhum service escreve env. Testes usam
`monkeypatch.setenv` antes de importar `app.config`.

## 6. Autenticação

Dependências prontas em `app/auth.py` (F1):

```python
def require_user(request: Request) -> User: ...          # cookie de sessão OU bearer de token
def require_scope(scope: str) -> Callable[..., Token]: ...  # 403 se o token não tem o escopo
def current_repo(request: Request) -> str: ...           # repo do token, "owner/name"
```

- Web: GitHub OAuth (Authorization Code) → cookie `sdd_session` `httpOnly`,
  `SameSite=Lax`, `secure` em produção, assinado HMAC, linha em `sessions`.
- Kit: token opaco `sdd_<32 bytes base64url>`, guardado **só** como SHA-256 em
  `tokens.token_hash`. Header `Authorization: Bearer sdd_...`.
- Escopos: `demand:claim`, `demand:write`, `artifact:sync`, `artifact:approve`,
  `review:write`, `token:admin`.
- Ordem de checagem em toda rota de escrita: token válido → não revogado → escopo →
  repo permitido → transição legal. Falha em qualquer elo → 403/409, **sem estado parcial**.

## 7. Contratos de módulo partilhado

### 7.1 Ciclo de vida — `app/services/lifecycle.py` (owner: F4)

```python
DEMAND_STATUSES = ("open", "claimed", "in_progress", "review", "merged", "done", "blocked")
ARTIFACT_STATUSES = ("draft", "pending", "on user review", "on agents review", "approved", "stable")

class IllegalTransition(Exception):
    code = "illegal_transition"; http_status = 409
    def __init__(self, entity: str, current: str, target: str): ...

def can_transition(table: str, current: str, target: str) -> bool: ...
def allowed_targets(table: str, current: str) -> list[str]: ...
```

`table` ∈ `{"demand", "artifact"}`. Tabelas de transição: §9.1 (demanda) e §9.2
(artefato) do design master. Handler HTTP **nunca** muda status direto — passa por aqui.

Correção sobre o design master (§9.1 vs §17): `start` e `release` moram em
`/api/demands/{id}/...`, não em `/api/claims/{id}/...`. `POST /api/claims/{id}/release`
**não** existe — evita rota duplicada com semântica ambígua.

### 7.2 Linter — `app/lint/` (owner: F2)

```python
# app/lint/rules.py
@dataclass(frozen=True)
class Finding:
    rule: str            # "BR-001"
    severity: str        # "error" | "warning"
    message: str
    path: str | None = None
    line: int | None = None
    detail: dict = field(default_factory=dict)

@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    check: Callable[["ArtifactDoc"], list[Finding]]

RULES: tuple[Rule, ...]   # BR-001..BR-004, SPEC-001..SPEC-004, PATH-001, PATH-002, LINK-001

# app/lint/runner.py
@dataclass
class ArtifactDoc:
    path: str
    content: str
    frontmatter: dict[str, str]
    body: str
    kind: str | None     # "br" | "spec" | None (inferido do path)
    repo_id: str | None = None

class LinkUniverse(Protocol):
    def exists(self, ref: str) -> bool: ...
    def resolve(self, ref: str) -> str | None: ...

def lint_document(doc: ArtifactDoc, universe: LinkUniverse) -> list[Finding]: ...
def lint_batch(docs: list[ArtifactDoc], universe: LinkUniverse) -> list[Finding]: ...
```

Regras canônicas: §11.1 do design master. `LINK-001` é `error` sempre.

Universo de links = método (`docs/` do repo blueprint, lido do disco) **+** artefatos já
sincronizados do repo de dev (tabela `artifacts`). Implementações:

```python
class MethodCorpus:      # F2 — índice em memória, construído no startup
    def __init__(self, root: Path): ...
class SyncedArtifacts:   # F2 — consulta `artifacts` no banco
    def __init__(self, pool): ...
class CompositeUniverse: # F2 — method + synced
```

### 7.3 Geração — `app/services/generator.py` (owner: F5)

```python
async def generate_br(demand: Demand, ctx: GenerationContext) -> GeneratedArtifact: ...
async def generate_specs(br: Artifact, ctx: GenerationContext) -> tuple[GeneratedArtifact, ...]: ...
```

`GeneratedArtifact = {id, kind, path, content, frontmatter, doubts_index_path}`.
Claude API: SDK `anthropic` oficial, modelo `claude-opus-5-5`,
`thinking={"type": "adaptive"}`, `output_config={"effort": "high"}`, **streaming**
(`client.messages.stream()` + `.get_final_message()`), `output_config.format` para o
frontmatter.

### 7.4 Revisores — `app/services/reviewers.py` (owner: F6)

```python
async def run_pipeline(artifact: Artifact) -> PipelineResult: ...
# PipelineResult = {verdict, findings[], linter_findings[], doubts_written, llm_available}
```

Ordem **fixa** (META-005): linter → Blind Hunter → Edge Case Hunter → Acceptance Auditor.
Rodam **sequenciais**. Falha de LLM → `verdict="pending"`, `llm_available=False`, e
**nada** bloqueia.

Achado de revisor:

```json
{"severity":"blocking","title":"...","detail":"...","ac":"AC-003","suggestion":"..."}
```

### 7.5 Dúvidas — `app/services/doubts.py` (owner: F6)

```python
async def raise_doubt(artifact_id: str, question: str, source: str) -> Doubt: ...
async def resolve_doubt(doubt_id: str) -> Doubt: ...
def render_doubts_file(artifact_id: str, doubts: list[Doubt]) -> str: ...
```

Fluxo META-006: achado → linha em `doubts` → linha no arquivo `duvidas-spec/<ID>.md`
do repo de dev (via `pull`) → agente resolve → `sync` → `doubts.status = "cleaned"`.
Catálogo central só lista artefato com pendência aberta.

### 7.6 Indexação e busca — `app/services/indexer.py`, `app/services/retriever.py` (owner: F7)

```python
# indexer.py
def chunk_markdown(text: str, heading_path: list[str]) -> list[Chunk]: ...   # split por H2
async def index_method() -> int: ...        # corpus 'method'
async def index_artifact(doc: ArtifactDoc, corpus_id: str) -> int: ...
async def index_commit(commit: Commit) -> int: ...
async def index_review(review: Review) -> int: ...

# retriever.py
@dataclass
class Hit:
    chunk_id: str; artifact_id: str | None; demand_id: str | None
    heading: str; text: str; score: float; corpus_id: str

async def search(q: str, corpus_id: str, top: int = 10) -> list[Hit]: ...
```

BM25 em duas etapas: candidatos por `ts_rank_cd` (top 200) → rerank em Python puro
(`k1=1.5`, `b=0.75`, mesmo scoring do `tools/retrieve.py`). **O corpus nunca cruza corpora**
(`corpus_id = "method" | "repo:<uuid>"`).

**Contrato de resposta estável**: `GET /api/method/search` (F3) e `GET /api/knowledge`
(F7) devolvem a **mesma forma**: `{"query": str, "hits": [ {heading, text, score, source_kind, artifact_id, demand_id, corpus_id} ]}`.
F3 entrega busca provisória (FTS puro, sem rerank); F7 sobe pra BM25 de duas etapas
**sem mudar a forma**. O cliente não percebe a troca.

### 7.7 Kit — `plugin/kit/sdd.py` (owner: F8)

Contrato completo no Apêndice A do design master. Complemento vinculante:

- **stdlib apenas**. Sem `pip install`, sem `npm install`.
- JSON sempre em stdout; diagnóstico em stderr.
- `SDD_URL`, `SDD_TOKEN`, `SDD_REPO` (default: remote git do repo).
- Exit codes: `0` ok | `1` lint/review bloqueante | `2` erro de uso | `3` sem demanda
  | `4` sync falhou | `5` auth.
- Comandos: `claim`, `sync`, `pull`, `status`, `skill sync`, `lint`, `review`,
  `knowledge`, `dossier`, `report`.
- `kit/state.json` guarda a demanda corrente (escrito por `claim`).
- `kit/config.local.json` guarda o token (gitignored).

## 8. Matriz de ownership (quem pode criar/editar o quê)

Conflito = dois agentes mexendo no mesmo arquivo. Esta tabela elimina.

| Fase | ARQUIVOS QUE A FASE PODE CRIAR/EDITAR | PODE LER, NÃO EDITAR |
| --- | --- | --- |
| **F1** | `server/pyproject.toml`, `server/app/{main,config,db,models,auth}.py`, `server/app/routers/*.py` (stubs), `server/app/services/*.py` (stubs), `server/app/lint/__init__.py`, `server/migrations/001_*.sql`, `server/tests/conftest.py`, `server/tests/test_bootstrap.py`, `db/docker-compose.yml` | `tools/`, `docs/` |
| **F2** | `server/app/lint/{rules,runner}.py`, `server/app/routers/lint.py`, `server/tests/{test_lint,test_links}.py` | `tools/lint.py` (inalterado) |
| **F3** | `server/app/routers/method.py`, `server/app/services/{method,skills}.py`, `server/tests/test_method.py` | `docs/` |
| **F4** | `server/app/services/{lifecycle,demands,artifacts,claims,commits}.py`, `server/app/routers/{demands,claims,artifacts,commits}.py`, `server/migrations/00{2..4}_*.sql`, `server/tests/{test_lifecycle,test_claim,test_sync}.py` | `app/db.py` |
| **F5** | `server/app/services/generator.py`, `server/app/routers/generation.py`, `server/tests/test_generation.py` | `services/method.py` |
| **F6** | `server/app/services/{reviewers,doubts}.py`, `server/app/routers/reviews.py`, `server/tests/{test_pipeline,test_doubts}.py` | `app/lint/` |
| **F7** | `server/app/services/{indexer,retriever}.py`, `server/app/routers/knowledge.py`, `server/migrations/005_*.sql`, `server/tests/{test_bm25,test_dossier}.py` | — |
| **F8** | `plugin/**` (`.claude-plugin/`, `kit/`, `skills/`, `README.md`), `server/tests/test_kit_contract.py` | — |
| **F9** | `plugin/hooks/pre-push`, `plugin/hooks/install-hooks.sh`, `plugin/kit/reviewer.py`, `server/tests/test_hook.py` | `plugin/kit/sdd.py` (consome, não edita) |
| **F10** | `site/**` | `server/app/routers/*` |

### 8.1 Stub obrigatório (F1 cria, fases posteriores preenchem)

F1 cria **todos** os routers e services listados acima, cada um com:

```python
"""Router de <assunto>. Implementado na fase F<n>."""
from fastapi import APIRouter
router = APIRouter()
```

Isso elimina colisão em `main.py` e nos `__init__.py`: cada fase edita só o próprio
arquivo. F1 registra todos os routers em `main.py` **incluindo os stubs**, com prefixo
`/api`. Um stub sem rota não responde nada — seguro.

Exceção: `POST /api/artifacts/{id}/approve` — F4 cria a rota devolvendo
`503 {"error":{"code":"pipeline_unavailable"}}`; F6 substitui **só o corpo do handler**.
Regra: F6 não pode editar `app/routers/artifacts.py` (ownership de F4) → o handler
delegado fica em `app/services/reviewers.py` e F4 chama `await reviewers.run_pipeline(...)`
por **import tardio** dentro do handler, para não quebrar o import de F4 caso F6
ainda não exista.

### 8.2 Correções ao design master (prevalece este contrato)

| Onde | Master diz | Corrige para |
| --- | --- | --- |
| §9.1 / §17 | `POST /api/claims/{id}/start` e `POST /api/claims/{id}/release` | `POST /api/demands/{id}/start` e `POST /api/demands/{id}/release` |
| §7 | routers: method, demands, claims, artifacts, reviews, knowledge, admin | + `lint.py` (F2), `commits.py` (F4), `generation.py` (F5) |
| §6 | F6 depende de F2, F5 | F6 depende de F2, F4, F5 |
| §7 | `skills/` na raiz do repo = fonte servida (F3) | mantém; o `skills/` do **plugin** (F8) é cópia instalada |

## 9. Dependências e ondas de paralelismo

```
F1 ─┬─ F2 ─┐
    ├─ F3 ─┼─ F4 ─┬─ F5 ─┬─ F6 ─┬─ F7 ─┬─ F9
    │      │      │      │      │      │
    │      │      │      │      │      └──── F8 ── F9
    │      │      │      │      └─────────── F7
    │      │      │      └────────────────── F6
    │      │      └───────────────────────── F5
    │      └──────────────────────────────── F4
    └─────────────────────────────────────── F2, F3, F8(sem backend)
```

| Onda | Fases em paralelo | Pré-requisito |
| --- | --- | --- |
| 0 | F1 | — |
| 1 | F2, F3 | F1 |
| 2 | F4 | F1, F2 |
| 3 | F5, F8 | F4 (F8) / F3+F4 (F5) |
| 4 | F6, F10 | F2+F4+F5 (F6) / F4+F6 (F10) |
| 5 | F7 | F4, F6 |
| 6 | F9 | F7, F8 |

**Regra para agente que implementa fase com dependência pendente**: pode escrever
código contra o contrato deste documento e o stub correspondente; **não** pode alterar
o contrato nem o arquivo da fase dependente. Testes que dependem de fase não pronta
ficam `@pytest.mark.skip(reason="F<n> pendente")` — com o número da fase no motivo.

## 10. Definição de pronto (por fase)

1. Código do escopo da fase, nos arquivos que ela pode editar (§8).
2. Testes novos passam; testes existentes continuam passando (`pytest server/tests`).
3. Nenhum `TODO`, `FIXME`, `pass  #` ou stub sem docstring de fase.
4. `POST /api/lint` no próprio artefato volta limpo (quando a fase tem artefato).
5. Commit no branch de trabalho com mensagem no padrão do repo e sem mexer em
   `tools/` nem em `docs/`.

## 11. Contrato do kit (complemento do Apêndice A)

```
kit/sdd.py <comando> [args]
Comandos: claim, sync, pull, status, skill sync, lint, review, knowledge, dossier, report
Env: SDD_URL (obrigatório) | SDD_TOKEN (obrigatório) | SDD_REPO (default: remote git)
Saída: JSON em stdout, sempre. Diagnóstico em stderr.
Exit codes: 0 ok | 1 lint/review bloqueante | 2 erro de uso | 3 sem demanda
            4 sync falhou | 5 auth
```

`SDD_URL` sem barra final. O kit fala **só** com as rotas do §17 do design master,
que este contrato não altera — exceto `start`/`release`, movidos para `/api/demands/...`.
