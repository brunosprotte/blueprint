# Fase F10 — Docusaurus (site estático + painel de status)

| Campo | Valor |
| --- | --- |
| **Fase** | F10 |
| **Data** | 2026-11-10 |
| **Depende de** | F4, F6 |
| **Bloqueia** | — |
| **Onda** | 4 (paralelo com F6) |
| **Contrato** | `design/specs/2026-11-10-contrato-comum.md` §7.4, §8, §9 |

> Reler o **Contrato Comum** §8 (ownership) e §9 (ondas) antes de começar. Esta fase
> só cria/edita **`site/**`**. Ela **não** edita `server/app/routers/*` nem `server/app/main.py`
> — o mount do estático já existe (F1, §3.7).

## 1. Objetivo

Entregar o back-office: um **site estático** Docusaurus servido pelo próprio FastAPI
(same-origin), com duas seções geradas — o **método** (espelho de `docs/` do blueprint) e as
**demandas** (dossiê gerado no build) — e um **painel de status** que é o único componente
vivo do site.

**O site é estático.** Demandas são geradas no **build**, não por evento. Rebuild via CI a
cada merge em `main` (§15.1 do design master).

**Critério de sucesso:** `npm --prefix site run build` termina com exit 0 e gera
`site/build`; o FastAPI serve esse diretório em `/`; o painel lista as demandas, mostra a
timeline de eventos e aprova artefato pelo endpoint do servidor.

## 2. Arquivos que esta fase pode criar/editar

```
site/package.json
site/package-lock.json
site/tsconfig.json
site/docusaurus.config.ts
site/sidebars.ts
site/.gitignore
site/scripts/sync-method.mjs
site/scripts/gen-demandas.mjs
site/src/css/custom.css
site/src/pages/index.tsx
site/src/components/StatusPanel/index.tsx
site/src/components/StatusPanel/StatusTable.tsx
site/src/components/StatusPanel/EventTimeline.tsx
site/src/components/StatusPanel/ApproveButton.tsx
site/src/components/StatusPanel/useDemands.ts
site/src/components/StatusPanel/useEventStream.ts
site/src/components/StatusPanel/styles.module.css
```

**Pode ler, não editar:** `docs/` (read-only, invariante 4), `server/app/routers/*`,
`server/app/main.py`, `package.json` da raiz do repo.

**Não tocar:** `server/**`, `plugin/**`, `tools/**`, `docs/**`, `db/**`, qualquer
`design/specs/`.

Exceção registrada: o workflow de CI que roda o build **não** é criado por esta fase
(está fora de `site/**`). O contrato do CI está na §3.9 para quem implementá-lo.

## 3. Contrato

### 3.1 Estrutura de `site/`

```
site/
├── package.json
├── package-lock.json
├── tsconfig.json
├── docusaurus.config.ts
├── sidebars.ts
├── .gitignore
├── scripts/
│   ├── sync-method.mjs          # docs/ → site/docs/metodo/   (prebuild)
│   └── gen-demandas.mjs         # API   → site/docs/demandas/  (prebuild)
├── src/
│   ├── css/custom.css
│   ├── pages/index.tsx          # home com o StatusPanel
│   └── components/StatusPanel/  # único componente vivo
├── static/                      # assets estáticos
└── docs/                        # GERADO — gitignored
    ├── metodo/…                 # espelho de docs/ do blueprint
    └── demandas/…               # dossiês gerados
```

`site/docs/` é **inteiramente gerado** → `.gitignore` de `site/`:

```
node_modules/
build/
.docusaurus/
docs/
```

### 3.2 `package.json`

```json
{
  "name": "sdd-site",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "sync": "node scripts/sync-method.mjs",
    "gen": "node scripts/gen-demandas.mjs",
    "prebuild": "npm run sync && npm run gen",
    "build": "docusaurus build",
    "prestart": "npm run sync && npm run gen",
    "start": "docusaurus start",
    "serve": "docusaurus serve",
    "clear": "docusaurus clear"
  },
  "dependencies": {
    "@docusaurus/core": "3.10.2",
    "@docusaurus/preset-classic": "3.10.2",
    "@mdx-js/react": "^3.0.0",
    "clsx": "^2.1.1",
    "prism-react-renderer": "^2.4.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  },
  "devDependencies": {
    "@docusaurus/module-type-aliases": "3.10.2",
    "@docusaurus/tsconfig": "3.10.2",
    "@docusaurus/types": "3.10.2",
    "typescript": "~5.6.3"
  },
  "engines": { "node": ">=20.0" }
}
```

Decisões de versão: `@docusaurus/core` e `@docusaurus/preset-classic` fixados em **3.10.2**
(última 3.x estável); React 19 (peer `^18 || ^19` do Docusaurus 3.10); TypeScript 5.6
(`@docusaurus/tsconfig` 3.10 não é validado com TS 7). `npm --prefix site install` grava o
`package-lock.json` versionado.

`tsconfig.json`:

```json
{
  "extends": "@docusaurus/tsconfig",
  "compilerOptions": {
    "baseUrl": "."
  },
  "exclude": [".docusaurus", "build"]
}
```

### 3.3 `docusaurus.config.ts`

```ts
import type { Config } from '@docusaurus/types';
import type * as Preset from '@docusaurus/preset-classic';

const config: Config = {
  title: 'Blueprint SDD',
  tagline: 'Ambiente Spec-Driven de multiagentes',
  url: process.env.SDD_SITE_URL ?? 'http://localhost:8000',
  baseUrl: '/',
  onBrokenLinks: 'throw',
  onBrokenAnchors: 'warn',
  markdown: {
    format: 'detect',
    hooks: { onBrokenMarkdownLinks: 'throw' }
  },
  i18n: {
    defaultLocale: 'pt-BR',
    locales: ['pt-BR']
  },
  presets: [
    [
      'classic',
      {
        docs: {
          path: 'docs',
          routeBasePath: 'docs',
          sidebarPath: './sidebars.ts',
          showLastUpdateTime: false
        },
        blog: false,
        theme: { customCss: './src/css/custom.css' }
      } satisfies Preset.Options
    ]
  ],
  themeConfig: {
    navbar: {
      title: 'Blueprint SDD',
      items: [
        { type: 'docSidebar', sidebarId: 'metodo', position: 'left', label: 'Método' },
        { type: 'docSidebar', sidebarId: 'demandas', position: 'left', label: 'Demandas' }
      ]
    },
    footer: {
      style: 'dark',
      links: [
        {
          title: 'Blueprint',
          items: [
            { label: 'Método', to: '/docs/metodo/' },
            { label: 'Demandas', to: '/docs/demandas/' }
          ]
        }
      ],
      copyright: 'Blueprint — SDD multiagentes'
    }
  }
};

export default config;
```

Regras:

- `baseUrl: '/'` — o site é servido pelo FastAPI na raiz (§15.3).
- `url` = `SDD_SITE_URL` (default `http://localhost:8000`) — usado para canonical/absoluto.
- **`onBrokenLinks: 'throw'`** — link quebrado **derruba o build**. É o que garante que o
  conteúdo gerado não publique rota morta.
- `onBrokenAnchors: 'warn'` — default do Docusaurus 3 (vira `throw` no v4).
- `markdown.format: 'detect'` — arquivos `.md` são parseados como **CommonMark** e `.mdx`
  como MDX. O corpus de `docs/` é markdown arbitrário (contains `{`, `<`, `---` soltos);
  em MDX qualquer `{` vira expressão e o build quebra. CommonMark elimina essa classe de
  falha.
- `markdown.hooks.onBrokenMarkdownLinks: 'throw'` — a chave nova (a antiga
  `onBrokenMarkdownLinks` no topo está deprecada no 3.x e emite aviso).
- `i18n` pt-BR, locale único.
- **Navbar só método + demandas** — sem item de produto, sem preço, sem "docs" genérico do
  template. `blog: false` (o blog do preset não é usado).
- Sem `favicon` (o asset não existe; adicionar depois exige `site/static/img/favicon.ico`
  **e** a chave `favicon`).

### 3.4 `sidebars.ts`

```ts
import type { SidebarsConfig } from '@docusaurus/plugin-content-docs';

const sidebars: SidebarsConfig = {
  metodo: [{ type: 'autogenerated', dirName: 'metodo' }],
  demandas: [{ type: 'autogenerated', dirName: 'demandas' }]
};

export default sidebars;
```

- Ambos os diretórios são **gerados** no prebuild → sempre existem no build.
- As páginas de demanda usam `sidebar: false` no frontmatter → não poluem a barra
  lateral; a página `demandas/indice.md` (sempre gerada) é o único item da sidebar
  `demandas`, o que garante que ela nunca fique vazia.

### 3.5 `scripts/sync-method.mjs` — método

Roda no `prebuild`. Espelha `docs/` do repo blueprint em `site/docs/metodo/`.

- Origem: `SDD_DOCS_DIR` se definido, senão `<repo>/docs` (repo = pai de `site/`).
- Destino: `<site>/docs/metodo/`.
- O destino é **removido** antes de copiar (evita arquivo obsoleto accumulating).
- Copia tudo sob `docs/`, **exceto** `docs/implementation-artifacts/` (rascunho de dúvidas
  de artefato, não é método).
- **`docs/` é somente leitura** (invariante 4): o script **nunca** escreve na origem —
  toda reescrita acontece na cópia.

**Reescrita de links** (necessária porque `onBrokenLinks: 'throw'`):

Para cada link markdown `[texto](alvo)` do arquivo copiado:

| Caso | Ação |
| --- | --- |
| `alvo` é URL absoluta (`http://`, `https://`, `mailto:`) | **manter** — link externo não é verificado pelo Docusaurus |
| `alvo` começa com `/` e o alvo existe na cópia | reescrever para caminho **relativo** ao arquivo copiado (ex.: `](/META/META-000_X.md)` dentro de `metodo/META/index.md` → `](META-000_X.md)`) |
| `alvo` é relativo e o alvo existe na cópia | **manter** |
| `alvo` é relativo/absoluto e o alvo **não** existe na cópia | **neutralizar**: trocar o link por código inline com o texto original — `[texto](alvo)` → `` `texto` ``; quando não há texto (ex.: `](/tables/orders.md)` escrito como link vazio), usar o próprio `alvo` como texto: `` `alvo` `` |

Casos reais do repositório blueprint que motivam a regra (verificados em `docs/`):

| Link em `docs/` | Destino | Ação na cópia |
| --- | --- | --- |
| `](/META/META-000_BLUEPRINT_KNOWLEDGE_MODEL.md)` (44 ocorrências em `docs/index.md`, `docs/ES/index.md`, `docs/META/index.md`, `docs/SK/index.md`, `docs/TP/index.md`, `docs/TS/index.md`) | existe | reescrito para relativo |
| `](/SK/caveman/README.md)`, `](/SK/<skill>/SKILL.md)` | existem | reescrito para relativo |
| `](/tables/orders.md)` (okf-catalog) | não existe | neutralizado |
| `](/path/to/concept.md)` (okf-catalog) | não existe | neutralizado |
| `](/path.md)` | não existe | neutralizado |
| `](path/to/concept-1.md)`, `](path/to/concept-2.md)` (okf-catalog) | não existe | neutralizado |
| `](./other.md)` (okf-catalog) | não existe | neutralizado |
| `](subdir/)` (okf-catalog) | não existe | neutralizado |
| `](../../README.md)` (`docs/SK/caveman/README.md`) | fora de `docs/` | neutralizado |
| `](https://cloud.google.com/...)`, `](https://wiki.acme.internal/...)` | externo | mantido |

**Autoverificação (obrigatória):** no fim, o script percorre a cópia e confere que todo
link interno aponta para um arquivo que existe na cópia. Se algum não resolver → imprime a
lista em stderr e **`exit 1`** (o build falha antes do Docusaurus, com a lista exata).
Isso é o que garante que `onBrokenLinks: 'throw'` nunca seja acionado por conteúdo do
método.

Saída no stdout (resumo, para o log do CI):

```
[sync] 54 arquivos copiados, 51 links reescritos, 9 links neutralizados
```

### 3.6 `scripts/gen-demandas.mjs` — demandas

Roda no `prebuild` (depois do sync). Gera `site/docs/demandas/`.

- Ligado por `SDD_URL` (default `http://localhost:8000/api`). **Sem `SDD_URL` o script sai
  com 0 e não gera nada** (desenvolvimento local sem servidor). Com `SDD_URL` definido e
  servidor fora → **exit 1** (build do CI quebra: o site não pode ser publicado com
  demands desatualizadas).
- Auth: `SDD_TOKEN` (mesmo nome do kit — Contrato Comum §7.7). Se ausente, usa a sessão
  via cookie — o build roda sem servidor local, então token é o caminho normal.
- Destino `<site>/docs/demandas/` é **removido** antes de escrever (nada obsoleto).

Fluxo:

1. `GET /api/demands` → lista de demandas.
   Parse tolerante: `Array.isArray(body) ? body : (body.demands ?? body.items ?? [])`.
2. Para cada demanda: `GET /api/knowledge/dossier/{demand_id}` (F7).
   Dossiê (§14.4 do design master):

   ```json
   {
     "necessidade":   { "br": [...], "acs": [...] },
     "proposta":      { "specs": [...], "grafo": [...] },
     "implementacao": { "commits": [...], "reviews": [...] },
     "desvios":       [ ... ]
   }
   ```

   Entradas de `br`/`specs` podem ser string (markdown) ou objeto. Parse tolerante:
   string → markdown direto; objeto → preferências de campo `content`, `markdown`, `body`,
   `summary` (nesta ordem); metadados `id`, `title`, `path`.
3. Escreve `<site>/docs/demandas/<demand_id>.md`.
4. Escreve `<site>/docs/demandas/indice.md` (índice com link para cada demanda).

**Formato do arquivo de demanda** (`<id>.md`):

```markdown
---
title: "Login com refresh token"
description: "Dossiê da demanda 3f6c1c8e-5a2b-4d9f-9c11-8b7e2f0a4d61"
sidebar: false
tags: [demanda, auth]
---

# Demanda: Login com refresh token

| Campo | Valor |
| --- | --- |
| **ID** | 3f6c1c8e-5a2b-4d9f-9c11-8b7e2f0a4d61 |
| **Módulo** | auth |
| **Status** | in_progress |
| **Dono** | bruno |
| **Repositório** | owner/name |
| **Atualizada em** | 2026-11-10T12:00:00Z |

## Necessidade

### BR

<markdown do BR>

### Acceptance Criteria

- **AC-001** — texto do AC

## Proposta

### SPEC-001 — Login

<markdown da SPEC>

### Grafo

- SPEC-001 → SPEC-002 (depends_on)

## Implementação

### Commits

| sha | mensagem | branch | data |
| --- | --- | --- | --- |
| 9f2c1ab | feat(auth): refresh token | feat/login-refresh | 2026-11-10 |

### Reviews

| sha | veredito | achados |
| --- | --- | --- |
| 9f2c1ab | suggestions | 2 |

## Desvios

- AC-004 sem cobertura na implementação
```

Regras de escrita:

- Sem `id` no frontmatter → o Docusaurus deriva o id do caminho → rota
  **`/docs/demandas/<demand_id>`**.
- `sidebar: false` → a página não entra na sidebar (sidebar só tem o índice).
- `title` e `description` com aspas duplas e escapes de `"` e `\` — o frontmatter é YAML.
- `tags`: `demanda` + o módulo da demanda.
- Escapar `|` em tabelas (substituir por `\|`).
- `indice.md` (sem `sidebar: false`):

  ```markdown
  ---
  title: Demandas
  sidebar_label: Demandas
  sidebar_position: 1
  ---

  # Demandas

  - [Login com refresh token](/docs/demandas/3f6c1c8e-5a2b-4d9f-9c11-8b7e2f0a4d61) — auth — in_progress — 2026-11-10
  ```

  Sem demandas → `# Demandas` + a linha "Nenhuma demanda gerada." (a página existe sempre,
  para a sidebar não ficar vazia).
- O índice é gerado com os **mesmos ids** que os arquivos → `onBrokenLinks: 'throw'` valida
  cada link do índice.

**Autoverificação:** o gerador confere, no fim, que todo link escrito por ele aponta para
um arquivo escrito por ele; se não → stderr + **exit 1**.

### 3.7 `src/components/StatusPanel/` — o único componente vivo

Componentes:

| Arquivo | Responsabilidade |
| --- | --- |
| `index.tsx` | layout do painel: filtros, tabela, timeline |
| `StatusTable.tsx` | tabela de demandas |
| `EventTimeline.tsx` | timeline de eventos da demanda selecionada |
| `ApproveButton.tsx` | botão de aprovação de artefato |
| `useDemands.ts` | carrega e filtra as demandas |
| `useEventStream.ts` | SSE + fallback de polling |
| `styles.module.css` | estilos do painel |

**Dados da tabela** (`GET /api/demands?repo=&status=`, F4):

| Coluna | Origem (tolerante) |
| --- | --- |
| Título | `demand.title` |
| Módulo | `demand.module` |
| Status | `demand.status` |
| Dono | `demand.owner?.login ?? demand.owner ?? demand.claimed_by ?? "—"` |
| Última atividade | `demand.updated_at` |

**Filtros:** por status (lista derivada dos status de `demands` — §8 do design master:
`open, claimed, in_progress, review, merged, done, blocked`) e por repo (derivado da lista
carregada). Filtros são de cliente; a query também aceita `?status=` e `?repo=`.

**Timeline por demanda** — SSE em `GET /api/events/stream`:

- `EventSource('/api/events/stream')` — **URL relativa**: same-origin, o cookie de sessão
  `sdd_session` vai junto sem CORS e sem `SameSite=None` (§15.3).
- Cada evento do servidor tem a forma da tabela `events` (§8): `{id, demand_id,
  artifact_id, type, payload, at}`.
- O painel guarda os **últimos 200** eventos e filtra por `demand_id` === demanda
  selecionada.
- **Fallback de polling:** se o `EventSource` fechar ou der erro → reconectar com
  backoff exponencial (1 s, 2 s, 4 s, 8 s, 16 s, 30 s — teto) **e**, em paralelo, poll
  `GET /api/events?demand=&since=` a cada **30 s**.
- O `id` do evento é o cursor: o painel manda `Last-Event-ID` ao reconectar (o servidor
  emite `id:` incremental, F1).

**Aprovar artefato** (`ApproveButton`):

```
POST /api/artifacts/{id}/approve
```

- Espera: `on agents review` → pipeline da F6 roda no servidor (§12 do design master).
- Respostas tratadas:
  - **200/204** → "pipeline disparado"; o botão fica desabilitado até o próximo evento.
  - **409** → transição ilegal → mostra `error.message` do envelope
    `{"error":{"code","message","detail"}}` (§3 do Contrato Comum).
  - **503** → `{"error":{"code":"pipeline_unavailable"}}` → "LLM indisponível, tente de novo
    depois" (§3: 503 = dependência externa indisponível, **não** é erro do cliente).
  - **401** → "faça login" + link para `/api/auth/github`.
- O botão pede confirmação antes de enviar (é a única ação que muda estado no servidor).

**O painel mostra, não decide** (§15.2 do design master): ele não aprova demanda, não
transiciona status, não escolhe próximo agente. A única escrita é o approve explícito,
disparado por clique humano.

**Home** (`src/pages/index.tsx`): renderiza `<StatusPanel />` dentro do layout padrão do
preset. Sem lógica de dados no SSR — o SSE só roda em `useEffect` (nada de `window` no
escopo de módulo, senão o build estático quebra).

### 3.8 Mesma origem

- O painel chama **sempre URLs relativas** (`/api/demands`, `/api/events/stream`,
  `/api/artifacts/{id}/approve`) → o FastAPI responde na mesma origem que o site.
- **Sem CORS**, sem header `Access-Control-Allow-Origin`, sem cookie cross-origin, sem
  `SameSite=None`. O cookie `sdd_session` (`httpOnly`, `SameSite=Lax`) funciona direto
  (§15.3).
- `fetch` com `credentials: 'same-origin'` (default do browser para fetch) — explícito no
  código para não depender de default.

### 3.9 Build, entrega e CI

```sh
npm --prefix site install          # uma vez; grava package-lock.json
npm --prefix site run build        # prebuild (sync + gen) + docusaurus build → site/build
npm --prefix site run start        # dev server em http://localhost:3000
```

- Saída: `site/build/` (default do Docusaurus).
- O FastAPI monta `site/build` em `/` — **já implementado pela F1** (§3.7 do F1):
  `app.mount("/", StaticFiles(directory=site/build, html=True), name="site")`, só se o
  diretório existir. F10 **não** mexe em `server/app/main.py`.
- `html=True` → `/docs/demandas/<id>` resolve para `site/build/docs/demandas/<id>/index.html`
  (diretório) ou para o arquivo com fallback.

**Contrato do CI** (implementado fora desta fase — o arquivo de workflow está fora de
`site/**`):

1. Na raiz do repo blueprint, a cada merge em `main`: `npm --prefix site ci` (ou
   `npm --prefix site install` + `npm --prefix site run build`).
2. `SDD_URL` e `SDD_TOKEN` definidos → o build gera as demandas.
3. `SDD_SITE_URL` definido → `url` absoluto correto.
4. `site/build/` publicado como estático **pelo próprio FastAPI** (o deploy sobe o app
   com o diretório montado).

## 4. Tarefas

1. `site/package.json` + `package-lock.json` + `tsconfig.json` + `.gitignore`.
2. `site/docusaurus.config.ts` (§3.3) e `site/sidebars.ts` (§3.4).
3. `site/scripts/sync-method.mjs` (§3.5).
4. `site/scripts/gen-demandas.mjs` (§3.6).
5. `site/src/components/StatusPanel/*` (§3.7) + `site/src/pages/index.tsx` +
   `site/src/css/custom.css`.
6. `npm --prefix site install` (grava o lockfile) e `npm --prefix site run build` verde.

## 5. Critérios de aceitação

- [ ] `npm --prefix site run build` termina com **exit 0** e gera `site/build/index.html`.
- [ ] `site/build/` é servido pelo FastAPI em `/` (mount da F1) — sem CORS, sem erro de
      cookie.
- [ ] `site/docs/metodo/` contém o espelho de `docs/` (BR, SPEC, ES, PAT, META, SK, LS,
      TS, TP, RI, `rules/`, `AGENTS.md`, `index.md`) e **não** contém
      `implementation-artifacts/`.
- [ ] `docs/` do repo blueprint **inalterado** após o build (`git status` de `docs/` vazio)
      — invariante 4.
- [ ] Nenhum link interno quebrado na cópia do método (a autoverificação do sync passa).
- [ ] `site/docs/demandas/<id>.md` gerado a partir do dossiê, com as seções Necessidade,
      Proposta, Implementação e Desvios.
- [ ] `site/docs/demandas/indice.md` existe sempre e linka cada demanda gerada.
- [ ] A rota `/docs/demandas/<id>` responde 200 no site construído.
- [ ] `onBrokenLinks: 'throw'` **realmente** derruba o build: um link quebrado em
      `site/docs/demandas/indice.md` faz `npm --prefix site run build` falhar com exit ≠ 0
      (verificação da §6).
- [ ] Painel lista título, módulo, status, dono e última atividade.
- [ ] Filtro por status e por repo funcionam.
- [ ] Timeline mostra os eventos da demanda selecionada, via
      `GET /api/events/stream` (SSE).
- [ ] Quedando o SSE, o painel continua atualizando (poll de 30 s) e reconecta com backoff.
- [ ] Botão de aprovação chama `POST /api/artifacts/{id}/approve` e trata 200/409/503/401.
- [ ] Nenhum arquivo fora de `site/**` criado ou alterado por esta fase.

## 6. Testes e verificação

**Não há suíte front-end obrigatória** (Contrato Comum §1: pytest para o servidor; o front
é estático). O que é obrigatório é a **verificação pelo build**:

1. `npm --prefix site run build` → exit 0.
2. **Prova do `onBrokenLinks: 'throw'`** (procedimento, ~1 min):

   ```sh
   printf -- '---\ntitle: Quebrado\n---\n\n[rota inexistente](/docs/demandas/nao-existe)\n' \
     > site/docs/demandas/_quebrado.md
   npm --prefix site run build     # deve FALHAR (exit != 0) com o erro de link quebrado
   rm site/docs/demandas/_quebrado.md
   npm --prefix site run build     # volta a passar
   ```

3. **Checklist manual do painel** (com o servidor no ar, `SDD_ALLOW_DEV_AUTH=true`):

   - [ ] a tabela carrega as demandas sem erro no console;
   - [ ] o filtro de status reduz a lista;
   - [ ] o filtro de repo idem;
   - [ ] selecionar uma demanda mostra a timeline;
   - [ ] derrubar o servidor derruba o SSE e o poll de 30 s assume;
   - [ ] o approve responde e o painel reflete o resultado;
   - [ ] o painel não escreve nada além do approve.

**Opcional** — `site/src/components/StatusPanel/__tests__/` com `jest` +
`@testing-library/react` (scripts `test` no `package.json`), para testar `useDemands`
(filtros), `useEventStream` (reconexão/backoff) e `ApproveButton` (401/409/503). Requer
adicionar `jest`, `jest-environment-jsdom`, `@testing-library/react`, `@testing-library/jest-dom`
e `@testing-library/user-event` em `devDependencies` **e** o preset `jest-preset-docusaurus`
— só vale se a fase já estiver acima do essential.

## 7. Fora de escopo

- Backend do painel: rotas de demandas, eventos e aprovação são de F1/F4/F6.
- `server/app/main.py` (o mount do estático é da F1).
- Workflow de CI (fora de `site/**`; contrato na §3.9).
- Blog, landing page de produto, i18n de segundo idioma, analytics, comentários.
- Busca no site (o RAG é do servidor, exposto em `GET /api/knowledge`).
- GitHub Pages / deploy separado — o site é servido pelo FastAPI (§15.3).

## 8. Referências

- Contrato Comum §3 (convenções de API e envelope de erro), §5 (env), §6 (auth, escopo
  `artifact:approve`), §7.4 (formato do achado), §8 (ownership), §9 (ondas).
- Design master §8 (tabelas `demands`, `artifacts`, `events`), §12 (pipeline de
  aprovação), §15.1 (Docusaurus estático, espelho do método, demandas geradas no build),
  §15.2 (painel de status: tabela, SSE, filtros, approve — "mostra, não decide"), §15.3
  (same-origin), §17 (superfície de API), §19 (503 = dependência externa indisponível).
- `design/specs/2026-11-10-fase-F1-core-servidor.md` §3.7 (mount de `site/build`).
- `design/specs/2026-11-10-fase-F4-*.md` (demandas, artefatos, approve) e
  `design/specs/2026-11-10-fase-F6-*.md` (pipeline), quando existirem.
- `docs/` do repo blueprint (fonte do espelho; read-only).
- `docs/META/META-003_RUNTIME_EXECUTION_MODEL.md` §8 (resolução em tempo de execução).
