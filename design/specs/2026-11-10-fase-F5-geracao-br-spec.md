# Fase F5 — Geração de BR/SPEC

| Campo | Valor |
| --- | --- |
| **Fase** | F5 |
| **Data** | 2026-11-10 |
| **Depende de** | F1, F3, F4 |
| **Bloqueia** | F6 |
| **Onda** | 3 (paralelo com F8) |
| **Contrato** | `design/specs/2026-11-10-contrato-comum.md` §7.3 |

> Reler o **Contrato Comum** antes de começar. Em conflito, o contrato prevalece sobre
> esta spec. Não reescreva o que F1 (schema, db, config) e F2 (linter) já definiram —
> **use**.

## 1. Objetivo

O servidor executa **SK-001** (business discovery) e **SK-002** (technical planning)
via Claude API e devolve **markdown pronto** de BR e de grafo de SPECs, com frontmatter
exato dos templates do método e arquivo de dúvidas criado junto.

**Critério de sucesso da fase:** `POST /api/generation/demands/{id}/br` devolve uma BR
com frontmatter de SK-001 §16 e as 9 seções de SK-001 §14; `POST /api/generation/artifacts/{id}/specs`
devolve N SPECs com frontmatter de SK-002 §15, as 14 seções de SK-002 §10 e as arestas do
grafo gravadas em `spec_edges`; ambos criam o arquivo de dúvidas do artefato; a segunda
chamada do mesmo gerador é idempotente.

**O servidor nunca escreve no repo de dev** (invariante 1). Ele devolve markdown; quem
escreve no repo é o kit (`sdd.py pull`, F8).

## 2. Arquivos que esta fase pode criar/editar

```
server/app/services/generator.py
server/app/routers/generation.py
server/tests/test_generation.py
```

**Não tocar:** `server/app/lint/` (F2), `server/app/services/{method,skills}.py` (F3),
`server/app/services/{lifecycle,demands,artifacts,claims,commits}.py` e
`server/app/routers/{demands,claims,artifacts,commits}.py` (F4), `server/app/routers/reviews.py`
(F6), `server/app/db.py` (F1), `tools/`, `docs/`, qualquer `design/specs/`.

## 3. Contrato (Contrato Comum §7.3 — repetido aqui para não depender de leitura cruzada)

```python
# server/app/services/generator.py
async def generate_br(demand: Demand, ctx: GenerationContext) -> GeneratedArtifact: ...
async def generate_specs(br: Artifact, ctx: GenerationContext) -> tuple[GeneratedArtifact, ...]: ...
```

```python
# server/app/models.py (F1) — reusar, não redefinir
@dataclass(frozen=True)
class Demand:
    id: str; repo_id: str; module: str; title: str; body: str
    status: str; claimed_by: str | None; claimed_at: datetime | None
    created_by: str; created_at: datetime; updated_at: datetime

@dataclass(frozen=True)
class Artifact:
    id: str; demand_id: str | None; repo_id: str | None
    kind: str; module: str; feature: str; path: str; sha: str
    status: str; version: str; content: str | None
    created_at: datetime; updated_at: datetime
```

`GeneratedArtifact` (dict, contrato §7.3):

```python
{"id": "BR-013", "kind": "br", "path": "docs/BR/login/login.md",
 "content": "---\nid: BR-013\n...", "frontmatter": {...},
 "doubts_index_path": "docs/implementation-artifacts/duvidas-br/BR-013.md"}
```

### 3.1 `GenerationContext` (definido por F5, dentro de `generator.py`)

```python
@dataclass(frozen=True)
class GenerationContext:
    pool: asyncpg.Pool
    demand_id: str
    repo_id: str
    module: str
    method_context: "MethodContext"
    repo_context: "RepoContext"
    client: Any | None = None        # AsyncAnthropic; injetável em teste
```

```python
@dataclass(frozen=True)
class MethodDocument:
    doc_id: str          # "SK-001", "META-001", "ES-000"
    title: str
    category: str        # SK | META | ES | PAT | LS | TS | TP | RI
    content: str

@dataclass(frozen=True)
class MethodContext:
    documents: tuple[MethodDocument, ...]
    technology_pack: str | None       # "TP-001"
    degraded: bool
    degraded_reason: str | None

@dataclass(frozen=True)
class RepoContext:
    corpus_id: str | None             # "repo:<uuid>" ou None
    hits: tuple[tuple[str, str], ...] # (heading, text) do BM25
    degraded: bool
    degraded_reason: str | None
```

`client=None` → `build_client()` (§5.1) é usado. Em teste, injete um fake.

## 4. Decisões que o contrato não cobre

O Contrato Comum §7.3 fixa a forma das funções e os parâmetros da API Claude, mas não
decide o que está abaixo. **Estas decisões são vinculantes para F5 e F6.**

| # | Decisão | Justificativa |
| --- | --- | --- |
| D1 | **`id`, `status`, `timestamp`, `type`, `version`, `generatedBy`, `createdFrom`, `technologyPack` e `doubtsIndex` são atribuídos pelo SERVIDOR**, nunca pelo modelo. O modelo devolve só `module`, `feature`, `title`, `description`, `tags` (+ `body`, `complexity`, ACs e relações, no caso de SPEC). | ID sequencial (`BR-013`) colide se o modelo inventar; `doubtsIndex` depende do ID; `technologyPack` é resolvido por META-001, e SK-002 §11 proíbe o agente de escolher tecnologia. |
| D2 | **`id` é alocado sob advisory lock transacional** (`pg_advisory_xact_lock(hashtext('sdd.artifact_id'))`) para que duas gerações concorrentes não peguem o mesmo número. | Geração é concorrentes (F6 e F9 disparam em paralelo). |
| D3 | **A resposta HTTP inclui `doubts_file` e `spec_edges`**, além do `GeneratedArtifact`. O `GeneratedArtifact` do contrato não tem onde levar o conteúdo do arquivo de dúvidas, e META-006 §5 exige que ele nasça junto com o artefato. | `doubts_file` (path+content) e `spec_edges` viajam no **payload da rota**; o `GeneratedArtifact` permanece exatamente com os 6 campos do contrato. |
| D4 | **Idempotência por default**: `generate-br`/`generate-specs` devolvem **200 com o artefato existente** e `created: false` quando o artefato já existe. Nada de 409. | "Retrabalho não deve duplicar artefato" — 409 deixaria o agente sem saída; devolver o existente é seguro e reentrante. Regeneração não existe em F5 (ver §9). |
| D5 | **Rotas com prefixo próprio** `/api/generation/...`, em `app/routers/generation.py` (owner F5). Não usar `/api/demands/{id}/generate-br` nem `/api/artifacts/{id}/generate-specs`, porque `demands.py` e `artifacts.py` são do F4 e **F5 não pode editá-los**. | Matriz de ownership §8 do contrato. |
| D6 | **`ANTHROPIC_BASE_URL` tem o sufixo `/v1` removido antes de virar `base_url` do SDK.** O SDK `anthropic` concatena `/v1/messages` ao `base_url`; o proxy do usuário é `http://127.0.0.1:20128/v1`, o que geraria `/v1/v1/messages`. | Ver §5.1. Não converter para OpenAI-compatível. |
| D7 | **Aresta não resolvida não é gravada** e gera evento `spec_edge_unresolved`; a SPEC é persistida assim mesmo. | O grafo é consequência da geração, não pré-requisito dela. Perder uma aresta é recuperável; perder a SPEC inteira não. |
| D8 | **F5 grava as Open Questions da BR/SPEC na tabela `doubts`** (`source='user'`, `status='pending'`) e publica o arquivo de dúvidas renderizado no mesmo formato que o `render_doubts_file` do F6. | META-006 §5 e §8: pendência precisa existir para o approval gate ter o que bloquear. O formato é fixado aqui e **F6 precisa adopted** (§5.6). |

## 5. Detalhes de implementação

### 5.1 Cliente Anthropic

```python
import os
import anthropic
from app.config import settings

MODEL = settings.llm_model          # "claude-opus-5-5" (Contrato Comum §5)

class LLMUnavailable(RuntimeError):
    """LLM indisponível: sem credencial, proxy fora, timeout, 5xx, ou recusa."""

def build_client() -> anthropic.AsyncAnthropic:
    """Cliente async. Lê ANTHROPIC_API_KEY e ANTHROPIC_BASE_URL do ambiente."""
    base = os.environ.get("ANTHROPIC_BASE_URL", "").strip().rstrip("/")
    if base.endswith("/v1"):          # D6: o SDK já concatena /v1/messages
        base = base[: -len("/v1")]
    try:
        return anthropic.AsyncAnthropic(base_url=base) if base else anthropic.AsyncAnthropic()
    except anthropic.AnthropicError as exc:
        raise LLMUnavailable(f"credencial ausente: {exc}") from exc
```

- O SDK lê `ANTHROPIC_API_KEY` nativamente. Não ler, não logar, não gravar a chave.
- `ANTHROPIC_BASE_URL` **não** vai para `app/config.py` (prefixo `SDD_`) — é env do SDK.
- Toda chamada usa os parâmetros fixados pelo contrato §7.3:

```python
async with client.messages.stream(
    model=MODEL,
    max_tokens=32000,
    thinking={"type": "adaptive"},
    output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
    system=SYSTEM_PROMPT,
    messages=[{"role": "user", "content": USER_PROMPT}],
) as stream:
    final = await stream.get_final_message()
```

- `max_tokens=32000` (streaming não tem limite de 10 min do SDK; respostas longas são o
  caso normal aqui).
- `stop_reason` **obrigatório** antes de ler o conteúdo: `"max_tokens"` → erro de
  truncamento (texto incompleto, schema inválido) → `LLMUnavailable`; `"refusal"` →
  `LLMUnavailable` com `payload["category"] = final.stop_details.category`.
- `output_config.format` (structured outputs) garante que o **primeiro bloco de texto é
  JSON válido** conforme o schema. Parse com `json.loads`.

### 5.2 Contexto de cada chamada

Duas fontes, nesta ordem (design master §18):

**a) Corpus do método resolvido por META-001.**

```
resolve_method_context(kind="br"|"spec", module, feature, br_content=None)
```

Sequência de categorias (META-001 §5/§6, sempre da mais abstrata para a mais concreta):

| kind | categorias carregadas | limite |
| --- | --- | --- |
| `br` | `SPEC` (existentes do mesmo módulo, para evitar capacidade duplicada) → `ES` → `PAT` → `LS` → `TS` (só os do TP) → `TP` → `RI` | 5 / 5 / 3 / 5 / 2 |
| `spec` | `BR` (a BR de origem) → `SPEC` (irmãs da mesma demanda) → `ES` → `PAT` → `LS` → `TS` → `TP` → `RI` | idem |

- A **skill executada** entra sempre no contexto: `SK-001` para kind `br`, `SK-002` para
  kind `spec`.
- `TP` (technology pack): selecionado pelo `technologyPack` já declarado na BR de origem,
  quando existir; senão, se o corpus tem exatamente um `TP-*`, usa-o; senão usa o de menor
  id (`TP-001`). **Determinístico**, sem heurística de stack — o schema §8 do design master
  não guarda a stack do repo. Upgrade path: quando F8 passar a stack no payload do `pull`,
  a seleção pode usar esse dado.
- `TS` só entra se o `TP` selecionado os referenciar.
- `RI`: o `RI` mais específico por título (META-001 §9) ou `RI-001`.

**Origem do corpus — F3, com fallback local:**

```python
try:
    from app.services.method import load_method_documents   # F3
except ImportError:
    load_method_documents = None                            # fallback local (abaixo)
```

Fallback local (F5, dentro de `generator.py`): varre `settings.repo_root / "docs"`
(proibido escrever; leitura é a invariante 4 do design master), lê o frontmatter de cada
`.md`, indexa por `id` e `title`, e carrega o conteúdo do documento selecionado. Sem
F3, `MethodContext.degraded=True`, `degraded_reason="F3 pendente: corpus do método lido
localmente sem índice compartilhado"`.

> **Requisito para F3 (handoff):** expor em `app/services/method.py`:
> `async def load_method_documents(category: str | None = None) -> list[MethodDocument]`
> e `async def load_method_document(doc_id: str) -> MethodDocument | None`.
> Se F3 entregar nomes diferentes, F5 ajusta **apenas** a função adaptadora
> `resolve_method_context()` — o resto do gerador não muda.

**b) Top-k BM25 do corpus do repo (F7).**

```python
try:
    from app.services.retriever import search      # F7
except ImportError:
    search = None                                   # dependência pendente
```

- `corpus_id = f"repo:{repo_id}"` — o corpus **nunca** cruza corpora (Contrato Comum §7.6).
- `q = demand.title + "\n" + demand.body[:2000]`, `top = 5`.
- Se `search` é `None` (F7 pendente): `RepoContext.corpus_id=None`, `hits=()`,
  `degraded=True`, `degraded_reason="F7 pendente: corpus do repo indisponível"`.
  **O artefato ainda é gerado** — só o contexto de reuso some. Isso é degradation, não
  falha.
- O hit entra no prompt como "Conhecimento prévio do repositório" com o heading e o texto,
  para **forçar reuso** e evitar duplicar conhecimento (META-000 §8/§9).

### 5.3 Schema de saída (structured outputs)

Dois schemas, um por kind. `additionalProperties: false` em todos os objetos e
`required` completo em todos.

**BR** (`kind="br"`):

```json
{
  "type": "object",
  "properties": {
    "frontmatter": {
      "type": "object",
      "properties": {
        "module": {"type": "string"},
        "feature": {"type": "string"},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}}
      },
      "required": ["module", "feature", "title", "description", "tags"],
      "additionalProperties": false
    },
    "body": {"type": "string"}
  },
  "required": ["frontmatter", "body"],
  "additionalProperties": false
}
```

**SPEC** (`kind="spec"`) — o grafo e as N SPECs saem **numa única chamada**:

```json
{
  "type": "object",
  "properties": {
    "specs": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "feature": {"type": "string"},
          "title": {"type": "string"},
          "description": {"type": "string"},
          "tags": {"type": "array", "items": {"type": "string"}},
          "complexity": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "VERY HIGH"]},
          "acceptanceCriteria": {"type": "array", "items": {"type": "string"}},
          "body": {"type": "string"}
        },
        "required": ["feature", "title", "description", "tags", "complexity",
                     "acceptanceCriteria", "body"],
        "additionalProperties": false
      }
    },
    "edges": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "parentFeature": {"type": "string"},
          "childFeature": {"type": "string"},
          "type": {"type": "string", "enum": ["depends_on", "derives_from", "tests"]}
        },
        "required": ["parentFeature", "childFeature", "type"],
        "additionalProperties": false
      }
    }
  },
  "required": ["specs", "edges"],
  "additionalProperties": false
}
```

- `acceptanceCriteria` são **ids de AC da BR** (`"AC-003"`), nunca texto de AC. Toda AC da
  BR precisa aparecer em ≥1 SPEC (SK-002 §12/§13, e é o que a regra `BR-004` do F2 cobra).
- `parentFeature`/`childFeature` referenciam **features dentro do lote** (o modelo não
  conhece os IDs do servidor — D1). O servidor mapeia feature → ID alocado.
- `complexity` = SK-002 §17 (`LOW | MEDIUM | HIGH | VERY HIGH`), gravada em
  `frontmatter.complexity` e no frontmatter como tag `complexity:<valor>`.

### 5.4 Renderização do markdown

```python
_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

def render_document(frontmatter: dict[str, object], body: str) -> str:
    fm = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True,
                         default_flow_style=False).rstrip()
    return f"---\n{fm}\n---\n\n{body.strip()}\n"
```

- `sort_keys=False` preserva a ordem de inserção do dict → a ordem canônica do template é
  garantida pela **ordem de construção do dict**, não pelo dump.
- `yaml.safe_dump` entre aspas simples o timestamp ISO. Aceito: o linter do F2 faz
  `yaml.safe_load`, e as duas formas parseiam igual. Para casar byte a byte com o
  template, use um `yaml.SafeDumper` com representer que emite `style='"'` para strings
  ISO-8601.
- `module` e `feature` **precisam** casar com `_SLUG_RE` (META-004 §6, e `PATH-001` do F2
  exige kebab-case). Se não casar → erro `422 invalid_module_feature`, sem gravar nada.
- `path` = `docs/BR/<module>/<feature>.md` (BR) ou `docs/SPEC/<module>/<feature>.md`
  (SPEC) — META-004 §4/§7. Caminho **no repo de dev**, que o kit escreve.

**Frontmatter BR** (SK-001 §16, ordem exata):

```yaml
---
id: BR-013
module: login
feature: login
type: Business Rule
title: Autenticação de usuários com e-mail e senha
description: Permite que usuários cadastrados autentiquem e acessem áreas protegidas.
status: draft
tags: [login, autenticacao]
timestamp: "2026-11-10T12:00:00Z"
doubtsIndex: docs/implementation-artifacts/duvidas-br/BR-013.md
version: 1.0.0
generatedBy: SK-001
---
```

**Frontmatter SPEC** (SK-002 §15, ordem exata):

```yaml
---
id: SPEC-024
module: login
feature: login-api
type: Functional Specification
title: Endpoint de autenticação por e-mail e senha
description: Expõe a autenticação de usuário e devolve sessão ao cliente autorizado.
createdBy: SK-002
createdFrom: BR-013
technologyPack: TP-001
status: draft
tags: [login, api, complexity:MEDIUM]
timestamp: "2026-11-10T12:05:00Z"
doubtsIndex: docs/implementation-artifacts/duvidas-spec/SPEC-024.md
version: 1.0.0
---
```

- `status` nasce `draft` (design master §9.2: `— → draft` na geração, com arquivo de
  dúvidas criado e indexado). `draft → pending` é do F4, no `sync`.
- `version` = `1.0.0`.
- `timestamp` = `datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")`.
- `description` é a linha de catálogo OKF (SK-001 §16 / SK-002 §15).

### 5.5 Corpo do artefato

O corpo vem do modelo (`body` do structured output) e **precisa** conter, nesta ordem,
os headings canônicos:

- **BR** (SK-001 §14, 9 seções): `Objetivo`, `Contexto`, `Atores`, `Capacidades`,
  `Regras de Negócio`, `Restrições`, `Exceções`, `Acceptance Criteria`,
  `Open Questions` (esta última **opcional** — só quando houver dúvida em aberto).
- **SPEC** (SK-002 §10, 14 seções): `Objetivo`, `Escopo`, `Responsabilidade`, `Entradas`,
  `Saídas`, `Fluxo principal`, `Fluxos alternativos`, `Validações`, `Failures`,
  `Pré-condições`, `Pós-condições`, `Acceptance Criteria atendidos`, `Dependências`,
  `Blueprint Documents necessários`.

F5 **não reimplementa a validação** — a regra `BR-003`/`SPEC-002` do F2 é a dona disso, e
o `draft → pending` do F4 só passa se o linter passar. F5 valida apenas o que ele
controla: slug de `module`/`feature`, unicidade do `id` alocado, e o schema da resposta.

### 5.6 Grafo de SPECs e `spec_edges`

Granularidade: **1 SPEC = 1 responsabilidade técnica** (SK-002 §7). SK-002 §17 classifica
a complexidade (`LOW|MEDIUM|HIGH|VERY HIGH`) — o valor vem do modelo e é gravado no
frontmatter. A **granularidade** (quantas SPECs, e como) segue a árvore de decisão
`Spec Branch Granularity` (SK-002, Árvores de Decisão) e o grafo segue SK-002 §8/§9.

**Convenção de direção das arestas** (fixa, para todo o sistema):

| tipo | `parent_id` | `child_id` | significado |
| --- | --- | --- | --- |
| `derives_from` | a SPEC | a BR de origem | a SPEC deriva da BR |
| `depends_on` | a SPEC que depende | a SPEC da qual depende | SPEC-025 depende de SPEC-024 |
| `tests` | a SPEC de testes | a SPEC testada | SPEC-029 testa SPEC-024 |

Gravação (uma linha por aresta resolvida):

```sql
INSERT INTO spec_edges (parent_id, child_id, type) VALUES ($1, $2, $3);
```

Resolução:

1. `parentFeature`/`childFeature` batem com o `feature` de uma SPEC do lote → ID alocado.
2. Se não batem, tenta resolver como **ID de SPEC já existente** no banco
   (`SELECT id FROM artifacts WHERE id = $1 AND kind = 'spec'`).
3. Se não resolver → a aresta **não é gravada** e o servidor registra
   `events(type='spec_edge_unresolved', payload={"parentFeature": ..., "childFeature": ...,
   "type": ..., "reason": "not_resolved"})` (D7).
4. Toda SPEC do lote ganha uma aresta `derives_from` para a BR de origem, gravada sempre.

Sem ciclo: a validação de ciclo é do linter (`SPEC-004`, F2). F5 não a duplica.

### 5.7 Arquivo de dúvidas (META-006 §5)

Criado **junto** com o artefato, no repo de dev (escrito pelo kit, no pull):

| kind | caminho |
| --- | --- |
| BR | `docs/implementation-artifacts/duvidas-br/<BR-id>.md` |
| SPEC | `docs/implementation-artifacts/duvidas-spec/<SPEC-id>.md` |

Formato **canônico v1** (F5 cria a primeira versão; **F6 precisa usar exatamente este
formato** no `render_doubts_file`, Contrato Comum §7.5):

```markdown
---
id: BR-013
artifactId: BR-013
status: draft
updatedAt: "2026-11-10T12:00:00Z"
---

# Dúvidas — BR-013

Pendências: 1

| id | status | source | question | raised_at | resolved_at |
| --- | --- | --- | --- | --- | --- |
| 6f1d2c8e-0a3b-4f5d-9e77-2b1c0a9d4e55 | pending | user | [AC-004] Senha pode ser redefinida por e-mail ou por token? | 2026-11-10T12:00:00Z | — |
```

- `status` do arquivo segue o mapeamento de META-006 §6: `draft`→`draft`, `pending`→
  `pending`, `on user review`/`on agents review`→`pending`, `approved`→`approved`.
- Cada **Open Question** do corpo da BR/SPEC vira uma linha na tabela **e** uma linha na
  tabela `doubts`:

```sql
INSERT INTO doubts (artifact_id, question, status, source)
VALUES ($1, $2, 'pending', 'user')
RETURNING id, artifact_id, question, status, source, raised_at, resolved_at;
```

- `question` = `"[<ac>] <title> — <detail>"` quando a pendência está amarrada a uma AC,
  senão `"<title> — <detail>"`. As Open Questions do corpo não têm AC: entram como
  `"<texto da pergunta>"`.
- `doubtsIndex` no frontmatter do artefato aponta para esse path (§5.4) — regra `PATH-002`
  do F2 exige que o arquivo exista quando o artefato for sincronizado.
- Catálogo central (`duvidas-br.md` / `duvidas-spec.md`) **não** é escrito por F5: só
  entra no catálogo o artefato com pendência aberta, e o catálogo é re-renderizado pelo
  F6 (que é dona de `services/doubts.py`).

### 5.8 Persistência, idempotência e erro

**Ordem das operações (uma transação):**

```
1. BEGIN
2. SELECT pg_advisory_xact_lock(hashtext('sdd.artifact_id'))
3. aloca o próximo id (BR: 'BR-%03d'; SPEC: 'SPEC-%03d')
   -- próximo = maior id numérico existente do kind + 1
   SELECT id FROM artifacts WHERE kind = $1 AND id ~ ('^' || $1 || '-[0-9]{3}$')
    ORDER BY id DESC LIMIT 1
4. INSERT em artifacts (id, demand_id, repo_id, kind, module, feature, path, sha,
                        status, version, content)
5. INSERT em spec_edges (uma linha por aresta resolvida)
6. INSERT em doubts (uma linha por Open Question)
7. INSERT em events (type='artifact_generated')
8. COMMIT
```

```sql
INSERT INTO artifacts (id, demand_id, repo_id, kind, module, feature, path, sha,
                       status, version, content)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'draft',$9,$10)
RETURNING *;
```

- `sha` = `hashlib.sha256(content.encode("utf-8")).hexdigest()` — é o que o F4 compara no
  `sync` para promote `draft → pending` (design master §9.2).
- `content` = o markdown completo (frontmatter + corpo). O F6 lê o conteúdo **da tabela**,
  não do repo.

**Idempotência (D4):**

```sql
SELECT * FROM artifacts
 WHERE demand_id = $1 AND kind = 'br'
 ORDER BY created_at DESC LIMIT 1;
```

- `generate-br`: se já existe BR da demanda → devolve **200** com o artefato existente,
  `created: false`, `idempotent: true`. **Nenhuma chamada de LLM, nenhuma escrita.**
- `generate-specs`: se já existem SPECs da BR → devolve **200** com elas, `created: false`.
- Só entra no caminho de geração quando não existe.

**Erro de LLM (design master §19):**

| Situação | Comportamento |
| --- | --- |
| `LLMUnavailable` (sem credencial, proxy fora, 5xx, timeout, `max_tokens`, recusa) | **503** `{"error":{"code":"llm_unavailable","message":"...","detail":{"stage":"br"}}}`. Demanda volta para `open` (§5.9). Evento `generation_failed`. **Nada é gravado** — nem artefato, nem dúvida. |
| Resposta com schema inválido ou `module`/`feature` fora do slug | **422** `{"error":{"code":"invalid_module_feature",...}}`. Demanda volta para `open`. Evento `generation_failed` com `detail.reason="invalid_artifact_path"`. |
| Demanda em `merged`, `done` ou `blocked` | **409** `{"error":{"code":"illegal_transition","message":"done -> generate-br"}}`. **Nenhuma chamada de LLM.** |

**Demanda voltando para `open` (§5.9):**

A transição passa por `app/services/lifecycle.py` (owner F4, invariante 2):

```python
# app/services/lifecycle.py (F4) — função que F5 espera existir
async def apply_demand_transition(pool: asyncpg.Pool, demand_id: str, target: str) -> str: ...
```

- Se o status atual é `open` → já está em `open`, **nada** a fazer (só o evento).
- Se é `claimed` → F4 aplica `claimed → open` (release).
- Se é `in_progress` → **permanece `in_progress`** (design master §19 fala em "volta pra
  open", mas `in_progress → open` não é transição legal na tabela §9.1, e o servidor nunca
  adivinha — invariante 2). O evento `generation_failed` carrega
  `detail={"reset": false}`.
- Se F4 ainda não expuser `apply_demand_transition` (dependência pendente): import tardio
  dentro do `try`, e no `ImportError` F5 faz o `UPDATE demands SET status=$2,
  updated_at=now() WHERE id=$1 AND status=$3` **só** quando `can_transition("demand",
  atual, alvo)` for `True` (import tardio também, de `lifecycle.can_transition`).

**Eventos (F4 e F1 registram eventos no mesmo formato de `events`):**

```sql
INSERT INTO events (demand_id, artifact_id, type, payload, actor)
VALUES ($1, $2, 'artifact_generated', $3::jsonb, $4);
```

- `artifact_generated` → payload `{"artifact_id","kind","path","sha","module","feature",
  "method_docs":[...],"repo_hits":N,"degraded":bool,"degraded_reason":str|null}`.
- `generation_failed` → payload `{"stage":"br"|"specs","error_type":"LLMUnavailable",
  "message":"...","reason":"llm_unavailable"|"invalid_artifact_path"}`.

### 5.9 Rotas (`app/routers/generation.py` — owner F5)

Prefixo próprio (D5). F1 registra o router com prefixo `/api` (F1 §3.7).

**`POST /api/generation/demands/{id}/br`**

- Escopo: `demand:write`.
- Sem body. Lê `demand.title`, `demand.body`, `demand.module`, `demand.repo_id`.
- Demanda inexistente → **404** `{"error":{"code":"not_found",...}}`.
- Demand sem `repo_id` → **400** `{"error":{"code":"missing_repo"}}`.
- Idempotente (D4).

Response **200**:

```json
{
  "created": true,
  "idempotent": false,
  "artifact": {
    "id": "BR-013",
    "kind": "br",
    "path": "docs/BR/login/login.md",
    "content": "---\nid: BR-013\nmodule: login\n...\n---\n\n# Objetivo\n...",
    "frontmatter": {
      "id": "BR-013", "module": "login", "feature": "login",
      "type": "Business Rule", "title": "...", "description": "...",
      "status": "draft", "tags": ["login", "autenticacao"],
      "timestamp": "2026-11-10T12:00:00Z",
      "doubtsIndex": "docs/implementation-artifacts/duvidas-br/BR-013.md",
      "version": "1.0.0", "generatedBy": "SK-001"
    },
    "doubts_index_path": "docs/implementation-artifacts/duvidas-br/BR-013.md"
  },
  "doubts_file": {
    "path": "docs/implementation-artifacts/duvidas-br/BR-013.md",
    "content": "---\nid: BR-013\n...\n---\n\n# Dúvidas — BR-013\n..."
  },
  "spec_edges": [],
  "context": {
    "method_docs": ["SK-001", "META-001", "META-004", "ES-000", "PAT-001", "LS-001", "TP-001", "RI-001"],
    "repo_hits": 0,
    "repo_corpus_id": null,
    "degraded": true,
    "degraded_reason": "F7 pendente: corpus do repo indisponível"
  },
  "usage": {"input_tokens": 18422, "output_tokens": 6310}
}
```

**`POST /api/generation/artifacts/{id}/specs`**

- Escopo: `demand:write`.
- `{id}` é o id de uma BR (`BR-013`). Artefato inexistente ou `kind != 'br'` → **404**.
- BR sem `demand_id` → **400** `{"error":{"code":"missing_demand"}}`.
- Idempotente: se já existem SPECs dessa BR → **200** com `created: false`.

Response **200**:

```json
{
  "created": true,
  "idempotent": false,
  "artifacts": [
    {"id": "SPEC-024", "kind": "spec", "path": "docs/SPEC/login/login-api.md",
     "content": "---\nid: SPEC-024\n...", "frontmatter": {...},
     "doubts_index_path": "docs/implementation-artifacts/duvidas-spec/SPEC-024.md"}
  ],
  "doubts_files": [
    {"path": "docs/implementation-artifacts/duvidas-spec/SPEC-024.md", "content": "..."}
  ],
  "spec_edges": [
    {"parent_id": "BR-013", "child_id": "SPEC-024", "type": "derives_from"},
    {"parent_id": "SPEC-025", "child_id": "SPEC-024", "type": "depends_on"},
    {"parent_id": "SPEC-029", "child_id": "SPEC-024", "type": "tests"}
  ],
  "context": {"method_docs": ["SK-002", "META-001", ...], "repo_hits": 3,
              "repo_corpus_id": "repo:8f1d2c8e-0a3b-4f5d-9e77-2b1c0a9d4e55",
              "degraded": false, "degraded_reason": null},
  "usage": {"input_tokens": 24310, "output_tokens": 19875}
}
```

**Erro 503 (LLM)**, envelope único do Contrato Comum §3:

```json
{"error": {"code": "llm_unavailable", "message": "Claude API indisponível",
           "detail": {"stage": "br", "error_type": "LLMUnavailable"}}}
```

### 5.10 Prompts

**BR — system:**

```
Você executa a Skill SK-001 — Business Discovery do método Blueprint.
Papel: Senior Business Analyst. Toda a conversa permanece no domínio de negócio.
Nunca discuta arquitetura, banco de dados, APIs, linguagens, frameworks ou implementação.
Nunca invente informação ausente: informação desconhecida vira Open Question, não suposição.
Fluxo obrigatório: Business Context → Actors → Capabilities → Business Rules → Domain Language
→ Business Scenarios → Acceptance Criteria → Open Questions → Business Validation → Generate BR.
Cada Acceptance Criteria é objetivo, verificável, numerado no formato AC-\d{3}, independente de
tecnologia e pequeno o suficiente para virar teste automatizado. Escreva a seção Acceptance
Criteria como uma lista "- AC-001: <critério>".
O corpo Markdown deve conter, nesta ordem, as seções: Objetivo, Contexto, Atores, Capacidades,
Regras de Negócio, Restrições, Exceções, Acceptance Criteria e Open Questions.
A seção Open Questions só entra quando houver dúvida em aberto; cada item é uma linha "- <pergunta>".
Nenhuma informação técnica no corpo.
Reutilize o conhecimento fornecido: não repita o que os documentos de contexto já resolvem.
Responda somente com o JSON do schema fornecido.
```

**BR — user:**

```
# Necessidade
<demand.title>

<demand.body>

# Contexto do método (resolvido por META-001)
<para cada MethodDocument: "## <doc_id> — <title>\n<content>">

# Conhecimento prévio do repositório (BM25 sobre artefatos anteriores)
<para cada hit: "## <heading>\n<text>">

Gere a Business Rule da necessidade acima. Se algo for ambíguo ou incerto, registre em
Open Questions em vez de assumir. Não invente ACs que não derivem da necessidade.
```

**SPEC — system:**

```
Você executa a Skill SK-002 — Technical Planning do método Blueprint.
Papel: Software Architect. Transforme a BR em um conjunto de Functional Specifications.
Nunca gere código, nunca escolha tecnologias (a Technology Pack já vem resolvida), nunca crie
regras de negócio e nunca modifique a BR.
Cada SPEC tem responsabilidade única: 1 SPEC = 1 capacidade técnica. Minimize acoplamento;
SPECs independentes devem poder ser implementadas em paralelo.
Todo Acceptance Criteria da BR precisa estar em pelo menos uma SPEC, em "Acceptance Criteria
atendidos". Nenhuma AC pode ficar sem cobertura.
Complexidade de cada SPEC: LOW, MEDIUM, HIGH ou VERY HIGH.
O corpo Markdown de cada SPEC deve conter, nesta ordem, as 14 seções: Objetivo, Escopo,
Responsabilidade, Entradas, Saídas, Fluxo principal, Fluxos alternativos, Validações, Failures,
Pré-condições, Pós-condições, Acceptance Criteria atendidos, Dependências e Blueprint Documents
necessários.
As arestas do grafo usam o feature da SPEC dentro deste lote como identificador. Em "tests", a
SPEC de testes é o parent e a SPEC testada é o child.
Responda somente com o JSON do schema fornecido.
```

**SPEC — user:**

```
# Business Rule de origem
<conteúdo integral da BR (id, frontmatter e body)>

# Acceptance Criteria da BR
- AC-001: ...
- AC-002: ...

# Contexto do método (resolvido por META-001)
<para cada MethodDocument: "## <doc_id> — <title>\n<content>">

# Conhecimento prévio do repositório (BM25 sobre artefatos anteriores)
<para cada hit: "## <heading>\n<text>">

Gere o Specification Graph e as Functional Specifications. Cada SPEC cobre exatamente as
responsabilidades que declara em "Acceptance Criteria atendidos".
```

## 6. Tarefas

1. `server/app/services/generator.py` — `GenerationContext`, `MethodContext`,
   `RepoContext`, `MethodDocument`, `build_client`, `LLMUnavailable`, schemas, prompts,
   `render_document`, `resolve_method_context`, `generate_br`, `generate_specs`,
   `render_doubts_seed`.
2. `server/app/routers/generation.py` — `POST /api/generation/demands/{id}/br`,
   `POST /api/generation/artifacts/{id}/specs`.
3. `server/tests/test_generation.py` — §8.

## 7. Critérios de aceitação

- [ ] `POST /api/generation/demands/{id}/br` devolve BR com os 12 campos de frontmatter
      de SK-001 §16, na ordem, e as 9 seções de SK-001 §14 no corpo.
- [ ] `POST /api/generation/artifacts/{id}/specs` devolve SPECs com os 15 campos de
      frontmatter de SK-002 §15 e as 14 seções de SK-002 §10.
- [ ] Toda AC da BR aparece em `acceptanceCriteria` de ≥1 SPEC gerada.
- [ ] `spec_edges` contém uma aresta `derives_from` por SPEC, apontando para a BR.
- [ ] `depends_on` e `tests` do grafo do modelo viram arestas com o ID real do servidor.
- [ ] `doubtsIndex` do frontmatter aponta para `duvidas-br/<id>.md` / `duvidas-spec/<id>.md`,
      e o arquivo é devolvido em `doubts_file`/`doubts_files` com o formato canônico v1.
- [ ] Cada Open Question do corpo virou linha em `doubts` com `source='user'`.
- [ ] Chamada repetida de `generate-br` devolve **200**, `created: false`, o **mesmo** id,
      e **não** faz chamada de LLM nem INSERT.
- [ ] `LLMUnavailable` → **503** `llm_unavailable`, nada gravado em `artifacts`,
      evento `generation_failed` presente, demanda de status `claimed` volta para `open`.
- [ ] Demanda `in_progress` que falha **permanece** `in_progress` (evento com
      `detail.reset=false`).
- [ ] Demanda em `done` → **409** `illegal_transition`, sem chamada de LLM.
- [ ] F7 ausente → `context.degraded = true` e o artefato **é gerado** mesmo assim.
- [ ] F3 ausente → corpus do método lido localmente, `degraded_reason` preenchido.
- [ ] Duas gerações concorrentes → IDs distintos (`BR-013` e `BR-014`), nenhum duplicado.
- [ ] O servidor **não** escreve nenhum arquivo do repo de dev (assert: nenhum path de
      escrita fora de `settings.repo_root`).
- [ ] `ANTHROPIC_BASE_URL=http://127.0.0.1:20128/v1` produz requisição em
      `http://127.0.0.1:20128/v1/messages` (não `/v1/v1/messages`).
- [ ] `pytest server/tests` verde.

## 8. Testes (`server/tests/test_generation.py`)

Sem chamada real à API: o `GenerationContext.client` recebe um fake que devolve o JSON do
schema.

| Teste | Verifica |
| --- | --- |
| `test_generate_br_frontmatter_matches_skill_template` | 12 campos de SK-001 §16, ordem exata |
| `test_generate_br_body_has_all_sections` | 9 seções de SK-001 §14 |
| `test_generate_br_creates_doubts_file` | path, formato canônico v1, `doubtsIndex` bate |
| `test_generate_br_open_questions_become_doubt_rows` | 1 Open Question → 1 linha em `doubts`, `source='user'` |
| `test_generate_specs_frontmatter_matches_skill_template` | 15 campos de SK-002 §15 |
| `test_generate_specs_body_has_14_sections` | 14 seções de SK-002 §10 |
| `test_spec_edges_derives_from_br` | uma aresta `derives_from` por SPEC |
| `test_spec_edges_depends_on_resolved` | `parentFeature` → ID real no `spec_edges` |
| `test_spec_edges_unresolved_is_skipped_with_event` | aresta órfã não gravada + evento `spec_edge_unresolved` |
| `test_every_ac_covered_by_some_spec` | union de `acceptanceCriteria` ⊇ ACs da BR |
| `test_generate_br_is_idempotent` | 2ª chamada → mesmo id, `created=false`, 0 chamadas ao fake |
| `test_generate_specs_is_idempotent` | idem para SPECs |
| `test_ids_are_unique_under_concurrency` | 2 gerações → 2 ids distintos, sem colisão |
| `test_llm_failure_returns_503_and_resets_demand` | 503 + demanda `open` + evento `generation_failed` |
| `test_llm_failure_writes_nothing` | `artifacts` sem linha nova |
| `test_demand_in_progress_stays_in_progress_on_failure` | status preservado, `detail.reset=false` |
| `test_demand_done_returns_409` | 409 sem chamada ao LLM |
| `test_invalid_module_feature_returns_422` | slug inválido → 422, nada gravado |
| `test_context_fallback_without_f7` | `degraded=true`, `repo_hits=0`, artefato gerado |
| `test_context_fallback_without_f3` | `degraded_reason` cita "F3 pendente" |
| `test_base_url_strips_v1_suffix` | `build_client()` usa base sem `/v1` |
| `test_server_never_writes_dev_repo` | nenhum arquivo criado fora do `repo_root` |
| `test_route_requires_scope` | token sem `demand:write` → 403 |

## 9. Fora de escopo

- **Regeneração / versionamento** de artefato: se a BR existe, ela é devolvida. Editar a
  BR é fluxo do repo (`sync` do F4). Upstream de versão nova: F4 (tabela `artifacts`
  tem `version`, mas não tem histórico).
- Escrever no repo de dev (é o kit, F8).
- Aprovar, revisar, pipeline de 3 revisores (é o F6).
- Prompt caching, batches, embeddings, fallback de modelo (`claude-opus-5-5` é o modelo
  fixo do Contrato Comum §5).
- Indexação do artefato no RAG (é o F7).

## 10. Referências

- Contrato Comum §3 (convenções de API), §4 (banco), §5 (env), §8 (ownership), §7.3
  (contrato do gerador), §9 (dependências e ondas).
- Design master §7.1 (invariantes), §8 (DDL), §9.2 (ciclo do artefato), §12 (papel do
  gerador), §18 (geração de BR/SPEC), §19 (erros), §20 (testes).
- SK-001 §14 (corpo da BR), §16 (frontmatter da BR).
- SK-002 §8 (grafo), §9 (dependências), §10 (14 seções), §13 (AC mapping), §15
  (frontmatter da SPEC), §17 (complexidade).
- META-001 §5/§6 (resolução), §8 (TP), §9 (RI).
- META-004 §4/§6/§7/§8 (paths, nomes, metadados).
- META-006 §5 (sincronização inicial), §6 (status), §8 (approval gate), §9 (regras de
  arquivo).
- META-000 §8 (resolução de conhecimento), §9 (evolução sem duplicação).
- F1 §3.3 (`db.get_pool`), §3.4 (`config.settings`), §3.5 (`auth.require_scope`).
- F2 §4 (regras do linter), §5.2 (normalização de headings).
