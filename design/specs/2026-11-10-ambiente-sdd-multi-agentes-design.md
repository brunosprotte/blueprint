# Design — Ambiente SDD Multi-Agentes

| Campo | Valor |
| --- | --- |
| **Data** | 2026-11-10 |
| **Status** | Rascunho para revisão |
| **Owner** | Bruno Cesar Sprotte |
| **Escopo** | Servidor SDD (repo blueprint) + Plugin multi-agente (repos de dev) |

> Placement: `design/specs/` — fora de `docs/` de propósito. META-004 restringe `docs/` às
> categorias oficiais (BR/PRD/SPEC/ES/PAT/LS/TS/TP/RI/META/SK). Este documento descreve
> a ferramenta, não conhecimento de negócio — não pertence ao corpus do método.

---

## 1. Contexto

O método Blueprint (Knowledge Driven Engineering) existe hoje como corpus de conhecimento
markdown + dois helpers Python (`tools/lint.py`, `tools/retrieve.py`). Não há API, não há
ciclo de vida automatizado, não há RAG, não há back-office.

A operação real é manual e depende do agente:

1. Agente descobre requisitos → escreve BR
2. Agente planeja → escreve grafo de SPECs
3. Usuário revisa e aprova
4. Agente roda 3 revisores (META-005) → achados em arquivo de dúvidas
5. Agente implementa
6. Commit → push

Passos 4 e 6 são o gargalo: dependem de o agente lembrar de fazer, no momento certo, com o
contexto certo. Nada garante rastreabilidade entre a necessidade original e o que foi
de fato implementado.

## 2. Objetivo

Um ambiente onde:

- Um **servidor** é a autoridade sobre o método e sobre o ciclo de vida das demandas.
- Um **plugin** instalado num repo de dev dá ao agente acesso determinístico a esse servidor.
- A orquestração acontece em scripts, não na interpretação do agente.
- Toda BR, SPEC, revisão e commit fica indexado, formando uma base de conhecimento
  consultável sobre o que está sendo construído.
- Um linter garante que artefatos nunca saem do padrão (frontmatter, ACs, links).

## 3. Não-objetivos

- Substituir o Claude Code. O plugin é um kit de scripts, hooks e skills.
- Substituir o GitHub ou o provedor de LLM do agente.
- Gerar código. O servidor produz conhecimento (BR/SPEC); código é responsabilidade
  do agente no repo de dev.
- Migrar o Blueprint para outro modelo de workspace. META-004 continua valendo.

## 4. As duas peças

Este projeto tem **dois artefatos independentes**. Confundir os dois é o principal risco
de escopo.

```
┌──────────────────────────────────────────────────────────────────────┐
│ A. SERVIDOR SDD — vive no repo blueprint                            │
│    github.com/brunosprotte/blueprint                                 │
│                                                                      │
│    server/     FastAPI (Python)                                      │
│    db/         Postgres (docker compose)                            │
│    site/       Docusaurus — docs do método + demandas + painel      │
│    skills/     skills de implementação (fonte versionada)           │
│    lint/       linter de artefatos (BR/SPEC) — SÓ artefatos          │
│    tools/      lint.py (código) + retrieve.py — inalterados          │
└──────────────────────────────────────────────────────────────────────┘
                    ▲ HTTP + Bearer token
                    │
┌───────────────────┴──────────────────────────────────────────────────┐
│ B. PLUGIN MULTI-AGENTE — vive no repo de dev (ex: sistema-presenca)  │
│                                                                      │
│    .claude-plugin/plugin.json     manifesto do plugin                │
│    skills/                        skills de implementação (espelho)  │
│    hooks/                         pre-push                           │
│    kit/sdd.py                     CLI stdlib (1 arquivo)             │
│    kit/state.json                 demanda corrente                   │
│                                                                      │
│    (cada repo tem seu próprio lint de código — o do plugin é       │
│     opcional e local; não é o linter do servidor)                   │
└──────────────────────────────────────────────────────────────────────┘
```

**Regra de separação:** o servidor nunca escreve no repo de dev. O plugin nunca escreve no
servidor sem token e sem passar pelas transições de estado que o servidor valida. As duas
fronteiras só conversam por API documentada.

## 5. Decisões de stack

| Tema | Decisão | Alternativa rejeitada | Motivo |
| --- | --- | --- | --- |
| Servidor | Python 3.12+ / FastAPI | Node/Express | `tools/` já é Python stdlib; kit no repo do dev roda sem `npm install` |
| Banco | Postgres 16 (docker compose) + pgvector | SQLite | multi-usuário + concorrência de claim; migra sem reescrita |
| RAG | BM25 (mesmo scoring do `retrieve.py`, sobre Postgres) | Voyage embeddings | Claude API não tem endpoint de embeddings; BM25 já funciona em PT técnico; zero custo |
| Embeddings | nenhum (upgrade path) | modelo local | YAGNI — só entra se o recall medido falhar |
| Auth | GitHub OAuth (web) + API token (kit) | senha própria | zero senha pra gerenciar |
| Back-office | Docusaurus servido pelo FastAPI (same-origin) | GitHub Pages | cookie de sessão sem cross-origin |
| Conexão kit↔servidor | script (`sdd.py`), não MCP | MCP | orquestração determinística: quem decide é o script, não o agente |
| Hook de push | `pre-push` (git hook via `core.hooksPath`) | `post-push` | review é gate: barrar o push antes do commit chegar ao remoto |
| Linter | módulo Python no servidor, exposto por API | reusar `tools/lint.py` | servidor valida artefatos; `tools/lint.py` valida código de repo |

## 6. Decomposição em sub-projetos

O sistema é grande demais para um plano único. Ordem de construção, cada fase com spec e
plano próprios:

| Fase | Sub-projeto | Entrega | Depende de |
| --- | --- | --- | --- |
| **F1** | Core do servidor | FastAPI + Postgres + schema + migrations + auth GitHub OAuth + API token | — |
| **F2** | Linter de artefatos | `server/app/lint/` + regras frontmatter/AC/links/paths + `POST /api/lint` + testes | F1 |
| **F3** | Método servido | `GET /api/method/*` servindo META/SK/ES/PAT + `skills/` + sync de skills | F1 |
| **F4** | Demandas e ciclo de vida | `demands` + `artifacts` + transições + claim atômico + sync | F1, F2 |
| **F5** | Geração de BR/SPEC | SK-001 + SK-002 no servidor via Claude API + grafo de SPECs | F3, F4 |
| **F6** | Aprovação e revisão | pipeline de 3 revisores + linter + arquivo de dúvidas (META-006) | F2, F4, F5 |
| **F7** | RAG | índice BM25 + `GET /api/knowledge` + dossiê | F4, F6 |
| **F8** | Plugin e kit | `plugin/.claude-plugin/` + `kit/sdd.py` + skills + comandos | F3, F4 |
| **F9** | Hook pre-push | review via `claude -p` + gate + report ao servidor | F7, F8 |
| **F10** | Docusaurus | docs do método + demandas + painel de status vivo | F4, F6 |

Cada fase é um ciclo spec → plano → implementação. Este documento cobre a arquitetura
completa. As specs de fase, o contrato comum e a matriz de ownership estão em:

- `design/specs/2026-11-10-contrato-comum.md` — **prevalece** sobre este documento
  em caso de conflito (convenções, contratos de módulo, ownership, correções).
- `design/specs/2026-11-10-fase-F1-core-servidor.md` … `…-F10-docusaurus.md`.

### 6.1 Ondas de paralelismo

As fases são implementadas por agentes diferentes, em paralelo, respeitando a matriz
de ownership do contrato comum (nenhum agente edita arquivo de outro).

| Onda | Fases em paralelo | Pré-requisito |
| --- | --- | --- |
| 0 | F1 | — |
| 1 | F2, F3 | F1 |
| 2 | F4 | F1, F2 |
| 3 | F5, F8 | F3+F4 (F5) / F4 (F8) |
| 4 | F6, F10 | F2+F4+F5 (F6) / F4+F6 (F10) |
| 5 | F7 | F4, F6 |
| 6 | F9 | F7, F8 |

## 7. Arquitetura do servidor

```
blueprint/
├── server/
│   ├── app/
│   │   ├── main.py              FastAPI app, middleware, routers
│   │   ├── config.py            env (pydantic-settings)
│   │   ├── db.py                pool asyncpg, sessão, migrations
│   │   ├── models.py            dataclasses/Pydantic de domínio
│   │   ├── auth.py              OAuth GitHub, sessões, tokens
│   │   ├── routers/
│   │   │   ├── method.py        GET /api/method/*
│   │   │   ├── demands.py       CRUD + transições
│   │   │   ├── claims.py        POST /api/claims
│   │   │   ├── artifacts.py     sync, lint, approve
│   │   │   ├── reviews.py       commits + findings
│   │   │   ├── knowledge.py     busca RAG + dossiês
│   │   │   └── admin.py         painel, eventos, SSE
│   │   ├── services/
│   │   │   ├── lifecycle.py     máquina de estados (tabela de transições)
│   │   │   ├── generator.py     SK-001 / SK-002 via Claude API
│   │   │   ├── reviewers.py     Blind/Edge/Acceptance
│   │   │   ├── indexer.py       chunking + indexação BM25
│   │   │   ├── retriever.py     BM25 rerank
│   │   │   └── doubts.py        META-006
│   │   └── lint/
│   │       ├── rules.py         regras (BR-001, SPEC-001, LINK-001…)
│   │       └── runner.py        runner sobre arquivos + índice
│   ├── migrations/
│   ├── tests/
│   └── pyproject.toml
├── db/
│   └── docker-compose.yml
├── plugin/                      fonte do kit que o dev copia pro repo dele
│   ├── .claude-plugin/plugin.json
│   ├── kit/sdd.py
│   ├── kit/state.json
│   ├── hooks/hooks.json
│   └── skills/
├── site/                        Docusaurus
├── skills/                      skills de implementação (fonte)
├── tools/                       lint.py, retrieve.py (inalterados)
└── docs/                        corpus do método (inalterado)
```

### 7.1 Invariantes

1. O servidor **nunca** clona nem escreve em repo de dev.
2. Toda transição de estado passa por `services/lifecycle.py`. Handler HTTP nunca muda
   status direto.
3. Todo artifact gerado nasce com `doubtsIndex` preenchido e arquivo de dúvidas criado
   (META-006 §5).
4. `docs/` do repo blueprint é **somente leitura** em runtime. O método é versionado no
   git; o servidor lê do disco em startup e reindexa quando o hash muda.

## 8. Modelo de dados

```sql
users      (id uuid pk, github_id bigint uniq, login text, email text,
            avatar_url text, created_at timestamptz)

tokens     (id uuid pk, user_id fk, repo_id fk null,
            token_hash text uniq,   -- sha256 do token
            scopes text[],          -- {demand:claim, artifact:sync, review:write}
            created_at, last_used_at, revoked_at)

repos      (id uuid pk, owner text, name text, default_branch text,
            uniq(owner, name))

demands    (id uuid pk, repo_id fk, module text, title text, body text,
            status text not null default 'open',
            claimed_by uuid fk null, claimed_at timestamptz null,
            created_by uuid fk, created_at, updated_at)
            -- status: open | claimed | in_progress | review | merged | done | blocked

artifacts  (id text pk,             -- 'BR-013', 'SPEC-024'
            demand_id fk null,      -- null = artefato do método (não é de demanda)
            repo_id fk null,
            kind text,              -- br | spec
            module text, feature text,
            path text,              -- docs/BR/turma/presencas.md
            sha text,               -- hash do conteúdo espelhado
            status text,            -- draft|pending|on user review|on agents review|approved|stable
            version text, content text,
            created_at, updated_at)

spec_edges (parent_id text fk artifacts, child_id text fk artifacts,
            type text)             -- depends_on | derives_from | tests

doubts     (id uuid pk, artifact_id fk, question text,
            status text,            -- pending | deferred | cleaned
            source text,            -- reviewer | linter | user
            raised_at, resolved_at)

commits    (id uuid pk, demand_id fk, repo_id fk, sha text,
            message text, branch text, author text,
            files jsonb, created_at)

reviews    (id uuid pk, commit_id fk, demand_id fk, verdict text,
            -- verdict: clean | suggestions | blocking
            findings jsonb, created_at)

chunks     (id uuid pk, artifact_id fk null, demand_id fk null,
            source_kind text,       -- method | br | spec | commit | review | doubt
            heading text, text text, token_count int,
            tsv tsvector, corpus_id text)
            -- corpus_id = 'method' | 'repo:<uuid>' — BM25 nunca cruza corpus

events     (id bigserial pk, demand_id fk null, artifact_id fk null,
            type text, payload jsonb, actor uuid null, at timestamptz)

sessions   (id text pk, user_id fk, expires_at)   -- cookie de sessão
```

### 8.1 Índices

- `demands(repo_id, status)` — claim por repo
- `artifacts(demand_id, kind)`, `artifacts(repo_id, path)` — sync idempotente
- `commits(demand_id, created_at desc)`, `reviews(demand_id)`
- `chunks` GIN em `tsv`
- `events(demand_id, at desc)`

## 9. Ciclo de vida

### 9.1 Demanda — só no banco

Fila compartilhada entre devs. Estado não cabe em arquivo de repo.

```
open ──claim──> claimed ──start──> in_progress ──report──> review
                    │                                       │
                    │                            findings blocking
                    │                                       │
                    │◀──────────────────────────────────────┘
                    │                          findings ok ───> merged ──> done
                    │
              release (volta pra open)
  qualquer ──> blocked (com motivo em events)
```

Transições válidas, em `services/lifecycle.py`:

| De | Para | Gatilho | Condição |
| --- | --- | --- | --- |
| — | `open` | `POST /api/demands` | body não vazio |
| `open` | `claimed` | `POST /api/claims` | atômico; token tem `demand:claim`; repo bate |
| `claimed` | `in_progress` | `POST /api/demands/{id}/start` | claimed_by == token.user |
| `in_progress` | `review` | `POST /api/reviews` | commit reportada |
| `review` | `in_progress` | `POST /api/reviews` | verdict = `blocking` |
| `review` | `merged` | `POST /api/demands/{id}/merge` | review mais recente = `clean`/`suggestions` |
| `merged` | `done` | `POST /api/demands/{id}/close` | — |
| `claimed` | `open` | `POST /api/demands/{id}/release` | claimed_by == token.user |
| qualquer | `blocked` | `POST /api/demands/{id}/block` | motivo obrigatório |

**Claim atômico.** Duas pessoas clicando ao mesmo tempo não podem pegar a mesma demanda:

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

`FOR UPDATE SKIP LOCKED` resolve a corrida no nível do Postgres — sem lock em
aplicação, sem retry loop, sem estado intermediário. Se a query retorna vazio, não há
demanda disponível (ou já foi pega). `SKIP LOCKED` também permite vários agentes
consumindo a fila em paralelo sem serializar.

### 9.2 Artefato — BR / SPEC

Estados herdados de META-004 §13 e SK-002 §4.

```
draft → pending → on user review → on agents review → approved → stable
```

| De | Para | Gatilho | Condição |
| --- | --- | --- | --- |
| — | `draft` | geração no servidor | arquivo de dúvidas criado e indexado |
| `draft` | `pending` | `sdd.py sync` reporta o arquivo no repo | sha do arquivo casa com o conteúdo gerado + lint estrutural passa |
| `pending` | `on user review` | `POST /api/artifacts/{id}/request-review` | ACs completos, sem dúvida `pending` |
| `on user review` | `on agents review` | `POST /api/artifacts/{id}/approve` | usuário autenticado |
| `on agents review` | `approved` | pipeline de aprovação | 3 revisores rodaram, linter limpo, todas as dúvidas `cleaned` |
| `approved` | `stable` | `POST /api/artifacts/{id}/stabilize` | ≥1 RI passa |

O **status do artefato é a fonte**, e o frontmatter do arquivo no repo é o espelho. Como o
repo é a fonte do conteúdo, cada transição gera uma versão de arquivo que o plugin aplica
via `sdd.py pull`.

Direção dos comandos, sem ambiguidade:

- `sdd.py pull` — **servidor → repo**. Escreve BR/SPEC aprovados, arquivos de dúvidas e
  frontmatter atualizado. É o único que escreve arquivo.
- `sdd.py sync` — **repo → servidor**. Reporta o que está no repo (path, sha, conteúdo)
  para o servidor indexar e reconciliar. Idempotente.

A transição `draft → pending` é detectada no sync: quando o sha reportado casa com o
conteúdo que o servidor gerou, o artefato está de fato no repo e sai de `draft`.

### 9.3 Duas dimensões, sem colisão

- **Demanda**: estado de *trabalho* (quem está fazendo o quê agora).
- **Artefato**: estado de *qualidade* (o documento está maduro?).

Uma demanda `in_progress` pode ter uma SPEC `approved` e outra `on agents review` ao
mesmo tempo — e está correto.

## 10. Fluxo do agente

```
usuário no repo de dev
  │
  ├─ "pega a próxima demanda"
  │    └─ sdd.py claim
  │         └─ POST /api/claims {repo}
  │              ├─ 409 (já claimada / sem demanda) → agente para
  │              └─ 200 → { demand, br, specs[], spec_graph,
  │                           skill_manifest, knowledge_hits }
  │
  ├─ sdd.py skill sync
  │    └─ GET /api/skills/manifest → compara hash local
  │         └─ desatualizado → GET /api/skills/{id} → escreve .claude/skills/
  │
  ├─ sdd.py pull
  │    └─ GET /api/artifacts/pending → escreve docs/BR/, docs/SPEC/,
  │                                  implementation-artifacts/ no repo → commit
  │
  ├─ sdd.py sync
  │    └─ POST /api/artifacts/sync → reporta path+sha+conteúdo → indexa
  │
  ├─ agente implementa contra a SPEC
  │
  └─ git push
       └─ .git/hooks/pre-push
            ├─ sdd.py lint        → estrutural local, instantâneo
            ├─ sdd.py review      → claude -p: diff vs SPEC da demanda
            └─ POST /api/reviews  → commit message + findings + verdict
                 ├─ blocking   → exit 1 → push abortado
                 └─ suggestions → passa, findings registrados
```

O agente **não decide** nada do fluxo. Ele executa scripts que já decidiram. É o que
torna a orquestração determinística.

### 10.1 Comandos do kit

| Comando | Efeito | Erro |
| --- | --- | --- |
| `sdd.py claim` | pega próxima demanda `open` do repo | exit 3 se não houver |
| `sdd.py pull` | aplica no repo (servidor → repo): artefatos aprovados, arquivos de dúvidas, frontmatter atualizado | — |
| `sdd.py sync` | reindexa artefatos locais → servidor (repo → servidor, idempotente) | exit 4 se lint estrutural falhar |
| `sdd.py status` | estado da demanda corrente + timeline de eventos | — |
| `sdd.py skill sync` | alinha `.claude/skills/` com o servidor | — |
| `sdd.py lint [paths]` | linter de artefatos (via API) | exit 1 se violação |
| `sdd.py review` | roda code review da demanda corrente | exit 2 se `blocking` |
| `sdd.py knowledge "<q>"` | busca RAG | — |
| `sdd.py dossier` | necessidade + solução + implementação | — |
| `sdd.py report <sha>` | reporta commit + findings | — |

Códigos de saída são contrato. O hook e o agente decidem por código, não por texto.

## 11. Linter de artefatos

Módulo Python no servidor (`server/lint/`). **Valida apenas artefatos** — não é o
`tools/lint.py` (que valida código de repositório e fica como está).

Exposto por `POST /api/lint` para o kit, e rodado internamente no pipeline de aprovação.
Mesma implementação, dois consumidores.

### 11.1 Regras

| Regra | Verifica | Origem |
| --- | --- | --- |
| `BR-001` | frontmatter completo: `id`, `module`, `feature`, `status`, `createdBy`, `createdFrom`, `version`, `timestamp` | META-004 §8 |
| `BR-002` | `status` ∈ conjunto oficial do ciclo de vida | META-004 §13 |
| `BR-003` | body contém contexto, atores, capacidades, regras, cenários, Acceptance Criteria | SK-001 |
| `BR-004` | ACs com id único e formato `AC-\d{3}`; toda AC referenciada por ≥1 SPEC | SK-002 §13 |
| `SPEC-001` | frontmatter completo + `technologyPack` + `doubtsIndex` | SK-002 §15 |
| `SPEC-002` | body contém as 14 seções obrigatórias | SK-002 §10 |
| `SPEC-003` | `createdFrom` aponta pra BR existente | SK-002 §15 |
| `SPEC-004` | grafo: todo `depends_on` aponta pra SPEC existente; sem ciclo | SK-002 §8 |
| `PATH-001` | path em `docs/BR/<modulo>/` ou `docs/SPEC/<modulo>/`, kebab-case | META-004 §4, §6 |
| `PATH-002` | `doubtsIndex` aponta pra arquivo existente em `docs/implementation-artifacts/` | META-006 §3 |
| `LINK-001` | `[[wiki-links]]`, `createdFrom`, `Blueprint Documents`, `doubtsIndex` — todos resolvem | META-000 §8 |

### 11.2 Universo de links

Sem clone do repo no servidor. O universo vem de:

1. Corpus do método — lido do disco do repo blueprint (META/SK/ES/PAT/LS/TS/TP/RI).
2. Artefatos do repo de dev — indexados via `sdd.py sync` (BR, SPEC, `implementation-artifacts/`).

Uma referência que não existe em nenhum dos dois é link quebrado.

### 11.3 Severidade

| Severidade | Efeito |
| --- | --- |
| `error` | bloqueia `draft → pending` e `on agents review → approved` |
| `warning` | registrado em `doubts` como `deferred`, não bloqueia |

`LINK-001` é `error` sempre. É exatamente o "nunca ter link quebrado" do requisito.

## 12. Pipeline de aprovação

Substitui a instrução em META-005 (que hoje depende do agente lembrar de rodar os
revisores). Virou evento do servidor, disparado pela aprovação do usuário.

```
usuário aprova no painel (OAuth GitHub)
  ↓ POST /api/artifacts/{id}/approve
status: on agents review
  ↓ servidor executa, sequencial e determinístico:
  1. LINTER      (Python, sem LLM)  → violações estruturais
  2. Blind Hunter      (LLM)        → achados
  3. Edge Case Hunter  (LLM)        → achados
  4. Acceptance Auditor(LLM)        → achados
  ↓
achados → tabela doubts (pending) + markdown do arquivo de dúvidas
  ↓
sdd.py pull → agente escreve docs/implementation-artifacts/duvidas-spec/SPEC-XXX.md
           → frontmatter status atualizado → commit
  ↓
agente resolve as dúvidas → sdd.py sync → server marca doubts: cleaned
  ↓
todas cleaned + linter limpo → status: approved
```

Ordem: **linter primeiro**. Artefato com frontmatter quebrado é barrado na hora, sem
gastar token de LLM em documento estruturalmente inválido.

Os três revisores rodam **no servidor**, com o conteúdo do artefato + conhecimento resolvido
por META-001. META-005 §"Regra" exige ordem fixa — rodam sequenciais, nessa ordem.

Cada revisor produz achados estruturados:

```json
{"severity":"blocking","title":"...","detail":"...","ac":"AC-003","suggestion":"..."}
```

Achados viram linhas em `doubts` e no arquivo de dúvidas do artefato, conforme META-006 §7.
O catálogo central `duvidas-spec.md` só lista artefatos com pendências abertas (META-006 §9).

## 13. Hook pre-push

`.git/hooks/pre-push` via `core.hooksPath` — mesmo mecanismo do `tools/install-hooks.sh`
já existente no blueprint. Determinístico, não depende do Claude Code estar vivo.

```
git push
  ↓ pre-push
  1. sdd.py lint      → POST /api/lint sobre o diff + docs tocados (determinístico, sem LLM)
  2. sdd.py review    → claude -p: diff vs SPEC da demanda corrente
  3. POST /api/reviews → commit message + findings + verdict
  ↓
verdict = blocking   → exit 1 → PUSH ABORTADO
verdict = suggestions → passa; findings registrados
verdict = clean       → passa
```

Escape hatch: `git push --no-verify`.

A demanda corrente mora em `kit/state.json`, gravado por `sdd.py claim`. Sem demanda
corrente, o hook roda só o lint e o push passa.

**Report ao servidor**: a mensagem de commit, o diff resumido, o verdict e os findings
vão para `commits` + `reviews`. Isso é o elo que fecha a rastreabilidade — é o mesmo
registro que o RAG consulta depois para responder "como isso foi implementado de fato".

**Reconcile depois do push.** O commit é reportado antes de chegar ao remoto. Se o push
falhar depois, o servidor tem registro de algo que não existe no remoto. Reconciliação:
`POST /api/demands/{id}/reconcile` compara `commits.sha` com o head real da branch
consultando a API do GitHub. Commits ausentes → marcados `orphaned`, somem do dossiê.

## 14. RAG

Corpus = método + artefatos + commits + reviews + dúvidas. Como o servidor é a autoridade,
tudo que ele indexa é conhecimento confiável.

### 14.1 Chunking

Por **seção H2**, que é a unidade de decisão do blueprint (o `retrieve.py` já usa "hinge
sections" como índice). Chunk guarda `heading`, `source_kind`, `artifact_id`, `demand_id`,
`corpus_id`.

### 14.2 Busca

BM25 em duas etapas:

1. **Candidatos** — Postgres FTS: `tsvector` (config `portuguese`) + `plainto_tsquery`,
   ordenado por `ts_rank_cd`, top 200.
2. **Rerank** — BM25 em Python puro (stdlib, ~40 linhas), `k1=1.5`, `b=0.75`, sobre os
   candidatos.

Por que não BM25 em SQL: a receita de BM25 em Postgres exige função customizada com
`unnest` sobre arrays de frequência. Python puro é mais curto, mais fácil de auditar e
testar, e o corpus é pequeno (ordem de 10⁴ chunks). Se o corpus crescer 100×, aí sim a
função em SQL passa a compensar.

**O corpus nunca cruza corpora.** `corpus_id` particiona: `method` vs `repo:<uuid>`. Uma
busca por "autenticação" no repo A não retorna documento do repo B.

### 14.3 Upgrade path

Embeddings entram **só se o recall medido falhar**. Claude API não tem endpoint de
embeddings — as opções são Voyage (pago) ou modelo local. Medir antes de pagar: conjunto
gold de 20 perguntas com resposta esperada, recall@5 medido a cada mudança do indexador.

### 14.4 Dossiê

Endpoint que junta o que tu pediu: necessidade, proposta de solução e implementação real.

```
GET /api/knowledge/dossier/{demand_id}
{
  "necessidade":    { "br": [...], "acs": [...] },
  "proposta":       { "specs": [...], "grafo": [...] },
  "implementacao":  { "commits": [...], "reviews": [...] },
  "desvios":        [ /* AC sem cobertura, findings não tratados */ ]
}
```

`desvios` é a parte que ninguém tinha: AC que a SPEC prometeu e o commit não entregou.

## 15. Back-office e Docusaurus

### 15.1 Docusaurus (site estático)

`site/` no repo do servidor. Docusaurus 3 consome os `.md` do método diretamente — já
têm frontmatter.

- `site/docs/metodo/` → symlink/cópia de `docs/` (BR, SPEC, ES, META, SK…)
- `site/docs/demandas/<id>.md` → gerado pelo servidor: BR + SPECs + commits + reviews
- Build local: `npm --prefix site run build`; output em `site/build`, servido pelo FastAPI

O site é estático. Demandas são geradas no build, não por evento. Rebuild via CI a cada
merge em `main` do repo blueprint.

### 15.2 Painel de status (único componente vivo)

Componente React dentro do Docusaurus que faz polling na API:

- Tabela de demandas: título, módulo, status, dono, última atividade
- Timeline de eventos por demanda (SSE: `GET /api/events/stream`)
- Filtros por status e por repo

Serve ao requisito: "preciso de uma forma visual de acompanhar o que está acontecendo,
mas a orquestração de fato acontece só com os scripts". O painel **mostra**, não **decide**.

Aprovação de artefato acontece no painel: botão → `POST /api/artifacts/{id}/approve` →
dispara o pipeline da seção 12.

### 15.3 Por que same-origin

O FastAPI serve `site/build` em `/`. Cookie de sessão funciona sem CORS, sem SameSite=None,
sem second cookie. GitHub Pages + API separada exigiria `SameSite=None; Secure` e
configuração de CORS — mais uma fonte de bug de sessão, sem ganho.

## 16. Auth

### 16.1 GitHub OAuth (web)

Authorization Code flow. Callback em `/api/auth/github/callback`. Sessão = cookie
`httpOnly`, `SameSite=Lax`, `secure` em produção, assinado (HMAC). Store em `sessions`.

Necessário: GitHub OAuth App com callback URL `https://<host>/api/auth/github/callback`.
Autorização por repo via `repo` scope; permissões finer-grained por repo se necessário.

### 16.2 API token (kit)

Token opaco `sdd_<32 bytes base64url>`. Armazenado apenas como hash SHA-256 no banco.
Criado na UI, escopos por repo, revogável.

```
Authorization: Bearer sdd_...
```

O token é a fronteira de confiança entre o repo de dev e o servidor. O `kit/sdd.py` lê de
`SDD_TOKEN` (env) ou `kit/config.local.json` (gitignored).

### 16.3 Autorização

Toda rota de escrita valida: token válido e não revogado → escopo necessário → repo
permitido → transição de estado legal. Falha em qualquer elo → 403/409 com o motivo.
Erro de auth nunca resulta em estado parcial.

## 17. Superfície de API

### Método
```
GET  /api/method/index                    # lista categorias e docs
GET  /api/method/doc/{doc_id}             # markdown bruto + frontmatter parseado
GET  /api/method/search?q=                # BM25 no corpus do método
GET  /api/skills/manifest                 # {id, version, hash, description}
GET  /api/skills/{skill_id}               # conteúdo
```

### Demandas
```
POST   /api/demands                        # cria demanda open
GET    /api/demands?repo=&status=
GET    /api/demands/{id}
POST   /api/demands/{id}/start
POST   /api/demands/{id}/merge
POST   /api/demands/{id}/close
POST   /api/demands/{id}/block
POST   /api/demands/{id}/release
POST   /api/demands/{id}/reconcile
```

### Claims
```
POST   /api/claims                         # claim atômico
GET    /api/claims/current
```

### Artefatos
```
GET    /api/artifacts?demand=&repo=
GET    /api/artifacts/{id}
POST   /api/artifacts/sync                 # repo→servidor: upsert por (repo, path), idempotente
POST   /api/lint                           # {paths[]|content[]} → violações
POST   /api/artifacts/{id}/request-review
POST   /api/artifacts/{id}/approve         # dispara pipeline de aprovação
POST   /api/artifacts/{id}/stabilize
GET    /api/artifacts/{id}/doubts
```

### Reviews e commits
```
POST   /api/commits                        # {sha, message, branch, files, demand_id}
GET    /api/commits?demand=
POST   /api/reviews                        # {sha, verdict, findings[]}
GET    /api/reviews?demand=
```

### Geração
```
POST   /api/generation/demands/{id}/br         # BR nova para a demanda
POST   /api/generation/artifacts/{id}/specs    # SPECs derivadas de uma BR
```

### Conhecimento
```
GET    /api/knowledge?q=&repo=&top=
GET    /api/knowledge/dossier/{demand_id}
```

### Admin e eventos
```
GET    /api/events?demand=&since=
GET    /api/events/stream                  # SSE
POST   /api/admin/tokens                   # cria API token
DELETE /api/admin/tokens/{id}
```

### Auth
```
GET    /api/auth/github                    # redireciona pro GitHub
GET    /api/auth/github/callback
POST   /api/auth/logout
GET    /api/auth/me
```

## 18. Geração de BR/SPEC

Servidor executa SK-001 (business discovery) e SK-002 (technical planning) via Claude
API.

1. `POST /api/demands` → demanda `open`
2. `services/generator.py` roda SK-001 → BR
3. SK-002 → grafo de SPECs + N SPECs
4. Contexto de cada chamada LLM:
   - corpus do método resolvido por **META-001** (BR→PRD→SPEC→ES→PAT→LS→TS→TP→RI)
   - top-k BM25 do corpus do repo (demandas anteriores) — força reuso, evita duplicar
     conhecimento (META-000 §8, §18)
5. Saída: markdown com frontmatter do SK-002 §15. Retornado ao kit, que **escreve no
   repo** e commita
6. Arquivo de dúvidas criado junto (META-006 §5)

Modelo: `claude-opus-5-5`, `thinking: adaptive`, `effort: high`, streaming (respostas
longas). Chamar `client.messages.stream()` e usar `.get_final_message()`.

Estruturação da saída usa `output_config.format` (structured outputs) para o
frontmatter — parsear markdown livre pra extrair metadata é frágil.

## 19. Erros

| Situação | Comportamento |
| --- | --- |
| Demanda já claimada | 409 + dono atual + `claimed_at`. Agente para. |
| Transição ilegal | 409 + estado atual. Servidor nunca "adivinha". |
| LLM falha gerando BR | demanda volta pra `open`, evento `generation_failed`, erro visível no painel |
| Review falha (LLM indisponível) | commit registrado, `verdict=pending`. Push **não** bloqueia — indisponibilidade externa não trava o time |
| Linter falha | `error` bloqueia aprovação; `warning` vira dúvida `deferred` |
| Token sem escopo | 403 |
| Token de repo diferente | 403 |
| Hook sem token | aviso no stderr, exit 0, não quebra o fluxo |
| Sync com conteúdo divergente | 409 + hash local e do servidor. resolutions explícitas |
| `SKIP LOCKED` sem demanda | 404 com `status=empty` |

**Push só bloqueia por `blocking`.** Falha de infraestrutura (LLM fora, rede fora) não
bloqueia commit — bloqueia decisão do revisor.

## 20. Testes

Pytest, sem framework de mock pesado.

| Teste | Tipo | Verifica |
| --- | --- | --- |
| `test_lifecycle.py` | tabela | toda transição legal passa; toda ilegal → 409 |
| `test_claim.py` | concorrência | N threads disputando 1 demanda → exatamente 1 vence |
| `test_lint.py` | unitário | cada regra BR-001..LINK-001 pega violação real e não pega doc válido |
| `test_links.py` | unitário | link quebrado detectado; link válido aceito |
| `test_bm25.py` | unitário | gold set: chunk conhecido rankeia no topo |
| `test_sync.py` | idempotência | sync 2× → mesmo índice, mesma versão |
| `test_pipeline.py` | integração | aprovação → 3 revisores + linter → dúvidas → `approved` |
| `test_dossier.py` | integração | dossiê com necessidade, proposta, implementação, desvios |

O `test_claim.py` é o mais importante: é a garantia de que duas pessoas não pegam a mesma
demanda.

## 21. Riscos

| Risco | Mitigação |
| --- | --- |
| Servidor vira gargalo (um repo só, sem deploy) | Postgres + FastAPI stateless; roda local hoje, sobe em container depois |
| Link universe incompleto (repo não sincronizou) | `sdd.py sync` é pré-requisito de `claim`; sync broken → claim recusa |
| LLM alucina AC sem cobertura | `BR-004` cruza ACs BR↔SPEC; `desvios` no dossiê |
| Review agent vira "chato" demais e trava o time | só `blocking` bloqueia; `suggestions` passa |
| Agents competitors no mesmo repo | claim atômico com `SKIP LOCKED` |
| RAG degrada com corpus grande | medir recall@5 com gold set antes de otimizar |
| Duas fontes de verdade (repo + DB) divergem | DB é autoritativo para **status**; repo é autoritativo para **conteúdo**. Reconciliador periódico compara hash |

## 22. Referências

| Doc | Uso |
| --- | --- |
| META-000 | hierarquia do conhecimento, regras de proteção |
| META-001 | resolução de conhecimento (usado pelo gerador e pelos revisores) |
| META-003 | máquina de estados de runtime (base do ciclo de vida) |
| META-004 | convenção de workspace (paths, frontmatter, ciclo de artefato) |
| META-005 | 3 revisores obrigatórios (base do pipeline de aprovação) |
| META-006 | sincronização de índice de dúvidas (achados → arquivo) |
| SK-001 | business discovery (geração de BR) |
| SK-002 | technical planning (geração de SPEC + grafo) |
| LS-001 / PAT-001 / ES-00x | padrões e padrões arquiteturais — regras do lint de código |

---

## Apêndice A — Contrato do kit

```
kit/sdd.py <comando> [args]

Comandos: claim, sync, pull, status, skill sync, lint, review, knowledge, dossier, report

Env:
  SDD_URL      https://servidor/api     (obrigatório)
  SDD_TOKEN    sdd_...                  (obrigatório)
  SDD_REPO     owner/name               (padrão: origem git)

Saída: JSON em stdout, sempre. Diagnóstico em stderr.
Exit codes: 0 ok | 1 lint/review bloqueante | 2 erro de uso | 3 sem demanda
            4 sync falhou | 5 auth
```

## Apêndice B — Manifesto do plugin

```json
{
  "name": "sdd-multi-agent",
  "version": "0.1.0",
  "description": "Kit de desenvolvimento Spec-Driven: acesso ao servidor de demandas SDD",
  "hooks": "./hooks/hooks.json",
  "skills": "./skills",
  "mcpServers": {}
}
```

Sem MCP: a conexão é por script, deliberadamente (§5).
