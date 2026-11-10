# Fase F6 — Aprovação e Revisão

| Campo | Valor |
| --- | --- |
| **Fase** | F6 |
| **Data** | 2026-11-10 |
| **Depende de** | F1, F2, F4, F5 |
| **Bloqueia** | F7, F9, F10 |
| **Onda** | 4 (paralelo com F10) |
| **Contrato** | `design/specs/2026-11-10-contrato-comum.md` §7.4 e §7.5 |

> Reler o **Contrato Comum** §7.4, §7.5 e §8.1 antes de começar. Em conflito, o contrato
> prevalece sobre esta spec. Não reescreva o que F2 (linter) e F4 (ciclo de vida) já
> definiram — **use**.

## 1. Objetivo

Substituir a instrução "o agente deve rodar os 3 revisores" (META-005) por um **evento
determinístico do servidor**: o linter roda primeiro, depois Blind Hunter, Edge Case
Hunter e Acceptance Auditor, **nesta ordem e sequencialmente**. Achados viram pendências
registradas (tabela `doubts` + arquivo de dúvidas do artefato), e o artefato só vira
`approved` quando o linter estiver limpo e **toda** pendência estiver `cleaned`
(approval gate do META-006 §8).

**Critério de sucesso da fase:** `POST /api/artifacts/{id}/approve` (delegado do F4) roda
linter + 3 revisores, grava achados como linhas em `doubts`, publica os 3 artefatos de
revisor e o arquivo de dúvidas para o `pull` do F4, e **não** aprova o artefato enquanto
houver pendência aberta.

**Falha de LLM não bloqueia nada** (design master §19): `verdict="pending"`,
`llm_available=False`, e o commit/push segue.

## 2. Arquivos que esta fase pode criar/editar

```
server/app/services/reviewers.py
server/app/services/doubts.py
server/app/routers/reviews.py
server/tests/test_pipeline.py
server/tests/test_doubts.py
```

**Não tocar:** `server/app/lint/` (F2 — só ler), `server/app/services/{lifecycle,demands,artifacts,claims,commits}.py`
e `server/app/routers/{demands,claims,artifacts,commits}.py` (F4 — só ler/usar),
`server/app/services/generator.py` (F5 — só ler/usar), `server/app/db.py` (F1),
`tools/`, `docs/`, qualquer `design/specs/`.

## 3. Contrato (Contrato Comum §7.4 e §7.5 — repetido aqui)

```python
# server/app/services/reviewers.py
async def run_pipeline(artifact: Artifact) -> PipelineResult: ...

# server/app/services/doubts.py
async def raise_doubt(artifact_id: str, question: str, source: str) -> Doubt: ...
async def resolve_doubt(doubt_id: str) -> Doubt: ...
def render_doubts_file(artifact_id: str, doubts: list[Doubt]) -> str: ...
```

```python
# server/app/models.py (F1) — reusar, não redefinir
@dataclass(frozen=True)
class Doubt:
    id: str; artifact_id: str; question: str
    status: str            # pending | deferred | cleaned
    source: str            # reviewer | linter | user
    raised_at: datetime; resolved_at: datetime | None
```

`PipelineResult` (contrato §7.4): `{verdict, findings[], linter_findings[], doubts_written,
llm_available}`.

**Achado de revisor** (contrato §7.4, forma exata):

```json
{"severity":"blocking","title":"...","detail":"...","ac":"AC-003","suggestion":"..."}
```

## 4. Decisões que o contrato não cobre

| # | Decisão | Justificativa |
| --- | --- | --- |
| D1 | **`PipelineResult` tem os 5 campos do contrato, mais** `review_artifacts`, `stages`, `approval_ready`, `blocking_reasons`, `artifact_status`. Os 5 do contrato mantêm nome e tipo. | O contrato fixa o mínimo; os extras são o que o F4 precisa para decidir a transição e o que o painel mostra. |
| D2 | **Veredito ∈ {`clean`, `suggestions`, `blocking`, `pending`}** (o DDL de `reviews` cita 3; `pending` é exigido pelo design master §19 para indisponibilidade de LLM). Precedência: (1) erro do linter → `blocking`; (2) LLM indisponível → `pending`; (3) achado `blocking` → `blocking`; (4) achado `suggestion`/`deferred` → `suggestions`; (5) nada → `clean`. | Um linter com erro é falha determinística e conhecida — não pode ser mascarada por `pending`. |
| D3 | **Erro do linter interrompe o pipeline antes dos 3 revisores** (nenhum token gasto). `warning` do linter vira dúvida `deferred` e não bloqueia. | Design master §12: "artefato com frontmatter quebrado é barrado na hora". |
| D4 | **`severity` → `doubts.status`**: `blocking`→`pending`, `suggestion`→`deferred`, `deferred`→`deferred`. | Design master §11.3 + META-006 §8: só `pending` (não `cleaned`) trava a aprovação; `deferred` é pendência registrada que não trava. |
| D5 | **O conteúdo dos artefatos de revisor e do arquivo de dúvidas é publicado em `events.payload` (jsonb).** Não há tabela nova: o DDL do design master §8 é fechado. | Requisito do enunciado. `events` é append-only e é o canal de publicação para o `pull` do F4. |
| D6 | **`GET /api/artifacts/{id}/doubts` fica em `app/routers/artifacts.py` (owner F4)** e delega para `app/services/doubts.py` do F6 via import tardio. F6 **não** define essa rota. | Design master §17 põe a rota em "Artefatos"; F4 é dono de `artifacts.py`. Evitar rota duplicada com o mesmo path em dois routers. |
| D7 | **`POST /api/reviews` exige uma linha em `commits`** (`reviews.commit_id` é FK). F6 resolve via `app/services/commits.py::upsert_commit` (F4); enquanto F4 não existir, F6 faz o `INSERT` direto no **único** ponto de troca, `_resolve_commit_id()`. | `reviews.commit_id` não pode ser nulo. |
| D8 | **F6 não edita `app/routers/artifacts.py`.** O handler delegado fica em `app/services/reviewers.py`; o handler do F4 chama `run_pipeline` por import tardio. Handoff exato em §6. | Contrato Comum §8.1 (prevalece). |
| D9 | **F6 importa `build_client` e `LLMUnavailable` de `app.services.generator` (F5)** em vez de duplicar a construção do cliente (e o tratamento do sufixo `/v1` do `ANTHROPIC_BASE_URL`). | Uma fonte de verdade para o cliente. F5 é pré-requisito de F6 (onda 3 → onda 4). |
| D10 | **Toda mudança no arquivo de dúvidas publica um novo evento `doubts_file_rendered`** com o conteúdo **completo**; o `pull` do F4 usa o **último** evento por `artifact_id`. | `events` é append-only; o pull lê o estado mais recente. |
| D11 | **O catálogo central (`duvidas-br.md` / `duvidas-spec.md`) é renderizado pelo F6** e publicado em `events` type `doubts_catalog_rendered`, listando **só** artefatos com pendência aberta. | META-006 §3/§9. |
| D12 | **`run_pipeline(artifact)` obtém o pool por `await get_pool()`** (F1), internamente. A assinatura do contrato §7.4 não muda. | Contrato §7.4 fixa a assinatura. |
| D13 | **A transição de status do artefato é aplicada pelo F6**, chamando `lifecycle.apply_artifact_transition` do F4. O handler do F4 **não** decide — ele só devolve o `PipelineResult`. | Invariante 2 do design master §7.1: toda transição passa por `services/lifecycle.py`. |

## 5. Detalhes de implementação

### 5.1 Pipeline — ordem fixa e sequencial

```
run_pipeline(artifact)
  ↓
[1] LINTER            (app/lint — Python puro, sem LLM, determinístico)
  ↓  erro?  → para aqui (D3)
[2] Blind Hunter      (LLM)
  ↓
[3] Edge Case Hunter  (LLM)
  ↓
[4] Acceptance Auditor(LLM)
  ↓
grava achados em doubts + publica artefatos de revisor + arquivo de dúvidas
  ↓
approval gate (§5.7) → transiciona o artefato (§5.7)
```

- **Sequencial, nessa ordem.** Sem paralelismo: META-005 exige ordem fixa, e o
  Acceptance Auditor recebe a BR de origem (que os caçadores não recebem).
- Cada etapa registra uma linha em `events` no fim (`pipeline_stage`), com
  `payload={"stage": "...", "ok": bool, "findings": n, "ms": int}` — é o log de ordem.

```python
@dataclass(frozen=True)
class PipelineResult:
    verdict: str                       # clean | suggestions | blocking | pending
    findings: list[dict]               # achados dos 3 revisores
    linter_findings: list[dict]        # findings do F2 (serializados)
    doubts_written: int
    llm_available: bool
    # extras (D1)
    review_artifacts: list[dict]       # [{"reviewer": "...", "path": "...", "content": "..."}]
    stages: list[dict]                 # [{"stage": "...", "ok": bool, "findings": n}]
    approval_ready: bool
    blocking_reasons: list[str]
    artifact_status: str               # status do artefato depois do pipeline

    def to_dict(self) -> dict: ...
```

### 5.2 Estágio 1 — LINTER (F2, chamada direta ao módulo)

Chamada **direta ao módulo**, não via HTTP: `app/lint` é biblioteca pura (Contrato Comum
§2), local e determinística.

```python
from app.lint import ArtifactDoc, lint_batch, MethodCorpus, SyncedArtifacts, CompositeUniverse
```

```python
doc = ArtifactDoc(
    path=artifact.path,
    content=artifact.content,
    frontmatter=frontmatter,      # yaml.safe_load do bloco --- do conteúdo
    body=body,
    kind=artifact.kind,           # "br" | "spec"
    repo_id=artifact.repo_id,
)
universe = CompositeUniverse(
    MethodCorpus(settings.repo_root),
    SyncedArtifacts(await get_pool()),
)
findings = lint_batch([doc, *sibling_specs], universe)
```

- `sibling_specs` = os artefatos `kind='spec'` da **mesma demanda** (`demand_id`), lidos
  de `artifacts`. Sem eles, a regra `BR-004` (cobertura de AC) acusaria AC não coberta
  num lint de artefato isolado. O linter é do F2 — F6 não reimplementa regra nenhuma.
- `error` → `verdict="blocking"`, `blocking_reasons` = ["linter: <rule> — <message>"],
  pipeline **para** (D3). `warning` → linha em `doubts` com `status='deferred'`,
  `source='linter'`, e segue.
- `LINK-001` é sempre `error` (Contrato Comum §7.2) → bloqueia.
- O linter **não** precisa de LLM e não falha por indisponibilidade externa.

### 5.3 Estágios 2–4 — os 3 revisores (LLM)

Cada revisor é **uma chamada** de Claude API, com o mesmo cliente do F5 (D9):

```python
from app.services.generator import build_client, LLMUnavailable   # F5

async with client.messages.stream(
    model=settings.llm_model,
    max_tokens=16000,
    thinking={"type": "adaptive"},
    output_config={"effort": "high", "format": {"type": "json_schema", "schema": FINDINGS_SCHEMA}},
    system=SYSTEM[reviewer],
    messages=[{"role": "user", "content": user_prompt(reviewer, artifact, ctx)}],
) as stream:
    final = await stream.get_final_message()
```

Schema (um por chamada):

```json
{
  "type": "object",
  "properties": {
    "findings": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "severity": {"type": "string", "enum": ["blocking", "suggestion", "deferred"]},
          "title": {"type": "string"},
          "detail": {"type": "string"},
          "ac": {"type": "string"},
          "suggestion": {"type": "string"}
        },
        "required": ["severity", "title", "detail", "ac", "suggestion"],
        "additionalProperties": false
      }
    }
  },
  "required": ["findings"],
  "additionalProperties": false
}
```

- `ac` = id da AC afetada (`AC-003`) ou string vazia `""` quando o achado não é de uma AC
  específica. Nunca `null` (o schema é estrito).
- `severity`: `blocking` (impede aprovação), `suggestion` (recomendação forte, não
  impede), `deferred` (pode ser tratado depois).
- `stop_reason` é checado antes de ler o conteúdo (idem F5 §5.1): `max_tokens` e
  `refusal` contam como LLM indisponível para aquela etapa.

**Contexto entregue a cada revisor:**

| revisor | artefato inteiro | conhecimento META-001 | ACs da BR de origem |
| --- | --- | --- | --- |
| Blind Hunter | sim | **não** (é cego de propósito) | **não** |
| Edge Case Hunter | sim | sim | sim |
| Acceptance Auditor | sim | sim | sim |

- O conhecimento resolvido por META-001 é o **mesmo** `MethodContext` que o F5 montou:
  `from app.services.generator import resolve_method_context` (F5) → reuso, sem duplicar
  o algoritmo de resolução.
- As ACs da BR de origem: para uma SPEC, a BR é achada pelo `createdFrom` do frontmatter
  do artefato; para uma BR, são as ACs do próprio corpo (regex `\bAC-\d{3}\b`).

**Prompts (texto exato).**

*Blind Hunter* — `system`:

```
Você é o Blind Hunter. Papel: revisor cego de artefato Blueprint.
Você recebe apenas o artefato e as regras do método. De propósito você NÃO recebe a BR de
origem, nem o contexto resolvido, nem as ACs: existe para pegar o que o autor não percebeu.
Procure, sem seguir a intenção do autor:
- afirmações que não podem ser verificadas ("rápido", "robusto", "moderno", "seguro", "etc.",
  "e demais");
- placeholders, TODO, FIXME, "a definir", "em breve", "a ser detalhado";
- contradições internas entre duas seções do próprio artefato;
- comportamento implícito sem cenário observável;
- AC sem Given/When/Then ou sem resultado observável;
- seção obrigatória vazia, com placeholder ou com uma frase que não diz nada.
NãoSugira implementação, não reescreva o artefato: reporte o que está errado.
Cada achado: {"severity","title","detail","ac","suggestion"}.
severity: "blocking" se o artefato não pode ser implementado ou revisado sem a correção;
"suggestion" se é melhoria real; "deferred" se é melhoria postergável.
ac: id da AC afetada ("AC-003") ou "" se não houver.
Se não houver achado, devolva {"findings": []}.
```

*Edge Case Hunter* — `system`:

```
Você é o Edge Case Hunter. Papel: caçar condições de contorno que o artefato não cobre.
Você recebe o artefato inteiro, as ACs da BR de origem e o conhecimento resolvido do método.
Para cada Acceptance Criteria da BR, derive mentalmente: entrada vazia; valor no limite
e valor fora do limite; entrada duplicada e reenvio; concorrência sobre o mesmo recurso;
requisição sem permissão; falha parcial de dependência externa; dado corrompido ou ausente;
cancelamento no meio do fluxo; operação repetida (idempotência).
Para cada AC, verifique se o artefato define o comportamento nesses casos.
Achado = gap concreto, não genérico: "quando <situação>, o artefato não diz <o que>".
Cada achado: {"severity","title","detail","ac","suggestion"}.
ac é obrigatório: é a AC cujo comportamento ficou indefinido.
Se não houver gap, devolva {"findings": []}.
```

*Acceptance Auditor* — `system`:

```
Você é o Acceptance Auditor. Papel: verificar rastreabilidade e cobertura.
Você recebe o artefato inteiro, a BR de origem com todas as Acceptance Criteria e a lista
de SPECs do grafo.
Verifique:
1. Toda AC da BR aparece em "Acceptance Criteria atendidos" de pelo menos uma SPEC. AC sem
   cobertura é achado "blocking".
2. Toda SPEC declara ACs que existem na BR. AC citada que não existe na BR é "blocking".
3. Toda SPEC preenche as 14 seções obrigatórias com conteúdo real, não placeholder.
   Seção vazia ou placeholder é achado "blocking".
4. Toda dependência declarada existe no grafo informado e o grafo não tem ciclo.
5. A "Responsabilidade" da SPEC descreve uma única responsabilidade técnica.
Cada achado: {"severity","title","detail","ac","suggestion"}.
ac é a AC em rastreio; use "" apenas nos achados 3, 4 e 5.
Se a auditoria fechar limpa, devolva {"findings": []}.
```

`user` (mesmo esqueleto para os 3, com as seções conforme a tabela acima):

```
# Artefato sob revisão
<conteúdo integral: frontmatter + corpo>

# Acceptance Criteria da BR de origem
- AC-001: ...

# Conhecimento resolvido (META-001)
## <doc_id> — <title>
<content>

Revise o artefato acima e devolva os achados no formato definido.
```

### 5.4 Achados, veredito e severidades

- `findings` do `PipelineResult` = concatenação dos achados dos 3 revisores, **na ordem
  dos revisores** (Blind → Edge → Acceptance), preservando a ordem dentro de cada um.
- `linter_findings` = findings do F2 serializados como
  `{"rule","severity","message","path","line","detail"}` (a dataclass `Finding` do F2
  tem esses campos).
- Cada achado de severidade `blocking` ou `suggestion`/`deferred` vira **uma linha em
  `doubts`** (§5.5). `doubts_written` = total de linhas criadas nesta execução (achados +
  warnings do linter).

```python
FINDING_SEVERITY_TO_DOUBT_STATUS = {
    "blocking": "pending",
    "suggestion": "deferred",
    "deferred": "deferred",
}
```

### 5.5 Dúvidas — `app/services/doubts.py`

```python
async def raise_doubt(artifact_id: str, question: str, source: str) -> Doubt: ...
async def resolve_doubt(doubt_id: str) -> Doubt: ...
def render_doubts_file(artifact_id: str, doubts: list[Doubt]) -> str: ...
async def list_doubts(artifact_id: str) -> list[Doubt]: ...      # extra (D6)
async def render_catalog(kind: str) -> str: ...                  # extra (D11)
```

- `raise_doubt` insere com `status='pending'` e `source` ∈ {`reviewer`,`linter`,`user`}
  (DDL §8). `source` fora do enum → `ValueError`.
- Para achados de severidade `suggestion`/`deferred`, o pipeline usa a função interna
  `_insert_doubt(artifact_id, question, status, source)` (status `deferred`), **não** a
  pública `raise_doubt` — a assinatura pública não tem severidade (Contrato Comum §7.5).
- `resolve_doubt` → `status='cleaned'`, `resolved_at=now()`, re-renderiza e publica o
  arquivo de dúvidas (D10). Dúvida inexistente → 404.
- `render_doubts_file(artifact_id, doubts)` é **síncrona e pura** (não toca o banco) —
  recebe a lista e devolve o markdown. Formato **canônico v1**, idêntico ao que o F5 cria
  na geração (§5.7 do F5):

```markdown
---
id: BR-013
artifactId: BR-013
status: pending
updatedAt: "2026-11-10T12:34:56Z"
---

# Dúvidas — BR-013

Pendências: 2

| id | status | source | question | raised_at | resolved_at |
| --- | --- | --- | --- | --- | --- |
| 6f1d2c8e-0a3b-4f5d-9e77-2b1c0a9d4e55 | pending | reviewer | [AC-003] Regra de bloqueio sem critério verificável | 2026-11-10T12:34:56Z | — |
| 9b7c4a10-55f2-4d8b-a1c3-6e90d2f4b8a7 | cleaned | user | Senha pode ser redefinida por e-mail ou por token? | 2026-11-10T12:00:00Z | 2026-11-10T12:20:10Z |
```

- `status` do arquivo segue META-006 §6: `draft`→`draft`; `pending`, `on user review` e
  `on agents review`→`pending`; `approved`→`approved`.
- `Pendências: N` = contagem de linhas com `status != 'cleaned'`.
- `question` é o texto já montado: `"[<ac>] <title> — <detail>"` (ou `"[<ac>] <title>"` se
  não houver detalhe), truncado em 500 caracteres.
- Catálogo central (`render_catalog`): só artefatos com **pelo menos uma** pendência
  `status != 'cleaned'`. Cabeçalho:

```markdown
# Dúvidas de SPEC — pendências abertas

| artifact_id | path | abertas | atualizado_em |
| --- | --- | --- | --- |
| SPEC-024 | docs/SPEC/login/login-api.md | 1 | 2026-11-10T12:34:56Z |
```

- `raise_doubt`/`resolve_doubt` publicam o arquivo renderizado e o catálogo (§5.6).

### 5.6 Publicação para o F4 — `events` (D5)

Não há tabela nova. O F6 publica em `events.payload` (jsonb):

```sql
INSERT INTO events (demand_id, artifact_id, type, payload, actor)
VALUES ($1, $2, 'review_artifact_written', $3::jsonb, $4);
```

| `events.type` | `payload` | quem consome |
| --- | --- | --- |
| `review_artifact_written` | `{"reviewer":"blind-hunter","path":"docs/implementation-artifacts/review-login-login-blind-hunter.md","content":"<markdown>","sha":"<sha256>","findings":3,"artifact_id":"SPEC-024"}` | `pull` do F4 (escreve o arquivo no repo de dev) |
| `doubts_file_rendered` | `{"artifact_id":"SPEC-024","path":"docs/implementation-artifacts/duvidas-spec/SPEC-024.md","content":"<markdown>","sha":"<sha256>"}` | `pull` do F4 |
| `doubts_catalog_rendered` | `{"kind":"spec","path":"docs/implementation-artifacts/duvidas-spec.md","content":"<markdown>","sha":"<sha256>"}` | `pull` do F4 |
| `pipeline_stage` | `{"stage":"linter\|blind-hunter\|edge-case-hunter\|acceptance-auditor","ok":true,"findings":2,"ms":8420}` | painel / auditoria |
| `pipeline_completed` | `{"verdict":"blocking","llm_available":true,"doubts_written":3,"linter_findings":1,"approval_ready":false,"artifact_status":"on agents review"}` | painel / F10 |

- O `pull` do F4 lê `artifacts` (os documentos) + os **últimos** eventos
  `review_artifact_written`, `doubts_file_rendered` e `doubts_catalog_rendered` por
  `artifact_id`/`kind` (`ORDER BY id DESC`) e escreve os arquivos no repo de dev.
- `actor` = `user_id` de quem aprovou (sessão web) ou `NULL` quando o pipeline roda sem
  usuário (chamada interna).

### 5.7 Approval gate e status do artefato

Regra (META-006 §8 + design master §9.2): o artefato só pode ir para `approved` quando

1. o linter passou sem `error`;
2. os 3 revisores rodaram (`llm_available=True`) e nenhum achado é `blocking`;
3. **toda** linha em `doubts` do artefato está com `status='cleaned'`.

```python
open_doubts = await list_open_doubts(artifact.id)   # status != 'cleaned'
approval_ready = (not linter_errors) and llm_available and (not blocking_findings) \
                 and (len(open_doubts) == 0)
```

- `blocking_reasons` lista o que impediu: `["linter: BR-001 — frontmatter ausente",
  "achado blocking: Regra de bloqueio sem critério verificável (AC-003)",
  "dúvida aberta: 6f1d2c8e-…"]`.
- Se `approval_ready` → o F6 chama a transição **do F4**:

```python
# app/services/lifecycle.py (F4) — função que F6 espera existir
async def apply_artifact_transition(pool: asyncpg.Pool, artifact_id: str, target: str) -> str: ...
```

  `target="approved"`, de `on agents review`. Se F4 ainda não expor a função (pendente),
  import tardio + `except ImportError` → F6 faz o `UPDATE artifacts SET status=$2,
  updated_at=now() WHERE id=$1 AND status='on agents review'` (só a partir de
  `on agents review`, que é o único estado de origem válido).
- Se **não** `approval_ready` → o artefato **fica** em `on agents review`. Nada trava o
  time: o pipeline só registra.
- `doubts` com `status='deferred'` **bloqueiam** a aprovação? **Não** — só `pending` e
  `deferred` contam como "não cleaned", e META-006 §8 exige todas `cleaned`. Aqui há uma
  divergência entre META-005 ("só concluir depois de tratar achados reais **ou**
  classificá-los como deferidos") e META-006 §8 ("somente quando todas as dúvidas
  estiverem `cleaned`"). **Decisão: META-006 §8 prevalece** (é o gate normativo e é o
  que o F4 valida no `approve`); `deferred` também precisa virar `cleaned` (o agente
  registra a decisão de deferir como resolução). Isso está registrado em
  `blocking_reasons` como `"dúvida deferida ainda não resolvida"`.
- A transição de status **nunca** é feita direto no handler HTTP do F4 (invariante 2) —
  o F6 faz, e sempre via `lifecycle`.

### 5.8 Falha de LLM (design master §19)

- Se **qualquer** um dos 3 revisores falhar (`LLMUnavailable`, timeout, recusa,
  `max_tokens`): `verdict="pending"`, `llm_available=False`, e o pipeline **para** (não
  roda os revisores restantes — ordem fixa, e um pipeline incompleto não produz veredito
  confiável).
- **Nada é bloqueado**: nenhuma dúvida é criada a partir de etapas que não rodaram, o
  artefato **não** é promovido, e o commit/push do repo de dev **não** trava.
- Os achados dos revisores que **rodaram** antes da falha **são mantidos** e registrados
  em `doubts` (são válidos), mas o veredito é `pending`, não `blocking`.
- Evento `pipeline_completed` com `payload.llm_available=false` e
  `payload.error_type="LLMUnavailable"`.
- Falha **só do linter** não é possível: o linter é local e determinístico. Se ele
  estourar exceção, `verdict="blocking"` com `blocking_reasons=["linter: erro interno"]`
  — falha de código, não de infraestrutura externa.

### 5.9 Rotas — `app/routers/reviews.py` (owner F6)

Prefixo `/api` (F1 §3.7). Duas rotas, e só estas.

**`POST /api/reviews`** — review de **commit** (fluxo do hook, design master §13).

- Escopo: `review:write`.
- Body:

```json
{
  "sha": "9f2c1ab4d7e5c6b8a0f1e2d3c4b5a697889900aa",
  "verdict": "clean",
  "findings": [
    {"severity": "suggestion", "title": "Falta teste de borda",
     "detail": "AC-003 não cobre e-mail com ponto no fim", "ac": "AC-003",
     "suggestion": "Adicionar caso com \"a@b.\""}
  ],
  "demand_id": "6f1d2c8e-0a3b-4f5d-9e77-2b1c0a9d4e55",
  "message": "feat(login): adiciona validação de senha",
  "branch": "feat/login",
  "author": "brunosprotte",
  "files": ["src/auth/login.ts"]
}
```

- `verdict` ∈ {`clean`, `suggestions`, `blocking`, `pending`}. `sha` obrigatório,
  `demand_id` obrigatório, `findings` opcional (default `[]`).
- `message`, `branch`, `author`, `files` são opcionais: quando presentes, viram a linha
  em `commits` (D7).

Processamento:

1. Resolve/cria a linha em `commits` (§5.10) → `commit_id`.
2. Grava a review:

```sql
INSERT INTO reviews (commit_id, demand_id, verdict, findings)
VALUES ($1, $2, $3, $4::jsonb)
RETURNING id, commit_id, demand_id, verdict, findings, created_at;
```

3. Transiciona a demanda **via `lifecycle.apply_demand_transition` do F4**:
   - `in_progress → review` (o gatilho de `review` é "commit reportada");
   - se `verdict == 'blocking'` → `review → in_progress` (design master §9.1).
   - Demanda em outro estado → **nenhuma** transição (não é erro: revisão pode chegar
     fora de ordem) e `demand_status` no response mostra o estado real.
4. Grava evento `review_reported` com `payload={"review_id","commit_id","sha","verdict",
   "findings":n,"demand_status"}`.

Response **201**:

```json
{
  "review_id": "b3a91c07-1f2d-4e5a-8c3b-9d0e1f2a3b4c",
  "commit_id": "c4b02d18-2a3e-4f6b-9d4c-0e1f2a3b4c5d",
  "demand_id": "6f1d2c8e-0a3b-4f5d-9e77-2b1c0a9d4e55",
  "sha": "9f2c1ab4d7e5c6b8a0f1e2d3c4b5a697889900aa",
  "verdict": "clean",
  "findings": [],
  "demand_status": "review",
  "created_at": "2026-11-10T12:40:00Z"
}
```

Erros: demanda inexistente → **404**; `sha` vazio → **422**; transição ilegal →
**409** `illegal_transition`; token sem `review:write` → **403**.

**`GET /api/reviews?demand=<demand_id>`**

- Lista as reviews da demanda, **mais recente primeiro**
  (`ORDER BY created_at DESC, id DESC`).
- Sem `demand` → **400** `{"error":{"code":"missing_parameter","detail":{"parameter":"demand"}}}`.
- Demanda inexistente → **404**.
- Escopo: leitura; exige token/sessão do mesmo repo (sem escopo de escrita).

Response **200**:

```json
{
  "demand_id": "6f1d2c8e-0a3b-4f5d-9e77-2b1c0a9d4e55",
  "reviews": [
    {"id": "b3a91c07-...", "commit_id": "c4b02d18-...", "sha": "9f2c1ab4...",
     "verdict": "clean", "findings": [], "created_at": "2026-11-10T12:40:00Z"}
  ]
}
```

> `reviews.commit_id` → `commits.sha` para expor o `sha` no GET (join).

**Rotas que F6 NÃO define** (design master §17, dono F4):
`GET /api/artifacts/{id}/doubts` (§5.11).

### 5.10 `commits` (D7)

`reviews.commit_id` é FK NOT NULL → toda review de commit precisa de uma linha em
`commits`. F6 **não** duplica o service do F4:

```python
# app/services/commits.py (F4) — função que F6 espera existir
async def upsert_commit(pool, demand_id: str, repo_id: str, sha: str, message: str | None,
                         branch: str | None, author: str | None,
                         files: list[str] | None) -> str: ...   # devolve commit_id
```

Fallback enquanto F4 não existir (ponto único de troca, `_resolve_commit_id()`):

```sql
INSERT INTO commits (demand_id, repo_id, sha, message, branch, author, files)
VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)
RETURNING id;
```

Idempotente por `(demand_id, sha)`: se já existe, devolve o `id` existente.

### 5.11 `GET /api/artifacts/{id}/doubts` (rota do F4, dados do F6 — D6)

O F4 implementa a rota; o F6 fornece o dado:

```python
# app/routers/artifacts.py (F4)
@router.get("/artifacts/{artifact_id}/doubts")
async def artifact_doubts(artifact_id: str, ...):
    from app.services.doubts import list_doubts   # import tardio — F6 pode não existir
    ...
```

F6 expõe:

```python
async def list_doubts(artifact_id: str) -> list[Doubt]: ...
```

e o F4 monta o response:

```json
{
  "artifact_id": "SPEC-024",
  "open_count": 1,
  "doubts": [
    {"id": "6f1d2c8e-...", "status": "pending", "source": "reviewer",
     "question": "[AC-003] Regra de bloqueio sem critério verificável",
     "raised_at": "2026-11-10T12:34:56Z", "resolved_at": null}
  ],
  "file": {"path": "docs/implementation-artifacts/duvidas-spec/SPEC-024.md",
           "content": "---\nid: SPEC-024\n..."}
}
```

O campo `file` vem do **último** evento `doubts_file_rendered` daquele `artifact_id`.

## 6. Handoff com o F4 — `POST /api/artifacts/{id}/approve` (D8)

**Escolha: F6 NÃO edita `app/routers/artifacts.py`.** O Contrato Comum §8.1 já resolve:
o handler delegado fica em `app/services/reviewers.py` e o **F4** chama
`await reviewers.run_pipeline(...)` por **import tardio**, para não quebrar o import do
F4 caso o F6 ainda não exista.

O que o F4 precisa ter no handler (é o que o F4 escreve na onda 2; o F6 apenas publica a
implementação):

```python
# app/routers/artifacts.py — PROPRIEDADE DO F4. Não editar a partir do F6.
from fastapi import APIRouter, HTTPException
from app.auth import require_user

router = APIRouter()

@router.post("/artifacts/{artifact_id}/approve")
async def approve_artifact(artifact_id: str, user=Depends(require_user)):
    from app.services import reviewers          # import tardio: F6 pode não existir
    from app.db import fetchrow
    try:
        artifact = await fetchrow(get_pool(), "SELECT * FROM artifacts WHERE id = $1", artifact_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail={"code": "not_found"})
        result = await reviewers.run_pipeline(artifact)
        return result.to_dict()
    except ImportError:
        raise HTTPException(status_code=503, detail={"code": "pipeline_unavailable"})
```

**Se o F4 já tiver publicado a rota com o 503 fixo** (versão literal do Contrato Comum
§8.1, sem o delegate), o handoff é **um hunk de 6 linhas** no arquivo do F4, e a
propriedade do arquivo **continua do F4** (§6.2 do Contrato Comum: "a fase que editar por
último fica com a propriedade" — o hunk entra no commit da F6, que é a última a editar,
mas o arquivo segue listado como F4 na matriz de ownership):

```diff
--- a/server/app/routers/artifacts.py
+++ b/server/app/routers/artifacts.py
@@
 @router.post("/artifacts/{artifact_id}/approve")
 async def approve_artifact(artifact_id: str, user=Depends(require_user)):
-    raise HTTPException(status_code=503, detail={"code": "pipeline_unavailable"})
+    from app.services import reviewers          # import tardio: F6 pode não existir
+    from app.db import fetchrow, get_pool
+    try:
+        artifact = await fetchrow(get_pool(), "SELECT * FROM artifacts WHERE id = $1", artifact_id)
+        if artifact is None:
+            raise HTTPException(status_code=404, detail={"code": "not_found"})
+        result = await reviewers.run_pipeline(artifact)
+        return result.to_dict()
+    except ImportError:
+        raise HTTPException(status_code=503, detail={"code": "pipeline_unavailable"})
```

**O que o F6 garante ao F4:**

1. `app.services.reviewers.run_pipeline(artifact)` existe, é `async`, aceita um
   `Artifact` (dataclass do F1) e devolve `PipelineResult` com `.to_dict()`.
2. `run_pipeline` **não** levanta exceção por indisponibilidade de LLM (vira
   `verdict="pending"`), e **não** levanta `IllegalTransition` — a transição de status é
   aplicada por dentro, tolerando falha (§5.7).
3. Se o F6 ainda não estiver instalado, o `ImportError` cai no 503
   `pipeline_unavailable` — o comportamento do Contrato Comum §8.1 é preservado.
4. F6 **não** altera nenhuma outra rota de `artifacts.py`.

## 7. Tarefas

1. `server/app/services/doubts.py` — `raise_doubt`, `resolve_doubt`, `render_doubts_file`,
   `list_doubts`, `render_catalog`, `_insert_doubt`, publicação dos eventos.
2. `server/app/services/reviewers.py` — `run_pipeline`, `PipelineResult`, os 3 revisores,
   os 3 prompts, o schema de findings, o gate, a transição.
3. `server/app/routers/reviews.py` — `POST /api/reviews`, `GET /api/reviews?demand=`.
4. `server/tests/test_pipeline.py` e `server/tests/test_doubts.py` — §9.

## 8. Critérios de aceitação

- [ ] O linter roda **primeiro** e nenhum LLM é chamado quando ele acha `error`.
- [ ] Os 3 revisores rodam **na ordem** Blind → Edge → Acceptance, sequencialmente
      (registrado em `events.pipeline_stage`).
- [ ] Todo achado tem a forma `{"severity","title","detail","ac","suggestion"}`.
- [ ] Achado `blocking` vira linha em `doubts` com `status='pending'`; `suggestion` e
      `deferred` viram `deferred`.
- [ ] `warning` do linter vira dúvida `deferred` com `source='linter'`.
- [ ] `verdict="clean"` só com 0 achados; `suggestions` com achados não-bloqueantes;
      `blocking` com erro de linter ou achado `blocking`; `pending` com LLM fora.
- [ ] Falha de LLM: `verdict="pending"`, `llm_available=False`, **nenhuma** dúvida criada
      pela etapa que falhou, artefato **não** promovido, e nenhum bloqueio de push.
- [ ] Os 3 artefatos de revisor são publicados em `events` com path
      `docs/implementation-artifacts/review-<tema>-<revisor>.md`.
- [ ] O arquivo de dúvidas é publicado em `events` (`doubts_file_rendered`) no formato
      canônico v1 — **idêntico** ao que o F5 gera.
- [ ] O catálogo `duvidas-spec.md` só lista artefatos com pendência aberta.
- [ ] Artefato com dúvida `pending` **não** vai para `approved`; com todas `cleaned` e
      linter limpo e 3 revisores rodados, **vai** (`on agents review → approved`), via
      `lifecycle.apply_artifact_transition`.
- [ ] `POST /api/reviews` grava a review, garante a linha em `commits` e transiciona
      `in_progress → review`; com `verdict="blocking"`, transiciona `review → in_progress`.
- [ ] `GET /api/reviews?demand=` devolve as reviews da demanda, mais recente primeiro.
- [ ] `pytest server/tests` verde.

## 9. Testes

`server/tests/test_pipeline.py` (fake do cliente Anthropic, sem chamada real):

| Teste | Verifica |
| --- | --- |
| `test_linter_error_stops_pipeline_before_llm` | 0 chamadas ao fake, `verdict="blocking"` |
| `test_linter_warning_becomes_deferred_doubt` | `doubts.status='deferred'`, `source='linter'` |
| `test_reviewer_order_is_fixed` | ordem Blind → Edge → Acceptance nos eventos |
| `test_reviewer_output_schema_rejected_when_invalid` | payload fora do schema → LLM indisponível |
| `test_findings_have_contract_shape` | 5 chaves, `severity` no enum, `ac` string |
| `test_blocking_finding_creates_pending_doubt` | `doubts.status='pending'` |
| `test_suggestion_finding_creates_deferred_doubt` | `doubts.status='deferred'` |
| `test_verdict_clean` | nenhum achado → `clean` |
| `test_verdict_suggestions` | achado não-bloqueante → `suggestions` |
| `test_verdict_blocking` | achado `blocking` → `blocking` |
| `test_llm_failure_returns_pending_and_blocks_nothing` | `verdict="pending"`, `llm_available=False`, 0 dúvidas novas, status do artefato inalterado |
| `test_review_artifacts_published_with_convention_paths` | 3 eventos `review_artifact_written` com `review-<tema>-<revisor>.md` |
| `test_doubts_file_published_in_canonical_v1` | conteúdo idêntico ao do F5 (frontmatter + tabela) |
| `test_catalog_lists_only_open_artifacts` | artefato com tudo `cleaned` fora do catálogo |
| `test_approval_blocked_by_open_doubt` | artefato fica em `on agents review` |
| `test_approval_succeeds_when_all_cleaned` | `on agents review → approved` |
| `test_approval_requires_llm_available` | com LLM fora, não promove |

`server/tests/test_doubts.py`:

| Teste | Verifica |
| --- | --- |
| `test_raise_doubt_inserts_pending` | `status='pending'`, `source` válido |
| `test_raise_doubt_rejects_invalid_source` | `source='foo'` → `ValueError` |
| `test_resolve_doubt_sets_cleaned` | `status='cleaned'`, `resolved_at` preenchido |
| `test_resolve_doubt_unknown_id` | 404 |
| `test_render_doubts_file_format` | frontmatter espelhado + tabela + contagem de pendências |
| `test_render_doubts_file_all_cleaned` | "Pendências: 0" |
| `test_render_catalog_only_open` | só artefato com pendência aberta |
| `test_doubts_survive_pipeline_roundtrip` | pipeline → dúvida → resolve → arquivo re-renderizado |

## 10. Fora de escopo

- O hook `pre-push` e o `claude -p` (é o F9); o F6 só **recebe** o resultado em
  `POST /api/reviews`.
- RAG/indexação das revisões (é o F7 — `chunks.source_kind='review'`).
- O painel (é o F10).
- Escrever no repo de dev (é o `pull` do F4, via F8).
- Reimplementar regra de linter (é o F2).
- Reimplementar a máquina de estados (é o F4).

## 11. Referências

- Contrato Comum §2 (dependências entre módulos), §3 (convenções de API), §6 (escopos),
  §7.2 (linter), §7.4 (revisores), §7.5 (dúvidas), §8 (ownership), §8.1 (stub do
  `approve`), §9 (dependências e ondas).
- Design master §7.1 (invariantes), §8 (DDL), §9.1 (ciclo da demanda), §9.2 (ciclo do
  artefato), §11.3 (severidade), §12 (pipeline de aprovação), §13 (hook), §17 (API),
  §19 (erros), §20 (testes).
- META-001 §5/§6 (resolução do contexto), §7 (carregar documentos).
- META-005 (3 revisores, ordem fixa, convenção de arquivos).
- META-006 §3 (catálogos), §5 (sincronização inicial), §6 (mapa de status), §7
  (sincronização de revisão), §8 (approval gate), §9 (regras de arquivo).
- SK-001 §16 (frontmatter da BR), §17 (fluxo de aprovação), SK-002 §10 (14 seções),
  §13 (AC mapping), §15 (frontmatter da SPEC), §16 (fluxo de aprovação).
- F2 §3 (contrato do linter), §4 (11 regras), §5 (universo de links).
- Contrato Comum §7.1 (`can_transition`/`allowed_targets`) e §8.1 (regra do `approve`).
- Design master §9.1/§9.2 (tabelas de transição), §17 (rota de aprovação).
- F5 §5.7 (formato canônico v1 do arquivo de dúvidas), §5.1 (`build_client`,
  `LLMUnavailable`), §5.2 (`resolve_method_context`).
