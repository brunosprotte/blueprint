# Fase F9 — Hook pre-push (gate de push)

| Campo | Valor |
| --- | --- |
| **Fase** | F9 |
| **Data** | 2026-11-10 |
| **Depende de** | F7, F8 |
| **Bloqueia** | — |
| **Onda** | 6 |
| **Contrato** | `design/specs/2026-11-10-contrato-comum.md` §7.7, §8, §9 |

> Reler o **Contrato Comum** §7.7 (contrato do kit) e §8 (matriz de ownership) antes de
> começar. Esta fase **consome** `plugin/kit/sdd.py` (F8) e as rotas de F2/F4/F7 —
> **não edita** nenhum desses arquivos.

## 1. Objetivo

Transformar o push em **gate**: antes do commit chegar ao remoto, o hook roda lint
estrutural determinístico e review do diff contra a SPEC da demanda corrente. Veredito
`blocking` aborta o push (exit 1); todo o resto passa.

**Não é post-push.** O commit ainda não existe no remoto quando o hook roda — por isso o
registro no servidor pode precisar de reconciliação depois (`POST /api/demands/{id}/reconcile`,
§13 do design master).

**Critério de sucesso:** um push com achado `blocking` sai com exit 1 e o git aborta; um
push sem token, sem demanda ou com LLM fora sai com exit 0 e o push segue.

## 2. Arquivos que esta fase pode criar/editar

```
plugin/hooks/pre-push
plugin/hooks/install-hooks.sh
plugin/kit/reviewer.py
server/tests/test_hook.py
```

**Pode ler, não editar:** `plugin/kit/sdd.py` (F8), `plugin/hooks/hooks.json` (F8),
`tools/hooks/pre-commit` e `tools/install-hooks.sh` (padrão de referência do blueprint),
`server/app/routers/{lint,commits,reviews,knowledge}.py` (F2/F4/F7).

As rotas `POST /api/commits` e `POST /api/reviews` são da **F4**; `POST /api/lint` é da F2;
`GET /api/knowledge/dossier/{id}` é da F7. Esta fase **apenas consome** esses endpoints —
não toca em nenhum router.

**Não tocar:** `docs/`, `tools/`, `server/app/**`, `site/`, qualquer `design/specs/`.

## 3. Contrato

### 3.1 Fluxo do gate

```
git push <remote> <branch>
  ↓ pre-push  (plugin/hooks/pre-push, sh)
  0. lê stdin: "<local ref> <local sha> <remote ref> <remote sha>" (1 linha por ref)
  1. SEM TOKEN              → aviso no stderr + exit 0            (§19 do design master)
  2. SEM DEMANDA CORRENTE   → roda só o lint; review é pulado      (§13)
  3. sdd.py lint <paths>    → POST /api/lint (determinístico, sem LLM)
       error   → BLOQUEIA (exit 1)
       warning → suggestion, passa
  4. sdd.py report <sha>    → POST /api/commits {sha, message, branch, files, demand_id}
  5. reviewer.py            → diff vs SPEC da demanda corrente (claude -p)
                             POST /api/reviews {sha, verdict, findings[]}
       blocking    → BLOQUEIA (exit 1)
       suggestions → passa, findings registrados
       pending     → passa (LLM indisponível — §19)
       clean       → passa
  ↓
exit 0 (push segue) | exit 1 (push abortado)
```

Regras que valem para todo o fluxo:

- **Só `blocking` bloqueia.** Falha de infraestrutura (LLM fora, rede fora, servidor fora)
  nunca bloqueia o time (§19).
- **O hook é não-interativo.** Não pergunta nada, não abre editor, não espera TTY.
- **Timeout.** A chamada `claude -p` tem timeout de **120 s**; expirou → `verdict=pending`
  e o push passa (§3.3).
- **Escape hatch.** `git push --no-verify` pula o hook (comportamento do próprio git).
- **Idempotência.** Rodar o hook duas vezes não cria dois commits nem dois reviews:
  `POST /api/commits` e `POST /api/reviews` são upsert por `sha` no servidor (F4).

Ordem passo 4 → 5: o commit é registrado **antes** do review porque `reviews.commit_id`
aponta para `commits.id` (§8 do design master). O commit é registrado antes de o push
confirmar — a reconciliação (§13) cobre o caso de push falhado depois.

**Sobre `sdd.py review`:** o passo 5 é executado pelo motor de review, que é o arquivo
`plugin/kit/reviewer.py` — **desta fase** — e não pelo comando `sdd.py review`. Motivo:
`plugin/kit/sdd.py` é do F8 e esta fase não pode editá-lo (Contrato Comum §8); se o hook
dependesse de o F8 ter implementado a delegação, o gate dependeria de um arquivo de outra
fase. O comando `sdd.py review` (F8) **deve** delegar ao mesmo módulo (§3.5), de modo que
o hook e o agente nunca produzam vereditos divergentes.

### 3.2 Contrato de `plugin/hooks/pre-push`

- **Shebang `#!/usr/bin/env sh`** e sintaxe POSIX. O git executa hooks via `sh` mesmo no
  Windows (Git for Windows usa o `sh` do MSYS) → bashisms quebram o hook. O blueprint já
  usa `sh`/bash em `tools/hooks/pre-commit`; o mesmo mecanismo vale aqui.
- **Argumentos:** `$1` = nome do remote, `$2` = URL do remote. Os dois são informativos —
  o hook não conecta no remote.
- **stdin:** uma linha por ref, no formato
  `<local ref> <local sha> <remote ref> <remote sha>`, ex.:
  `refs/heads/feat/x 9f2c1ab... refs/heads/feat/x 4a7d0e1...`.
  O hook **precisa** ler o stdin para saber o que está sendo enviado (sha local e sha
  remoto definem o range do diff). Linha com remote sha `0000000000000000000000000000000000000000`
  = branch nova.
- **CWD:** o git executa o hook com CWD = topo do working tree.

Resolução de caminhos (nesta ordem, primeira que existir vence):

| Recurso | Regra |
| --- | --- |
| raiz do repo | `git rev-parse --show-toplevel` |
| diretório do kit | `SDD_KIT_DIR` → `$REPO_ROOT/kit` → `$REPO_ROOT/plugin/kit` → `$(dirname "$0")/../kit` |
| interpretador Python | `SDD_PYTHON` → `python3` → `python` → `py -3` |
| token | `SDD_TOKEN` → `$KIT_DIR/config.local.json` → nenhum |
| demanda corrente | `$KIT_DIR/state.json` → nenhum |

Se o kit não for encontrado → aviso no stderr + **exit 0** (não quebra o fluxo).

Cálculo do diff (determinístico, sem rede):

1. Ler o stdin e escolher a **ref primária**: a primeira linha cujo sha local ≠ sha remoto.
   Se todas forem iguais → nada a enviar → exit 0.
2. Se o sha remoto ≠ `000…0` → range = `<sha_remoto>..<sha_local>`.
3. Se o sha remoto = `000…0` (branch nova) → base = `git merge-base <sha_local> refs/remotes/<remote>/HEAD`;
   se o merge-base falhar, base = primeiro pai (`<sha_local>^`).
4. `git diff --no-color <base>..<sha_local>` → diff.
   `git diff --no-color --name-only <base>..<sha_local>` → arquivos tocados.

Artefatos enviados ao lint: entre os arquivos tocados, apenas os que casarem com
`docs/BR/` ou `docs/SPEC/` (o linter de F2 valida **só** artefatos BR/SPEC — §4 do F2).
Arquivo deleted → ignorado. Arquivo ilegível → ignorado com aviso no stderr.

Comandos do kit chamados pelo hook (o kit resolve URL/token/env por conta própria —
Contrato Comum §7.7):

```sh
"$PY" "$KIT_DIR/sdd.py" lint "$ARTIFACT_PATH_1" "$ARTIFACT_PATH_2"   # passo 3
"$PY" "$KIT_DIR/sdd.py" report "$SHA"                                  # passo 4
"$PY" "$KIT_DIR/reviewer.py" --demand "$DEMAND_ID" --sha "$SHA" --json # passo 5
```

Interpretação dos exit codes (Contrato Comum §7.7 — "códigos de saída são contrato"):

| Comando | Exit | Interpretação no hook |
| --- | --- | --- |
| `lint` | 0 | lint limpo |
| `lint` | 1 | lint com `error` → **BLOQUEIA** |
| `lint` | 2, 3, 4, 5 | falha operacional → aviso no stderr + **não bloqueia** |
| `report` | 0 | commit registrado |
| `report` | 2, 3, 4, 5 | falha operacional → aviso no stderr + **não bloqueia** |
| `reviewer.py` | 0 | veredito `clean`, `suggestions` ou `pending` → passa |
| `reviewer.py` | 1 | veredito `blocking` → **BLOQUEIA** |
| `reviewer.py` | 2, 3, 4, 5 | falha operacional → aviso no stderr + **não bloqueia** |

O hook decide pelo **exit code**, não por texto (§10.1 do design master). O JSON em stdout
é o que vai para o servidor, não o que decide o push.

Saída do hook (stderr, prefixo `[sdd]`):

```
[sdd] lint: 0 erro, 2 aviso
[sdd] review: blocking — 1 achado bloqueante
[sdd] push abortado (veredito blocking). Use 'git push --no-verify' para ignorar.
```

ou, no caso de passagem:

```
[sdd] lint: 0 erro, 0 aviso
[sdd] review: clean
```

Mensagens de caso degradado (todas exit 0):

```
[sdd] sem token configurado (SDD_TOKEN ou kit/config.local.json) — revisão ignorada.
[sdd] sem demanda corrente (kit/state.json) — só o lint roda.
[sdd] Claude Code indisponível (claude não está no PATH) — revisão ignorada.
[sdd] revisão expirou após 120s — veredito pending, push liberado.
```

### 3.3 Contrato de `plugin/kit/reviewer.py`

Módulo do kit: **stdlib apenas** (Contrato Comum §7.7), JSON em stdout, diagnóstico em
stderr. Sem `pip install`.

API pública (usada por `sdd.py review` do F8 e pelo hook):

```python
def build_prompt(spec_text: str, acs: list[str], diff_text: str) -> str: ...
def parse_findings(raw: str) -> list[dict]: ...
def decide(findings: list[dict]) -> str: ...
def review(demand: dict, sha: str, diff_text: str, spec_text: str, acs: list[str]) -> dict: ...
def main(argv: list[str]) -> int: ...
```

CLI:

```
python3 kit/reviewer.py --demand <demand_id> --sha <sha> [--repo owner/name] [--json]
```

- `--demand` = id da demanda corrente (vem de `kit/state.json`).
- `--sha` = sha local sendo enviado.
- `--json` = imprime o JSON de resultado em stdout (padrão: sempre imprime).
- Exit codes: 0 = ok (`clean`/`suggestions`/`pending`), 1 = `blocking`, 2 = erro de uso,
  3 = sem demanda, 4 = falha de sync, 5 = auth.

**stdout** (uma linha, JSON):

```json
{"verdict":"clean","findings":[],"llm_available":true,"cost_usd":0.0312,"spec_found":true}
```

`verdict` ∈ `clean` | `suggestions` | `blocking` | `pending`.
`findings` = lista no formato do Contrato Comum §7.4:

```json
{"severity":"blocking","title":"...","detail":"...","ac":"AC-003","suggestion":"..."}
```

**Fonte da SPEC** (nesta ordem):

1. `GET /api/knowledge/dossier/{demand_id}` (F7) → `proposta.specs[]` (conteúdo markdown
   das SPECs) e `necessidade.acs[]`.
2. Se o dossiê trouxer só os **ids** das SPECs (sem o conteúdo) → `GET /api/artifacts/{id}`
   (F4) para cada id → campo `content`.
3. Se o servidor não responder ou não houver SPEC → não há o que comparar:
   - servidor fora → `verdict="pending"`, `llm_available=false` → push passa;
   - demanda sem SPEC → **não posta review**, escreve aviso no stderr
     (`[sdd] nenhuma SPEC encontrada para a demanda — review ignorado`) e o push passa.

**Montagem do prompt** (`build_prompt`):

```
Você é o revisor de código de uma demanda Spec-Driven. Compare o DIFF com a SPEC e
devolva SOMENTE achados, em JSON.

Responda exatamente com um array JSON dentro de um bloco cercado por ```json.
Cada achado tem exatamente estas chaves:
  "severity":    "blocking" | "suggestion"
  "title":       string curto (uma linha)
  "detail":      string com o motivo e a referência arquivo:linha
  "ac":          id do Acceptance Criterion violado (ex.: "AC-003") ou null
  "suggestion":  string com a correção sugerida ou null

Regras:
- "blocking" = viola a SPEC, viola um AC, ou quebra build/testes.
- "suggestion" = estilo, nomeação, melhoria — não bloqueia.
- Se não houver achado, devolva um array vazio: []
- Não invente informação que não está no DIFF ou na SPEC.

=== SPEC ===
{spec_text}

=== ACCEPTANCE CRITERIA ===
{acs}

=== DIFF ===
{diff_text}
```

Limites (para não estourar contexto): diff cortado em **120 000 caracteres** ou
**2 000 linhas**, o que vier primeiro; SPEC cortada em **60 000 caracteres**; ACs em
linhas `- <id>: <texto>`. O corte é anotado no prompt (`[diff truncado]`), e o hook
registra um finding `suggestion` com o aviso — o truncamento nunca vira `blocking`.

**Chamada do Claude Code CLI** (comando exato, prompt via **stdin**):

```
claude -p --output-format json --permission-mode dontAsk --no-session-persistence \
  --allowedTools "" --tools "" --max-turns 1 --strict-mcp-config [--model <model>]
```

- Prompt por **stdin** (não como argumento): evita escaping e limite de tamanho de argv.
- `--model` só é acrescentado se `SDD_LLM_MODEL` estiver definido (Contrato Comum §5);
  sem ele, usa o modelo default do CLI.
- `--allowedTools ""` e `--tools ""`: o revisor não tem permissão de executar nada —
  ele só lê o prompt.
- Resposta: JSON com `result` (o texto), `is_error`, `total_cost_usd`. O texto útil é
  `result`; se `is_error` for true → `verdict="pending"`.
- **Windows:** `shutil.which("claude")` resolve para `claude.CMD`. Executar
  `[caminho, ...]` direto falha para `.cmd` → quando o caminho termina em `.cmd`/`.bat`,
  invocar `["cmd", "/c", caminho, ...]`. Como o prompt vai por stdin, não há quoting.
- **Timeout: 120 s** (`subprocess.run(..., timeout=120)`). `TimeoutExpired` →
  `verdict="pending"`, `llm_available=false`, aviso no stderr. O timeout é sobrescrevível
  por `SDD_REVIEW_TIMEOUT` (segundos) para os testes — default 120.
- **`claude` ausente** (`shutil.which` = None) → `verdict="pending"`,
  `llm_available=false`, aviso no stderr. Push passa.

**Parse tolerante** (`parse_findings`), nessa ordem:

1. Se o texto tiver cerca de código ``` (uma linha de abertura com ``` e uma de
   fechamento), extrair o conteúdo entre as cercas.
2. Procurar o primeiro `[` … `]` balanceado e fazer `json.loads` → se der lista de
   objetos, é o resultado.
3. Se falhar, varrer o texto e tentar `json.loads` em cada `{` … `}` individual,
   acumulando os objetos que parsearem → lista de achados.
4. Se nada parsear → `verdict="pending"`, `llm_available=false` (resposta inutilizável
   é falha de LLM, não "clean").
5. Normalização de cada achado: chaves ausentes → `""`; `severity` ausente ou inválido →
   `"suggestion"` (só `blocking` bloqueia, então o default seguro é não bloquear);
   `severity` fora do conjunto → idem; `ac` ausente → `null`; achado que não for `dict` →
   descartado.

**Decisão do veredito** (`decide`):

| Achados | Veredito | Exit | Push |
| --- | --- | --- | --- |
| nenhum | `clean` | 0 | passa |
| só `suggestion` | `suggestions` | 0 | passa |
| algum `blocking` | `blocking` | 1 | **aborta** |
| LLM ausente / expirou / resposta inutilizável / servidor fora | `pending` | 0 | passa |

**Registro no servidor:** depois de decidir, `reviewer.py` faz
`POST /api/reviews` com o corpo

```json
{"sha":"<sha>","verdict":"blocking","findings":[{"severity":"blocking","title":"...","detail":"...","ac":"AC-003","suggestion":"..."}]}
```

Cabeçalhos: `Authorization: Bearer <SDD_TOKEN>` e `Content-Type: application/json`.
Falha no POST (rede, 4xx, 5xx) → aviso no stderr + exit 0: **falha de registro nunca
bloqueia o push** (§19).

### 3.4 Contrato de `plugin/hooks/install-hooks.sh`

Mesma mecânica do `tools/install-hooks.sh` do blueprint (`git config core.hooksPath`),
adaptada para o repo de dev, que é onde o hook roda:

```bash
#!/usr/bin/env bash
# Instala o hook pre-push do kit SDD no repo atual.
# Idempotente. Executar uma vez por clone, de dentro do repo de dev.
set -e
cd "$(git rev-parse --show-toplevel)"

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # <plugin>/hooks  ou  <repo>/.sdd/hooks
DEST=".sdd/hooks"

mkdir -p "$DEST"
cp "$SRC/pre-push" "$DEST/pre-push"
chmod +x "$DEST/pre-push"

git config core.hooksPath "$DEST"

echo "hooks installed: core.hooksPath = $(git config core.hooksPath)"
echo "pre-push will run the SDD gate on every push."
```

Regras:

- `git config` **sem** `--global` → configuração local do repo (`core.hooksPath` é
  **por repo**; um clone não instalado não é afetado).
- Caminho **relativo** (`.sdd/hooks`), como no blueprint (`tools/hooks`) — o git resolve
  caminho relativo de hooks a partir do topo do working tree.
- Idempotente: rodar de novo só sobrescreve o arquivo e reaffirma o config.
- `chmod +x` no `pre-push` — sem bit de execução o git ignora o hook em Unix.
- Como usar (no repo de dev, com o plugin instalado):

  ```sh
  bash /caminho/para/plugin/hooks/install-hooks.sh
  git config core.hooksPath        # → .sdd/hooks
  ```

- Windows: o git for Windows executa hooks via `sh`; o `pre-push` precisa ter shebang
  `#!/usr/bin/env sh` e sintaxe POSIX (§3.2). Alternativa em PowerShell, se o `sh` não
  estiver no PATH:

  ```powershell
  git config core.hooksPath .sdd/hooks
  ```

### 3.5 Contrato com F8 (`plugin/kit/sdd.py`)

`plugin/kit/sdd.py` é do **F8**. Esta fase **consome** e **não edita**. Requisitos que
F9 impõe ao kit (todos derivados do Contrato Comum §7.7 e do §10.1 do design master):

| Comando do kit | Quem usa | Contrato exigido |
| --- | --- | --- |
| `sdd.py lint <paths...>` | hook, passo 3 | envia ao servidor o `{"repo": "...", "docs": [{"path": ..., "content": ...}]}` de cada artefato tocado (o conteúdo é lido do disco pelo kit — F2 §5.6); exit 1 = lint com `error` |
| `sdd.py report <sha>` | hook, passo 4 | faz `POST /api/commits` com `{"sha","message","branch","files","demand_id"}`; `sha`, `message`, `branch` e `files` vêm do git; `demand_id` vem de `kit/state.json` |
| `sdd.py review` | **agente** (não o hook) | **deve delegar a `kit/reviewer.py`** (§3.3), para que hook e agente nunca divirjam; enquanto `reviewer.py` não existir (F9 pendente), `sdd.py review` deve falhar limpo: aviso no stderr + exit 2 — nunca traceback |
| `kit/state.json` | hook |demand corrente (formato lido em §3.6) |
| `kit/config.local.json` | hook | token (formato lido em §3.7) |

O hook **não** depende de `sdd.py review` existir: o motor de review é
`plugin/kit/reviewer.py`, desta fase.

### 3.6 `kit/state.json` lido por esta fase

O arquivo é escrito por `sdd.py claim` (F8). F9 **lê** o formato canônico:

```json
{
  "demand_id": "3f6c1c8e-5a2b-4d9f-9c11-8b7e2f0a4d61",
  "demand": {
    "id": "3f6c1c8e-5a2b-4d9f-9c11-8b7e2f0a4d61",
    "title": "Login com refresh token",
    "module": "auth",
    "status": "in_progress",
    "repo": "owner/name"
  },
  "repo": "owner/name",
  "branch": "feat/login-refresh",
  "updated_at": "2026-11-10T12:00:00Z"
}
```

Leitura tolerante: `demand_id` → senão `demand.id` → senão `id`. Se nenhum existir, ou o
arquivo não parsear como JSON → **sem demanda** (§3.2, passo 2).

### 3.7 Token

Ordem: variável de ambiente `SDD_TOKEN` → `$KIT_DIR/config.local.json` → nenhum.

Formato canônico de `kit/config.local.json` (escrito pelo F8, lido por F9):

```json
{"token": "sdd_...", "url": "http://localhost:8000/api"}
```

Leitura tolerante: `token` → senão `sdd_token`. Sem token → passo 1 (aviso + exit 0).

## 4. Tarefas

1. `plugin/hooks/pre-push` — script sh POSIX: ler stdin, resolver kit/interpretador/token/
   demanda, calcular o diff, chamar `sdd.py lint`, `sdd.py report` e `reviewer.py`,
   decidir o exit code.
2. `plugin/hooks/install-hooks.sh` — copia o hook para `.sdd/hooks` e configura
   `core.hooksPath` (local, relativo, idempotente).
3. `plugin/kit/reviewer.py` — prompt, `claude -p`, parse tolerante, decisão de veredito,
   `POST /api/reviews`, fallback `pending`.
4. `server/tests/test_hook.py` — §6.

## 5. Critérios de aceitação

- [ ] `plugin/hooks/pre-push` roda com `#!/usr/bin/env sh` e **não** usa bashisms.
- [ ] O hook lê o stdin e usa o sha local do stdin no `POST /api/commits` (sha errado
      no registro = bug).
- [ ] Branch nova (sha remoto `000…0`) → diff calculado contra o merge-base, sem erro.
- [ ] Sem `SDD_TOKEN` e sem `kit/config.local.json` → aviso no stderr, **exit 0**.
- [ ] Sem `kit/state.json` → só o lint roda; nenhuma chamada de review; **exit 0**.
- [ ] Lint com `error` → **exit 1** (push abortado) e o erro listado no stderr.
- [ ] Lint só com `warning` → findings registrados, **exit 0**.
- [ ] Review com `severity: "blocking"` → **exit 1** e push abortado.
- [ ] Review com `severity: "suggestion"` → **exit 0** e findings registrados em
      `POST /api/reviews`.
- [ ] Review sem nenhum achado → `verdict=clean`, **exit 0**.
- [ ] `claude` fora do PATH → `verdict=pending`, `verdict` registrado, **exit 0**.
- [ ] `claude` expirando o timeout de 120 s → `verdict=pending`, **exit 0** (teste com
      `SDD_REVIEW_TIMEOUT=1`).
- [ ] Resposta do `claude` com JSON dentro de cerca ``` e sem cerca → os dois casos
      produzem os mesmos achados.
- [ ] Resposta do `claude` sem JSON parseável → `verdict=pending`, **exit 0**.
- [ ] `POST /api/reviews` recebe corpo com `sha`, `verdict` e `findings[]` no formato do
      Contrato Comum §7.4.
- [ ] Falha no `POST /api/reviews` → aviso no stderr, **exit 0**.
- [ ] `install-hooks.sh` deixa `git config core.hooksPath` = `.sdd/hooks` **no repo
      local** (não global) e `pre-push` executável.
- [ ] `install-hooks.sh` roda duas vezes → mesmo resultado (idempotente).
- [ ] Nenhum arquivo fora dos quatro listados na §2 é criado ou alterado.

## 6. Testes (`server/tests/test_hook.py`)

Sem framework de mock pesado (Contrato Comum §1): pytest + `tmp_path` + `subprocess` +
scripts stub.

| Teste | Verifica |
| --- | --- |
| `test_hook_without_token_exits_zero` | sem token → exit 0, stderr contém "token" |
| `test_hook_without_demand_runs_lint_only` | sem `state.json` → o stub de lint foi chamado, review não, exit 0 |
| `test_hook_blocking_verdict_aborts_push` | `claude` stub devolve achado `blocking` → exit 1, stderr cita o achado |
| `test_hook_with_suggestions_passes` | achado `suggestion` → exit 0, `POST /api/reviews` registrado com `verdict=suggestions` |
| `test_hook_llm_unavailable_yields_pending` | `claude` fora do PATH → `verdict=pending` registrado, exit 0 |
| `test_install_hooks_configures_core_hookspath` | `install-hooks.sh` → `git config core.hooksPath` == `.sdd/hooks`, hook executável, config **local** |
| `test_reviewer_parses_json_with_fence` | `parse_findings` com cerca ``` → achados extraídos |
| `test_reviewer_parses_json_without_fence` | `parse_findings` sem cerca → mesmos achados |
| `test_reviewer_missing_claude_returns_pending` | `shutil.which` forçado a None → `verdict=pending`, exit 0 |
| `test_reviewer_timeout_returns_pending` | `claude` stub dorme, `SDD_REVIEW_TIMEOUT=1` → `verdict=pending`, exit 0 |
| `test_hook_reads_refs_from_stdin` | o sha do stdin é o sha registrado em `POST /api/commits` |

Montagem dos testes:

- `tmp_path` com repo git real (`git init`, um commit, `git remote add origin ...`).
- `kit/sdd.py` **stub** que imprime JSON em stdout e registra as chamadas em arquivo
  (`lint` → `{"findings": [], "summary": {"error": 0, "warning": 0}}`; `report` → `{}`).
- `kit/reviewer.py` real (importado do repositório), com `claude` stub no `PATH`:
  script que imprime `{"type":"result","subtype":"success","is_error":false,
  "result":"```json\n[{...}]\n```","total_cost_usd":0.0}`.
- Servidor HTTP stub: `http.server` em porta livre, em thread, gravando os bodies
  recebidos (`POST /api/commits`, `POST /api/reviews`) em arquivo JSONL.
- `SDD_URL` e `SDD_TOKEN` apontando para o stub; `SDD_KIT_DIR` apontando para o `kit`
  temporário.

Testes que dependem de fase não pronta (F7 sem `GET /api/knowledge/dossier/{id}`, F8 sem
`sdd.py review`) ficam `@pytest.mark.skip(reason="F<n> pendente")` — Contrato Comum §9.

## 7. Fora de escopo

- Escrever em `plugin/kit/sdd.py` (F8).
- Alterar `plugin/hooks/hooks.json` (F8) — o hook do plugin é outro mecanismo
  (Claude Code hooks); o gate de push é git.
- Reconciliação pós-push (`POST /api/demands/{id}/reconcile`) — F4.
- Aprovação de artefato e pipeline de revisores do servidor — F6.
- `post-push` / `post-receive` — não existem nesta fase.
- Métricas, dashboard, histórico de push.

## 8. Referências

- Contrato Comum §3 (convenções de API), §5 (env), §6 (auth e escopos), §7.4 (formato do
  achado), §7.7 (contrato do kit), §8 (ownership), §9 (ondas e regra de dependência
  pendente).
- Design master §5 (stack: hook de push), §8 (modelo de dados: `commits`, `reviews`),
  §10.1 (comandos do kit e "códigos de saída são contrato"), §13 (hook pre-push e
  reconcile), §17 (superfície de API), §19 (erros: hook sem token, review falha).
- `design/specs/2026-11-10-fase-F2-linter-artefatos.md` §5.6 (contrato de `POST /api/lint`).
- `design/specs/2026-11-10-fase-F8-plugin-kit.md` (kit, quando existir).
- `tools/hooks/pre-commit` e `tools/install-hooks.sh` (mecanismo de `core.hooksPath`
  já validado no blueprint).
- `docs/META/META-003_RUNTIME_EXECUTION_MODEL.md` §8, §9 (resolução em tempo de
  execução; nunca inventar informação para continuar).
