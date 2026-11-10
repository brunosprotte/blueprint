# Fase F2 — Linter de Artefatos

| Campo | Valor |
| --- | --- |
| **Fase** | F2 |
| **Data** | 2026-11-10 |
| **Depende de** | F1 |
| **Bloqueia** | F4, F6 |
| **Onda** | 1 (paralelo com F3) |
| **Contrato** | `design/specs/2026-11-10-contrato-comum.md` §7.2 |

> Reler o **Contrato Comum** §7.2 antes de começar.

## 1. Objetivo

Módulo Python puro que valida **artefatos** (BR/SPEC) contra o padrão do Blueprint:
frontmatter completo, status no ciclo de vida, seções obrigatórias, ACs únicos e
cobertos, paths canônicos, arquivo de dúvidas existente e **zero link quebrado**.

**Não é o `tools/lint.py`.** Aquele valida código de repositório e fica intocado.
Este valida documentos do método.

**Critério de sucesso:** `POST /api/lint` devolve violações corretas para documentos
que violam e nenhuma para documentos válidos; `LINK-001` pega link quebrado.

## 2. Arquivos que esta fase pode criar/editar

```
server/app/lint/__init__.py        (exporta a API pública)
server/app/lint/rules.py
server/app/lint/runner.py
server/app/routers/lint.py
server/tests/test_lint.py
server/tests/test_links.py
```

**Não tocar:** `tools/lint.py`, `server/app/lint/` além dos arquivos acima, qualquer
outro service, `docs/`.

## 3. Contrato (do Contrato Comum §7.2 — repetido aqui para não depender de leitura cruzada)

```python
# server/app/lint/rules.py
@dataclass(frozen=True)
class Finding:
    rule: str; severity: str; message: str
    path: str | None = None; line: int | None = None
    detail: dict = field(default_factory=dict)

@dataclass(frozen=True)
class Rule:
    id: str; severity: str
    check: Callable[["ArtifactDoc"], list[Finding]]

RULES: tuple[Rule, ...]

# server/app/lint/runner.py
@dataclass
class ArtifactDoc:
    path: str; content: str; frontmatter: dict[str, str]; body: str
    kind: str | None; repo_id: str | None = None

class LinkUniverse(Protocol):
    def exists(self, ref: str) -> bool: ...
    def resolve(self, ref: str) -> str | None: ...

def lint_document(doc: ArtifactDoc, universe: LinkUniverse) -> list[Finding]: ...
def lint_batch(docs: list[ArtifactDoc], universe: LinkUniverse) -> list[Finding]: ...
```

Implementações de universo (todas em `runner.py`):

```python
class MethodCorpus:      # índice em memória do repo blueprint (docs/)
    def __init__(self, root: Path): ...
    def exists(self, ref: str) -> bool: ...
    def resolve(self, ref: str) -> str | None: ...

class SyncedArtifacts:   # consulta a tabela `artifacts` no banco (repo de dev já sincronizado)
    def __init__(self, pool): ...

class CompositeUniverse: # method + synced
    def __init__(self, *universes: LinkUniverse): ...
```

## 4. Regras (canônicas — §11.1 do design master)

| Regra | Severidade | Verifica |
| --- | --- | --- |
| `BR-001` | error | frontmatter tem `id, module, feature, type, title, description, status, tags, timestamp, doubtsIndex, version, generatedBy` (template SK-001 §16) |
| `BR-002` | error | `status` ∈ `draft, pending, on user review, on agents review, approved, stable` |
| `BR-003` | error | body contém as seções de SK-001 §14: Objetivo, Contexto, Atores, Capacidades, Regras de Negócio, Restrições, Exceções, Acceptance Criteria, Open Questions (esta última opcional) |
| `BR-004` | error | ACs com id único no formato `AC-\d{3}`; toda AC da BR referenciada por ≥1 SPEC (SPEC-001) |
| `SPEC-001` | error | frontmatter tem `id, module, feature, type, title, description, createdBy, createdFrom, technologyPack, status, tags, timestamp, doubtsIndex, version` (template SK-002 §15) |
| `SPEC-002` | error | body contém as 14 seções de SK-002 §10: Objetivo, Escopo, Responsabilidade, Entradas, Saídas, Fluxo principal, Fluxos alternativos, Validações, Failures, Pré-condições, Pós-condições, Acceptance Criteria atendidos, Dependências, Blueprint Documents necessários |
| `SPEC-003` | error | `createdFrom` aponta pra BR existente |
| `SPEC-004` | error | grafo consistente: todo `depends_on` aponta pra SPEC existente; sem ciclo |
| `PATH-001` | error | path em `docs/BR/<modulo>/` ou `docs/SPEC/<modulo>/`, nome kebab-case |
| `PATH-002` | error | `doubtsIndex` aponta pra arquivo existente em `docs/implementation-artifacts/duvidas-{br,spec}/` |
| `LINK-001` | error | `[[wiki-links]]`, `createdFrom`, `Blueprint Documents`, `doubtsIndex` — todos resolvem |

Severidade: `error` bloqueia `draft → pending` e `on agents review → approved`.
`warning` vira dúvida `deferred`. `LINK-001` é **sempre** `error`.

## 5. Detalhes de implementação

### 5.1 Parsing

- Frontmatter: YAML entre a primeira linha `---` e a próxima `---`. Usar `yaml.safe_load`.
  Sem PyYAML? Adicionar `pyyaml` às deps do servidor (F1) — é o certo aqui.
- Se o arquivo não tem frontmatter → `BR-001`/`SPEC-001` com mensagem "frontmatter ausente".
- `kind` inferido do path: `docs/BR/...` → `br`, `docs/SPEC/...` → `spec`, caso contrário `None`
  (artefato não-BR/SPEC não é validado por BR-*/SPEC-*, só por PATH/LINK).

### 5.2 Seções obrigatórias

Presença por **heading** (`##` ou `#`), casando por normalização: minúsculas, sem
acentos, sem pontuação, espaços colapsados. "Regras de Negócio" e "Regras de negocio"
são a mesma seção. `"Blueprint Documents necessários"` casa com
`"Blueprint Documents necessarios"`.

A ausência gera **um finding por seção faltante**, com `detail={"missing": "<nome canônico>"}`.

### 5.3 ACs

- Regex: `\bAC-\d{3}\b` no body da BR.
- ID duplicado → `BR-004` com `detail={"duplicate": "AC-003"}`.
- Formato inválido (ex.: `AC-3`, `AC-3000`) → `BR-004` com `detail={"malformed": "..."}`.
- Cobertura: cruza ACs da BR com ACs declaradas nas SPECs do mesmo lote.
  SPEC declara ACs em "Acceptance Criteria atendidos" e/ou no frontmatter `acceptanceCriteria`.
  AC sem cobertura → `BR-004` `detail={"uncovered": "AC-003"}`.
- Uma SPEC que cita AC inexistente → `SPEC-002`? Não — é `BR-004` com
  `detail={"unknown_ac": "AC-999", "spec": "SPEC-003"}`.

### 5.4 Grafo (SPEC-004)

- Dependências declaradas no frontmatter `dependsOn: [SPEC-002, ...]` ou na seção
  "Dependências" (parsear linhas `SPEC-XXX`).
- `depends_on` apontando pra SPEC inexistente → finding.
- Ciclo (A→B→A) → finding com `detail={"cycle": ["SPEC-001","SPEC-002"]}`.
- Detecção de ciclo: DFS com pilha de visiting, reporting o ciclo encontrado.

### 5.5 Universo de links

Refs chequeadas por regra:

| Origem | Como extrair |
| --- | --- |
| `[[wiki-links]]` | regex `\[\[([^\]]+)\]\]` no body |
| `createdFrom` | frontmatter, valor `BR-001` |
| `Blueprint Documents` | seção "Blueprint Documents necessários" — linhas `META-000`, `PAT-001`, `LS-002`… |
| `doubtsIndex` | frontmatter, path relativo |
| `technologyPack` | frontmatter, `TP-001` |
| `dependsOn` | frontmatter/lista |

Resolução de referência:
- `BR-001` / `SPEC-001` / `META-000` / `PAT-001` … → busca no universo (corpus do método
  indexa por id de arquivo; artefatos sincronizados por `artifacts.id`).
- `[[Nome de Documento]]` → resolve pelo **título** (frontmatter `title`) ou pelo nome do
  arquivo sem extensão, case-insensitive. Se não achar por título, tenta o `id` do
  frontmatter.
- Path relativo (`docs/implementation-artifacts/duvidas-spec/SPEC-001.md`) → existe no
  universo de arquivos do repo de dev (artifacts sincronizados com `path`).

`MethodCorpus` indexa, para cada `.md` sob `docs/`: o path relativo, o `id` do
frontmatter, o `title` do frontmatter, e o nome do arquivo sem extensão.
`SyncedArtifacts` consulta `artifacts` por `id`, `path` e `title`.

### 5.6 `POST /api/lint`

Request:

```json
{"repo": "owner/name",
 "docs": [{"path": "docs/BR/login/login.md", "content": "---\n...\n---\n..."}]}
```

Response:

```json
{"findings": [{"rule":"BR-001","severity":"error","message":"...","path":"...","line":3,"detail":{}}],
 "summary": {"error": 1, "warning": 0}}
```

- Aceita também `{"paths": [...]}` — aí o servidor lê os arquivos do disco? **Não**:
  o servidor nunca lê repo de dev. `paths` sozinho → 400 com `code: "paths_without_content"`.
  (O `sdd.py lint` do kit manda o conteúdo junto.)
- Escopo: `artifact:sync` ou sessão web.
- Lint é **puro e determinístico**: mesmo input → mesma output, sempre.

## 6. Tarefas

1. `server/app/lint/rules.py` — dataclasses `Finding`, `Rule` + as 11 regras.
2. `server/app/lint/runner.py` — `ArtifactDoc`, universos, `lint_document`, `lint_batch`.
3. `server/app/lint/__init__.py` — exporta `Finding`, `Rule`, `RULES`, `ArtifactDoc`,
   `lint_document`, `lint_batch`, `MethodCorpus`, `SyncedArtifacts`, `CompositeUniverse`.
4. `server/app/routers/lint.py` — `POST /api/lint`.
5. Testes (§7).

## 7. Critérios de aceitação

- [ ] BR válida de exemplo → **zero** findings.
- [ ] SPEC válida de exemplo → **zero** findings.
- [ ] Cada uma das 11 regras pega uma violação real num fixture específico.
- [ ] `[[link-quebrado]]` → `LINK-001` error.
- [ ] `createdFrom: BR-999` inexistente → `LINK-001` + `SPEC-003`.
- [ ] AC `AC-3` malformada → `BR-004`.
- [ ] AC duplicada → `BR-004`.
- [ ] AC sem cobertura em SPEC → `BR-004` com `uncovered`.
- [ ] Grafo com ciclo → `SPEC-004`.
- [ ] `PATH-001` pega `docs/BR/Login/Login.md` (maiúsculas) e `docs/BR/login/login_final.md`
      (underscore).
- [ ] `PATH-002` pega `doubtsIndex` apontando pra arquivo inexistente.
- [ ] `POST /api/lint` devolve `summary` e findings ordenados por (path, rule).
- [ ] Determinismo: dois lint do mesmo input → listas idênticas.
- [ ] `tools/lint.py` **inalterado** (`git diff --stat tools/` vazio).

## 8. Testes

`server/tests/test_lint.py` — um teste por regra (`test_br001_missing_field`, …),
mais `test_valid_br_no_findings`, `test_valid_spec_no_findings`, `test_deterministic`.

`server/tests/test_links.py` — `test_broken_wiki_link`, `test_valid_wiki_link`,
`test_created_from_missing`, `test_doubts_index_missing`, `test_blueprint_doc_missing`,
`test_composite_universe`, `test_method_corpus_indexes_titles`.

Fixtures: `server/tests/fixtures/br_valida.md`, `br_invalida.md`, `spec_valida.md`,
`spec_invalida.md` — criados por esta fase, mantidos versionados (são insumo de F4/F6).

## 9. Fora de escopo

Validação de código (é `tools/lint.py`), aprovação, pipeline de revisores, RAG.
