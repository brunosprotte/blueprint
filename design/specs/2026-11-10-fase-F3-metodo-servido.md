# Fase F3 — Método Servido

| Campo | Valor |
| --- | --- |
| **Fase** | F3 |
| **Data** | 2026-11-10 |
| **Depende de** | F1 (F2 para o `MethodCorpus`, opcional e tardio) |
| **Bloqueia** | F5, F8 |
| **Onda** | 1 (paralelo com F2) |
| **Contrato** | `design/specs/2026-11-10-contrato-comum.md` §7.6 |

> Reler o **Contrato Comum** §7.6 antes de começar. Esta spec define *o que construir*;
> o Contrato Comum define as convenções que prevalecem.

## 1. Objetivo

Servir o **corpus do método** (os `.md` de `docs/` do repo blueprint) e as **skills de
implementação** (diretório `skills/` na raiz do repo blueprint) por API, para que:

- o kit (`sdd.py skill sync`, `sdd.py knowledge`) consume o método versionado no git;
- o gerador (F5) resolva conhecimento por META-001 contra esse corpus;
- o plugin (F8) instale skills com hash verificável.

**Não é reindexar o corpus no Postgres.** F3 entrega busca **provisória** (FTS puro).
F7 sobe para BM25 de duas etapas **sem mudar a forma da resposta** (§3.4).

**Critério de sucesso da fase:** `GET /api/method/index` lista o corpus, `GET
/api/method/doc/META-004` devolve o documento com frontmatter parseado,
`GET /api/method/search?q=workspace` devolve hits com a **mesma forma** de
`GET /api/knowledge`, e `GET /api/skills/manifest` devolve o manifesto com hash.

**Fora de escopo:** embeddings (a Claude API **não tem** endpoint de embeddings — §3.6),
BM25 em Python (F7), chunks de artefatos/dúvidas (F7), aprovação (F6), painel (F10).

## 2. Arquivos que esta fase pode criar/editar

```
server/app/services/method.py
server/app/services/skills.py
server/app/routers/method.py
server/tests/test_method.py
```

**Pode ler, não editar:** `docs/` (somente-leitura em runtime — invariante 4 do design
master), `skills/` (fonte servida), `server/app/lint/` (F2), `server/app/db.py` (F1),
`server/app/config.py` (F1), `server/app/main.py` (F1), `server/app/auth.py` (F1),
`server/app/models.py` (F1), `server/migrations/001_bootstrap.sql` (F1).

**Não tocar:** `tools/`, `docs/`, `skills/`, `server/migrations/` (esta fase **não cria
migration** — as tabelas que F3 usa já vêm de `001_bootstrap.sql`, F1), `plugin/`,
`site/`, qualquer `design/specs/`.

## 3. Contratos a implementar

### 3.1 `server/app/services/method.py`

```python
CATEGORIES: tuple[str, ...] = ("BR", "PRD", "SPEC", "ADR", "ES", "PAT",
                               "LS", "TS", "TP", "RI", "META", "SK")

CATEGORY_TITLES: dict[str, str] = {
    "BR": "Business Rules", "PRD": "Product Requirements",
    "SPEC": "Functional Specifications", "ADR": "Architecture Decision Records",
    "ES": "Engineering Standards", "PAT": "Patterns",
    "LS": "Language Standards", "TS": "Technology Standards",
    "TP": "Technology Packs", "RI": "Reference Implementations",
    "META": "Meta Documents", "SK": "Skills",
}

EXCLUDED_DIRS: tuple[str, ...] = ("implementation-artifacts",)

@dataclass(frozen=True)
class MethodDoc:
    id: str              # "META-004" | "SK-001" | slug do arquivo
    title: str
    category: str        # "META" | "SK" | "ROOT"
    path: str            # repo-relativo, POSIX: "docs/META/META-004_WORKSPACE_CONVENTION.md"
    kind: str            # "meta" | "skill" | "es" | "br" | "spec" | "doc"
    frontmatter: dict[str, str]
    content: str         # arquivo cru, byte-idêntico ao disco (inclui o bloco ---)
    hash: str            # sha256 hex de content

class MethodIndex:
    """Índice de documentos do método. NÃO é o `MethodCorpus` do F2."""
    def __init__(self, root: Path): ...
    @property
    def corpus_hash(self) -> str: ...
    def refresh(self) -> bool: ...            # True se o corpus mudou
    def all(self) -> list[MethodDoc]: ...      # ordenação estável por path
    def get(self, doc_id: str) -> MethodDoc | None: ...
    def by_path(self, path: str) -> MethodDoc | None: ...
    def categories(self) -> list[dict]: ...
```

**Reuso do F2 — sem reimplementar.** O `MethodCorpus` (F2, `app/lint/runner.py`) resolve
`[[wiki-links]]` para o linter; o `MethodIndex` (F3) guarda **metadados + conteúdo +
hash** que só F3 precisa. F3 **compõe** o `MethodCorpus` do F2 — não o copia, não edita
`app/lint/`:

```python
from app.lint.runner import MethodCorpus   # F2

class MethodIndex:
    def __init__(self, root: Path):
        self.root = root
        self.corpus = MethodCorpus(root)    # instância do F2 (existe/resolve)
```

F2 e F3 estão na **mesma onda (1)** e podem ser implementados em paralelo. O import
acima é **tardio** (dentro de `__init__`, com `try/except ImportError`) e o `MethodIndex`
**funciona sozinho** sem o F2: os índices de F3 (id, título, conteúdo, hash, chunks) são
independentes da resolução de links. Se o F2 ainda não existir, `self.corpus = None` e
`exists/resolve` não são usados por F3. Testes que exigem o F2 ficam
`@pytest.mark.skip(reason="F2 pendente")` (Contrato Comum §9).

### 3.2 `server/app/services/skills.py`

```python
@dataclass(frozen=True)
class Skill:
    id: str            # "ponytail" — frontmatter `name`, senão o nome do diretório
    version: str       # frontmatter `version`, senão "0.0.0"
    hash: str          # sha256 hex da árvore da skill (§4.4)
    description: str   # frontmatter `description`, senão ""
    path: str          # repo-relativo: "skills/ponytail/SKILL.md"

class SkillRegistry:
    def __init__(self, root: Path): ...       # root = repo root; skills = root/"skills"
    @property
    def corpus_hash(self) -> str: ...
    def refresh(self) -> bool: ...
    def manifest(self) -> list[Skill]: ...     # ordenado por id
    def get(self, skill_id: str) -> Skill | None: ...
    def files(self, skill_id: str) -> dict[str, str]: ...   # auxiliares, sem SKILL.md
```

### 3.3 `server/app/routers/method.py`

Cinco rotas, prefixo `/api` (registrado por F1 em `main.py`):

| Rota | Escopo | Resumo |
| --- | --- | --- |
| `GET /api/method/index` | público | categorias + documentos |
| `GET /api/method/doc/{doc_id:path}` | público | documento bruto + frontmatter |
| `GET /api/method/search?q=&top=` | público | busca lexical (FTS) |
| `GET /api/skills/manifest` | autenticado | manifesto com hash |
| `GET /api/skills/{skill_id}` | autenticado | conteúdo da skill |

**Autenticação.** `GET /api/method/*` é **leitura pública**: o site publica o mesmo
corpus (`site/docs/metodo/` é cópia de `docs/` — design master §15.1) e o corpus não
contém segredo. `GET /api/skills/*` **exige `require_user`** (F1): as skills de
implementação não são publicadas. Token do kit (`Authorization: Bearer sdd_...`) passa
em ambos; sessão web (`sdd_session`) também.

### 3.4 Contrato de resposta estável da busca

`GET /api/method/search` responde **exatamente** como `GET /api/knowledge`
(Contrato Comum §7.6):

```json
{
  "query": "workspace convention",
  "hits": [
    {
      "heading": "3. Workspace Structure",
      "text": "Todo projeto Blueprint deve utilizar a seguinte estrutura...",
      "score": 0.0918421,
      "source_kind": "method",
      "artifact_id": null,
      "demand_id": null,
      "corpus_id": "method"
    }
  ]
}
```

- `artifact_id` e `demand_id` são **sempre `null`** no corpus do método (chunk de método
  não pertence a artefato nem a demanda).
- `source_kind` = `"method"`.
- `corpus_id` = `"method"` (particiona o corpus — o BM25 nunca cruza corpus,
  design master §14.2).
- `heading` = título da seção H2 do chunk, sem `#`.
- `text` = corpo da seção, truncado em 800 caracteres (mesmo teto do `tools/retrieve.py`).
- `score` = float. **F3: `ts_rank_cd`. F7: BM25 rerank.** A escala muda; a **forma** não.
  O cliente nunca deve comparar score entre F3 e F7.

### 3.5 `GET /api/method/index`

```json
{
  "categories": [
    {"id": "META", "title": "Meta Documents", "path": "docs/META", "count": 8, "official": true}
  ],
  "docs": [
    {
      "id": "META-004",
      "title": "META-004 — Workspace Convention",
      "category": "META",
      "kind": "meta",
      "path": "docs/META/META-004_WORKSPACE_CONVENTION.md",
      "hash": "9f2c…"
    }
  ],
  "corpus_hash": "c41a…",
  "count": 55
}
```

- `categories` = categorias **presentes** no disco, ordenadas por `CATEGORIES` (§3.1),
  depois as não-oficiais em ordem alfabética.
- `official: true` quando o id está em `CATEGORIES` (META-004 §3). Diretório fora da
  lista oficial (ex.: `docs/rules/`) → `official: false`.
- `docs` = todos os documentos do corpus, ordenados por `path`.
- `corpus_hash` = hash do corpus (§4.2) — muda quando qualquer arquivo muda.
- Arquivos na raiz de `docs/` (ex.: `docs/index.md`) → `category: "ROOT"`,
  `kind: "doc"`.

### 3.6 `GET /api/method/doc/{doc_id:path}`

`doc_id` aceita, **nesta ordem de resolução**:

1. **Path repo-relativo** — `docs/META/META-004_WORKSPACE_CONVENTION.md` ou
   `META/META-004_WORKSPACE_CONVENTION.md`.
2. **Path relativo a `docs/`** — `META/META-004_WORKSPACE_CONVENTION.md`.
3. **`id` do frontmatter** — quando o documento declara `id:` no frontmatter.
4. **Prefixo do nome do arquivo** — regex `^([A-Z]{2,4}-\d{3})\b` sobre o stem
   (ex.: `META-004_WORKSPACE_CONVENTION` → `META-004`; `ES-000_ENGINEERING_PRINCIPLES`
   → `ES-000`).
5. **Prefixo do título** — regex `^([A-Z]{2,4}-\d{3})\s+—` sobre o frontmatter `title`
   (ex.: `SK-001 — Business Discovery` → `SK-001`).
6. **Slug do arquivo** — stem sem o prefixo, minúsculo, `_`→`-`
   (ex.: `caveman` → `caveman`; `write-tests` → `write-tests`).
7. **Título normalizado** — minúsculas, sem acento, espaços colapsados.

Resposta **200**:

```json
{
  "id": "META-004",
  "title": "META-004 — Workspace Convention",
  "category": "META",
  "path": "docs/META/META-004_WORKSPACE_CONVENTION.md",
  "frontmatter": {"type": "Meta", "title": "META-004 — Workspace Convention", "…": "…"},
  "content": "---\ntype: Meta\n…\n---\n\n# META-004 — Workspace Convention\n…",
  "hash": "9f2c…"
}
```

- `content` = **arquivo cru**, byte-idêntico ao disco, **incluindo** o bloco de
  frontmatter. `frontmatter` é o parse do YAML (dicionário vazio se o arquivo não tiver).
- `hash` = sha256 hex de `content` em UTF-8.
- `title` = frontmatter `title`; senão o primeiro H1; senão o stem do arquivo.
- `category` = primeiro segmento do path sob `docs/`, em maiúsculas; `"ROOT"` para
  arquivos na raiz de `docs/`.
- `kind` **não** é devolvido aqui (o contrato do payload é exatamente
  `{id, title, category, path, frontmatter, content, hash}`).

**404** — documento inexistente:

```json
{"error": {"code": "not_found", "message": "documento não encontrado: X", "detail": {}}}
```

### 3.7 `GET /api/method/search`

Query: `q` (**obrigatório**, não-vazio após `strip`) e `top` (inteiro, default **50**,
máx. 200).

- `q` ausente ou vazio → **400** `{"error":{"code":"invalid_query","message":"q é obrigatório","detail":{}}}`.
- `top` fora de `[1, 200]` → **400** `code: "invalid_query"`.
- Sem hits → `{"query": "...", "hits": []}` (200). **Nunca 404** — busca sem resultado é
  resultado válido.
- Filtra **sempre** por `corpus_id = 'method'` (nunca cruza corpus).

### 3.8 `GET /api/skills/manifest`

```json
{
  "skills": [
    {
      "id": "ponytail",
      "version": "0.0.0",
      "hash": "b31f…",
      "description": "You are a lazy senior developer…",
      "path": "skills/ponytail/SKILL.md"
    }
  ],
  "corpus_hash": "77d0…",
  "count": 1
}
```

- Uma entrada **por diretório** de `skills/`.
- `id` = frontmatter `name` do `SKILL.md`; se ausente, o nome do diretório.
- `version` = frontmatter `version`; se ausente, `"0.0.0"`.
- `description` = frontmatter `description`; se ausente, `""`.
- `path` = caminho **repo-relativo** do `SKILL.md` (ex.: `skills/ponytail/SKILL.md`).
- `hash` = hash da árvore da skill (§4.4) — muda quando **qualquer** arquivo da skill
  muda.
- `corpus_hash` = hash do diretório `skills/` inteiro.
- O kit (F8) lê `.skills` e compara `hash` com o hash local de `.claude/skills/<id>/`.

### 3.9 `GET /api/skills/{skill_id}`

**200**:

```json
{
  "id": "ponytail",
  "version": "0.0.0",
  "hash": "b31f…",
  "description": "…",
  "path": "skills/ponytail/SKILL.md",
  "content": "---\nname: ponytail\n…\n---\n\n# Ponytail\n…",
  "files": {"README.md": "…"}
}
```

- `content` = conteúdo **bruto** do `SKILL.md` (o kit escreve em `.claude/skills/<id>/`).
- `files` = map `path-relativo-dentro-da-skill → conteúdo bruto` dos arquivos
  auxiliares (tudo menos o `SKILL.md`). O kit escreve cada chave em
  `.claude/skills/<id>/<chave>`.
- **404** — skill inexistente:
  `{"error":{"code":"not_found","message":"skill não encontrada: X","detail":{}}}`.

## 4. Detalhes de implementação

### 4.1 O que é o corpus

- Raiz: `settings.repo_root / "docs"` (F1, `app/config.py`; default = raiz do repo
  blueprint).
- **Somente-leitura em runtime** (invariante 4 do design master). F3 **nunca** escreve em
  `docs/`.
- Quais arquivos entram: todo `.md` sob `docs/`, **exceto**:
  - `docs/implementation-artifacts/**` — rastreadores de dúvidas (META-006 §9), não
    conhecimento do método;
  - arquivos ocultos (`.`-prefixed) e diretórios `.git`.
- `docs/rules/*.md` **entra** no corpus (é conhecimento do método ainda em reorg —
  `docs/index.md` diz "pending reorg"), com `official: false` na categoria.
- Diretórios vazios não geram categoria.

### 4.2 Hash do corpus e reindexação

- **Hash de documento** = `sha256(content.encode("utf-8")).hexdigest()`.
- **Hash do corpus** = sha256 da concatenação, para cada arquivo em ordem alfabética de
  path relativo a `docs/`, de `relpath + "\0" + sha256_hex + "\n"`.
- **Detecção de mudança**: `MethodIndex.refresh()` recalcula o hash do corpus e
  compara com o valor anterior. Cache de leitura por `(path, mtime_ns, size)`: arquivo
  não modificado **não é relido** — mas o hash continua sendo **de conteúdo**, não de mtime.
- **Ciclo**: startup → carga inicial; a cada requisição de `search`/`index` →
  `refresh()` (barato: só relê o que mudou). Mudou → reindexa os chunks (§4.3).
- O corpus **não** é cacheado em disco nem gravado no banco: é reconstruído do git a
  cada boot (invariante 4).

### 4.3 Busca provisória — FTS no Postgres

- Tabela: `chunks` (DDL canônico do design master §8, criada por F1 em
  `001_bootstrap.sql`; índice GIN em `tsv` em §8.1). Colunas usadas por F3:
  `id, source_kind, heading, text, token_count, tsv, corpus_id` —
  `artifact_id`/`demand_id` ficam `NULL`.
- **Escrita**: F3 faz `DELETE FROM chunks WHERE corpus_id = 'method'` e reinsere os
  chunks do corpus quando o hash muda. Como o corpus é **derivado** (read-only do git),
  reindexar é barato e não há estado de usuário a perder.
- **Chunking**: divide por seção **H2** (`^## `) — a unidade de decisão do blueprint
  (design master §14.1). Documento sem nenhum H2 → **um** chunk, `heading` = o H1 (ou o
  título do frontmatter). `text` = corpo da seção, `strip()`, truncado em **800
  caracteres** (mesmo teto do `tools/retrieve.py`).
- `token_count` = contagem de tokens com o mesmo tokenizador do `tools/retrieve.py`:
  `re.compile(r"\w+", re.UNICODE)`, token minúsculo, `len > 1`.
- `tsv` = `to_tsvector('portuguese', heading || ' ' || text)`.
- **Consulta**:

```sql
SELECT heading, text,
       ts_rank_cd(tsv, plainto_tsquery('portuguese', $1)) AS score
  FROM chunks
 WHERE corpus_id = 'method'
   AND tsv @@ plainto_tsquery('portuguese', $1)
 ORDER BY score DESC, heading ASC
 LIMIT $2;
```

- **Sem embeddings.** A Claude API **não tem** endpoint de embeddings (design master §5
  e §14.3). A busca é **lexical**. Embeddings só entram se o recall medido falhar, com
  Voyage (pago) ou modelo local — upgrade path, não escopo de F3.
- **Provisório de propósito**: F3 entrega FTS puro. F7 substitui por BM25 de duas
  etapas (candidatos `ts_rank_cd` top 200 → rerank BM25 em Python, `k1=1.5`, `b=0.75`,
  mesmo scoring do `tools/retrieve.py`) **sem mudar a forma da resposta** (§3.4).
  O cliente (kit, F8) não percebe a troca.

### 4.4 Layout e hash das skills

- Fonte: `settings.repo_root / "skills"`.
- Layout: `skills/<id>/SKILL.md` — mesma forma do que o Claude Code consome em
  `.claude/skills/<id>/SKILL.md` (por isso o kit copia 1:1).
- **Hash da skill** = sha256 da concatenação, para cada arquivo da skill em ordem
  alfabética de path relativo, de `relpath + "\0" + sha256_hex(content) + "\n"`.
  O `SKILL.md` entra junto com os auxiliares. É o mesmo formato do hash do corpus
  (§4.2) — o kit (F8) reimplementa esse cálculo em stdlib.
- `skills/` **inexistente** → `manifest: {"skills": [], "count": 0}`, `corpus_hash` = sha256
  da string vazia. **`GET /api/skills/{id}` → 404.** F3 **não cria** `skills/` (não está
  na matriz de ownership do Contrato Comum §8); o diretório é conteúdo de repo, criado
  fora do código. O serviço tolera a ausência — o servidor sobe com ou sem `skills/`.

### 4.5 Carregamento no startup

- F3 **não edita `main.py`** (ownership do F1). O carregamento acontece por
  `router.add_event_handler("startup", ...)` em `app/routers/method.py`:
  `include_router` propaga o handler para o app.
- **Ordem**: o `@app.on_event("startup")` do F1 (que cria o pool) é registrado antes do
  `include_router` → o pool existe quando o handler de F3 roda. Ainda assim, o handler
  **não falha o boot**: captura exceção, escreve no stderr e segue.
- **Fallback**: `get_method_service()` (dependência FastAPI) garante carga **preguiçosa**
  na primeira requisição, com `asyncio.Lock` para não carregar duas vezes. A carga
  tardia é a autoridade; a eager é apenas otimização.
- O mesmo vale para `SkillRegistry`.

## 5. Tarefas

1. `server/app/services/method.py` — `CATEGORIES`, `CATEGORY_TITLES`, `MethodDoc`,
   `MethodIndex` (carga, refresh por hash, resolução de `doc_id` em 7 passos, categorias),
   chunking por H2, `index_chunks(pool)`, `search(pool, q, top)`.
2. `server/app/services/skills.py` — `Skill`, `SkillRegistry` (descoberta de diretórios,
   frontmatter, hash da árvore, `manifest()`, `files()`).
3. `server/app/routers/method.py` — as 5 rotas + dependências `get_method_service` /
   `get_skill_registry` + handler de startup.
4. `server/tests/test_method.py` — §7.
5. **Não criar migration.** `chunks` já existe em `001_bootstrap.sql` (F1).

## 6. Critérios de aceitação

- [ ] `GET /api/method/index` devolve todas as 12 categorias oficiais presentes em
      `docs/` + `docs/rules` como não-oficial, com `count` correto e `docs` ordenado por
      path.
- [ ] `GET /api/method/doc/META-004` → 200, `frontmatter.type == "Meta"`,
      `content` **igual** ao arquivo do disco (byte a byte), `hash` == sha256 do arquivo.
- [ ] `GET /api/method/doc/docs/META/META-004_WORKSPACE_CONVENTION.md` → o **mesmo**
      documento (path relativo aceito).
- [ ] `GET /api/method/doc/SK-001` → 200 (resolução por prefixo do título).
- [ ] `GET /api/method/doc/nao-existe` → 404 `code: "not_found"`.
- [ ] `GET /api/method/search?q=workspace+convention` → 200, `hits` **não vazio**, e
      **todo** hit tem exatamente as chaves
      `{heading, text, score, source_kind, artifact_id, demand_id, corpus_id}`.
- [ ] `GET /api/method/search?q=` (vazio) → 400 `code: "invalid_query"`.
- [ ] `GET /api/method/search?q=xyzzy-inexistente` → 200 com `hits: []` (não 404).
- [ ] A busca **nunca** devolve chunk de outro corpus (assert `corpus_id == "method"` em
      todo hit).
- [ ] `GET /api/skills/manifest` → 200, cada skill com
      `{id, version, hash, description, path}` e `hash` estável entre duas chamadas.
- [ ] `GET /api/skills/{id}` → 200 com `content` bruto do `SKILL.md`.
- [ ] `GET /api/skills/inexistente` → 404.
- [ ] `GET /api/skills/manifest` **sem** autenticação → 401.
- [ ] Alterar um `.md` de `docs/` muda `corpus_hash` em `GET /api/method/index` e
      reindexa os chunks (o hit novo aparece na busca).
- [ ] `docs/` **inalterado** após a fase (`git diff --stat docs/` vazio).
- [ ] `tools/` **inalterado** (`git diff --stat tools/` vazio).
- [ ] `pytest server/tests` verde.

## 7. Testes (`server/tests/test_method.py`)

| Teste | Verifica |
| --- | --- |
| `test_index_lists_categories` | categorias oficiais presentes, `count` por categoria |
| `test_index_excludes_implementation_artifacts` | nenhum doc de `duvidas-*` no índice |
| `test_index_includes_non_official_category` | `docs/rules` presente com `official: false` |
| `test_corpus_hash_changes_with_content` | alterar arquivo muda `corpus_hash` |
| `test_doc_by_id` | `META-004` → 200, frontmatter parseado, content cru |
| `test_doc_by_relative_path` | path relativo → mesmo documento |
| `test_doc_by_title_prefix` | `SK-001` resolve pelo prefixo do título |
| `test_doc_content_matches_disk` | `content` == bytes do arquivo |
| `test_doc_not_found_404` | 404 `code: "not_found"` |
| `test_search_response_shape` | chaves de cada hit exatamente as do contrato |
| `test_search_hits_are_method_corpus` | todo hit `corpus_id == "method"`, `artifact_id is None` |
| `test_search_empty_query_400` | 400 `code: "invalid_query"` |
| `test_search_no_match_returns_empty` | 200 `hits: []` |
| `test_search_respects_top` | `top=1` devolve 1 hit |
| `test_search_invalid_top_400` | `top=0` → 400 |
| `test_skills_manifest_shape` | cada entrada com as 5 chaves |
| `test_skills_manifest_stable_hash` | 2 chamadas → mesmo hash |
| `test_skill_content_raw` | `content` == arquivo do fixture |
| `test_skill_files_map` | auxiliares em `files`, `SKILL.md` fora do map |
| `test_skill_not_found_404` | 404 |
| `test_skills_manifest_requires_auth` | sem Bearer → 401 |
| `test_method_read_is_public` | sem Bearer → 200 |
| `test_skills_dir_missing_is_empty` | `skills/` ausente → manifest vazio, sem exceção |
| `test_deterministic_search` | 2 buscas iguais → mesmo `hits` (mesmo score) |

Fixtures: `server/tests/fixtures/method/` — cópia mínima de `docs/` (2 META + 1 SK +
1 `rules/`) e `skills/` (1 skill com `SKILL.md` + 1 auxiliar). O teste aponta
`settings.repo_root` para o fixture via `monkeypatch`, **sem** tocar no `docs/` real.

## 8. Referências

- Contrato Comum §2 (regras de dependência), §3 (convenções de API), §5 (env),
  §7.6 (contrato estável de busca), §8 (matriz de ownership), §9 (ondas).
- Design master §4 (as duas peças), §5 (stack: sem embeddings), §7.1 (invariantes),
  §8 (DDL `chunks`), §8.1 (índices), §14.1/§14.2/§14.3 (RAG, chunking, upgrade path),
  §17 (superfície de API).
- META-004 §3 (categorias oficiais), §5 (documentos arquiteturais na raiz da categoria),
  §7 (convenção de arquivo).
- META-006 §9 (catálogos não são conhecimento do método).
- `tools/retrieve.py` — tokenizador, chunking e BM25 de referência (k1=1.5, b=0.75).
- Specs irmãs: `2026-11-10-fase-F1-core-servidor.md` (pool, config, auth),
  `2026-11-10-fase-F2-linter-artefatos.md` (`MethodCorpus`, regras de lint),
  `2026-11-10-fase-F7-*` (BM25 de duas etapas — troca a implementação, não a forma).
