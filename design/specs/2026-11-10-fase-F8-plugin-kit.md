# Fase F8 — Plugin e Kit

| Campo | Valor |
| --- | --- |
| **Fase** | F8 |
| **Data** | 2026-11-10 |
| **Depende de** | F3, F4 |
| **Bloqueia** | F9 |
| **Onda** | 3 (paralelo com F5) |
| **Contrato** | `design/specs/2026-11-10-contrato-comum.md` §7.7, §11 |

> Reler o **Contrato Comum** §7.7 e §11 antes de começar. Esta spec define *o que
> construir*; o contrato e o Apêndice A do design master definem a interface do kit.

## 1. Objetivo

Entregar o **kit** que o agente executa dentro do repo de dev: um CLI Python **stdlib
apenas**, o manifesto do plugin Claude Code, o espelho gerado das skills e o README de
instalação.

O kit não interpreta, não sugere, não decide: ele **executa** o que o servidor
decidiu e **devolve um exit code** (§11 do Contrato Comum). O hook (F9) e o agente
decidem por código, nunca por texto.

**Critério de sucesso da fase:** `python plugin/kit/sdd.py --help` lista os 10 comandos
do contrato; cada comando fala HTTP com `urllib.request`, devolve JSON em stdout e
sai com o código certo; o kit roda num repo de dev sem `pip install` e sem
`npm install`.

## 2. Arquivos que esta fase pode criar/editar

```
plugin/.claude-plugin/plugin.json
plugin/.gitignore
plugin/README.md
plugin/hooks/hooks.json
plugin/kit/sdd.py
plugin/kit/state.json.example
plugin/skills/.gitkeep
plugin/skills/README.md
server/tests/test_kit_contract.py
```

**Não tocar:** `server/app/**` (F1–F7), `server/migrations/**`, `plugin/hooks/pre-push`
e `plugin/hooks/install-hooks.sh` (F9), `plugin/kit/reviewer.py` (F9), `tools/`,
`docs/`.

**Acréscimos explícitos à matriz do Contrato Comum §8** (§8 lista `plugin/**`
com `.claude-plugin/`, `kit/`, `skills/`, `README.md`):

| Arquivo | Por que existe |
| --- | --- |
| `plugin/hooks/hooks.json` | O manifesto (Apêndice B do design master) aponta para `./hooks/hooks.json`. Um manifesto que aponta para arquivo inexistente é manifesto quebrado. F9 é dono de `plugin/hooks/pre-push` e `install-hooks.sh`, **não** do `hooks.json` — o `hooks.json` é a configuração de hooks do Claude Code, não do git. |
| `plugin/.gitignore` | Sem ele, `kit/state.json` e `kit/config.local.json` (que contêm o token) seriam versionados. |
| `plugin/kit/state.json.example` | O `kit/state.json` real é gitignored (§7.7) — um arquivo **exemplo** versionado é a única forma de entregar o formato sem versionar estado. |

## 3. Contrato (Apêndice A do design master + Contrato Comum §7.7/§11)

```
kit/sdd.py <comando> [args]

Comandos: claim, sync, pull, status, skill sync, lint, review, knowledge, dossier, report

Env: SDD_URL (obrigatório) | SDD_TOKEN (obrigatório) | SDD_REPO (default: remote git)

Saída: JSON em stdout, sempre. Diagnóstico em stderr.

Exit codes: 0 ok | 1 lint/review bloqueante | 2 erro de uso | 3 sem demanda
            4 sync falhou | 5 auth
```

Regras que o Contrato Comum acrescenta e que **prevalecem**:

- **stdlib apenas**. Sem `pip install`, sem `npm install`, sem dependência externa —
  nem em runtime, nem em import.
- `SDD_URL` sem barra final.
- Token vem de `SDD_TOKEN` **ou** de `kit/config.local.json`.
- `kit/state.json` guarda a demanda corrente; `kit/config.local.json` guarda o token;
  os dois são gitignored.

### 3.1 Correções ao design master que esta fase aplica

| Onde | Design master diz | F8 faz (o Contrato Comum prevalece) |
| --- | --- | --- |
| §10.1 (tabela de comandos) | `sdd.py review` → "exit 2 se `blocking`" | **exit 1** — o Contrato Comum §7.7 e §11 definem `1` = "lint/review bloqueante". `2` é erro de uso. |
| §10.1 (tabela de comandos) | `sdd.py sync` → "exit 4 se lint estrutural falhar" | exit 4 (o servidor rejeita o sync → o sync falhou). |
| §10 (fluxo) / §4B | `pull` usa `GET /api/artifacts/pending` | Mantido. A rota **não** está na lista do §17 do design master, mas está no fluxo do §10 e é exigida pelo enunciado desta fase; nenhuma outra rota fora do §17 é usada. Se o servidor não tiver essa rota, `pull` responde **exit 4** com diagnóstico explícito (o F4 precisa expor a rota — ver §7). |

## 4. Estrutura do plugin

```
plugin/
├── .claude-plugin/
│   └── plugin.json          # manifesto (Apêndice B)
├── .gitignore               # kit/state.json, kit/config.local.json
├── README.md                # instalação num repo de dev
├── hooks/
│   ├── hooks.json           # hooks do Claude Code (vazio nesta fase)
│   └── pre-push             # F9 — NÃO é desta fase
├── kit/
│   ├── sdd.py               # o CLI (1 arquivo)
│   ├── state.json           # gitignored — criado por `claim`
│   ├── state.json.example   # exemplo versionado
│   └── config.local.json    # gitignored — {"token": "sdd_..."}
└── skills/                  # espelho gerado — ver §6.6
```

### 4.1 `plugin/.claude-plugin/plugin.json`

Conteúdo **exato** (Apêndice B do design master):

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

- `mcpServers` é `{}` — **decisão deliberada** (design master §5): a conexão kit↔servidor
  é por script, não MCP, para que a orquestração seja determinística.
- `version` acompanha a versão do kit; bump em `0.1.0` → `0.1.1` quando o contrato do
  CLI mudar.

### 4.2 `plugin/hooks/hooks.json`

Conteúdo **exato**:

```json
{
  "hooks": {}
}
```

Vazio de propósito: nesta fase não há evento de hook do Claude Code registrado. O gate
de push é o hook **git** `pre-push` (F9), instalado via `core.hooksPath` — não é um
evento de hook do Claude Code e não entra neste arquivo.

### 4.3 `plugin/.gitignore`

```
kit/state.json
kit/config.local.json
```

### 4.4 `plugin/kit/state.json.example`

Conteúdo **exato**:

```json
{
  "demand_id": "3f1c9a2e-5b74-4d68-9a10-7c2e5b8d9f31",
  "repo": "owner/name",
  "spec_ids": ["SPEC-002", "SPEC-003"],
  "br_id": "BR-013",
  "claimed_at": "2026-11-10T12:34:56Z"
}
```

Campos: `demand_id` (id da demanda), `repo` (`owner/name`), `spec_ids` (ids das SPECs
entregues no claim), `br_id` (id da BR, `null` se a demanda ainda não tem BR),
`claimed_at` (ISO 8601 com `Z`).

### 4.5 `plugin/skills/`

Pasta **gerada** — ninguém escreve skill à mão aqui.

- `plugin/skills/.gitkeep` — marcador de pasta vazia (a pasta precisa existir no
  pacote).
- `plugin/skills/README.md` — 3 linhas explicando a proveniência:

```markdown
# Skills (espelho gerado)

Esta pasta é **gerada**. O conteúdo vem do servidor SDD
(`GET /api/skills/manifest` → `GET /api/skills/{skill_id}`) e é reescrito por
`sdd.py skill sync --dest plugin/skills`. Não editar skills à mão aqui.
```

- A cópia que o **Claude Code carrega no repo de dev** é `.claude/skills/`, escrita por
  `sdd.py skill sync` (sem `--dest`) — ver §6.6.

## 5. `plugin/kit/sdd.py` — arquitetura

Um arquivo, stdlib apenas, Python **3.9+** (roda em qualquer repo de dev, não só no
ambiente do servidor).

### 5.1 Imports permitidos (e nada mais)

```python
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
```

Qualquer outro import = reprovação no teste de contrato (§12). `from __future__ import
annotations` é permitido (necessário para anotações `X | None` em 3.9).

### 5.2 Constantes

```python
EXIT_OK         = 0   # ok
EXIT_BLOCKING   = 1   # lint/review bloqueante
EXIT_USAGE      = 2   # erro de uso
EXIT_NO_DEMAND  = 3   # sem demanda
EXIT_SYNC_FAILED = 4  # sync falhou (e falha de operação contra o servidor)
EXIT_AUTH       = 5   # auth
TIMEOUT = 30           # segundos, urllib.request.urlopen
```

### 5.3 Gramática do CLI

```
sdd.py claim
sdd.py sync
sdd.py pull
sdd.py status
sdd.py skill sync [--dest PATH]
sdd.py lint [paths ...]
sdd.py review
sdd.py knowledge "<q>" [--repo owner/name] [--top N]
sdd.py dossier
sdd.py report <sha>
```

Implementação com `argparse`: um `add_subparsers(dest="command", required=True)`; o
comando `skill` é um subparser com o positional `action` (`choices=["sync"]`).
Comando desconhecido → argparse escreve a mensagem em stderr e sai com **2** (o
`parser.error()` já usa 2 — coincide com "erro de uso").

`--help` é a **única** saída em texto: imprime a ajuda do argparse em stdout. Todo
outro comando imprime **JSON em stdout**.

### 5.4 Fluxo de `main()`

```python
def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # 1. URL ausente  -> exit 2 (erro de uso)   [Contrato Comum §11]
    # 2. Token ausente -> exit 5 (auth)
    # 3. despacha para o comando
    ...
```

Ordem das checagens (fixa):

1. `argparse` — argumentos inválidos → 2.
2. `SDD_URL` ausente ou vazio → stderr `SDD_URL ausente` → **exit 2**.
3. Token: `SDD_TOKEN` → senão `kit/config.local.json` (`{"token": "..."}`) → senão
   stderr `SDD_TOKEN ausente` → **exit 5**.
4. Comando.

`SDD_REPO`: `SDD_REPO` (env) → senão `git remote get-url origin` → senão stderr
`repo não identificável` → **exit 2**.

### 5.5 HTTP só com stdlib

```python
def http(method: str, path: str, payload: dict | None = None) -> tuple[int, object]:
    url = SDD_URL.rstrip("/") + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, (json.loads(body) if body else None)
```

Erros:

| Situação | Tratamento |
| --- | --- |
| `urllib.error.HTTPError` | Ler o corpo, tentar `json.loads`. Se não for JSON, usar `{"error": {"code": "http_error", "message": <texto>}}`. Levantar `ServerError(status, body)`. |
| `urllib.error.URLError` (rede/DNS) | Levantar `TransportError` → stderr + exit 4. |
| Timeout | `socket.timeout` cai em `URLError` → exit 4. |
| Corpo que não é JSON em 2xx | `TransportError` → exit 4 (o servidor respondeu algo que o kit não entende). |

Toda resposta do servidor — inclusive de erro — é repassada em **stdout** como JSON:

```json
{"error": {"code": "empty", "message": "não há demanda open para este repo", "detail": {}}}
```

O diagnóstico legível vai para **stderr**. O kit nunca decide por texto: decide por
**status HTTP** e por **exit code**.

### 5.6 Status HTTP → exit code

`ServerError` é mapeado por comando (a tabela é o contrato de comportamento):

| Comando | 401 | 403 | 404 | 409 | 400/422 | 5xx / rede |
| --- | --- | --- | --- | --- | --- | --- |
| `claim` | 5 | 5 | **3** | **3** | 2 | 4 |
| `sync` | 5 | 5 | 4 | **4** | **4** | 4 |
| `pull` | 5 | 5 | 4 | 4 | 2 | 4 |
| `status` | 5 | 5 | 4 | 4 | 2 | 4 |
| `skill sync` | 5 | 5 | 4 | 4 | 2 | 4 |
| `lint` | 5 | 5 | 4 | 4 | 2 | 4 |
| `review` | 5 | 5 | 4 | 4 | 2 | 4 |
| `knowledge` | 5 | 5 | 4 | 4 | 2 | 4 |
| `dossier` | 5 | 5 | **3** | 4 | 2 | 4 |
| `report` | 5 | 5 | 4 | 4 | 2 | 4 |

Justificativas:

- **401/403 → 5 (auth)**: token ausente, inválido, revogado, sem escopo ou de outro
  repo (Contrato Comum §3 e §6).
- **404 → 3 (sem demanda)** em `claim` (o servidor responde `code: "empty"` quando a
  fila está vazia, design master §19) e em `dossier` (a demanda não existe).
- **409 → 3** em `claim` (demanda já claimada / sem demanda — design master §10: o
  agente para) e **409 → 4** em `sync` (conteúdo divergente — design master §19).
- **400/422 → 2** (erro de uso: o kit mandou payload inválido), exceto `sync`, onde
  **422 → 4**: o servidor rejeitou os documentos, o sync não aconteceu.
- **5xx/rede → 4**: a operação não pôde ser concluída. Em `review`, o **503** (LLM
  indisponível) **não** bloqueia (design master §19): o kit registra
  `{"verdict": "pending", "llm_available": false}` e sai com **0**.

### 5.7 Estado e configuração

| Arquivo | Escrito por | Conteúdo |
| --- | --- | --- |
| `kit/state.json` | `claim` | §4.4 |
| `kit/config.local.json` | usuário (manual) | `{"token": "sdd_..."}` |

`state.json` é lido por `pull`, `status`, `dossier`, `review` e `report`.
`config.local.json` é lido só quando `SDD_TOKEN` não está no ambiente.
Ambos são gitignored (§4.3). O token **nunca** é impresso em stdout, stderr ou log.

### 5.8 Descoberta do repo

```python
def resolve_repo() -> str:
    env = os.environ.get("SDD_REPO")
    if env: return env.strip()
    out = subprocess.run(["git", "remote", "get-url", "origin"],
                         capture_output=True, text=True, check=False)
    if out.returncode != 0 or not out.stdout.strip(): raise UsageError(...)
    m = re.search(r"(?P<owner>[^/:]+)/(?P<name>[^/]+?)(?:\.git)?\s*$", out.stdout.strip())
    if not m: raise UsageError(...)
    return f"{m.group('owner')}/{m.group('name')}"
```

O regex `(?P<owner>[^/:]+)/(?P<name>[^/]+?)(?:\.git)?\s*$` pega os **dois últimos
segmentos** do remote, cobrindo `git@github.com:owner/name.git`,
`https://github.com/owner/name.git`, `https://user:token@github.com/owner/name.git` e
`ssh://git@github.com/owner/name`. `owner` não pode conter `/` nem `:` (senão o host
seria confundido com o owner). Falha → exit 2 (erro de uso: sem repo identificável).

### 5.9 SHA-256

```python
hashlib.sha256(content.encode("utf-8")).hexdigest()
```

Usado no `sync` (hash do conteúdo de cada documento local) e no `skill sync`
(comparação com o `hash` do manifesto).

## 6. Comandos

### 6.1 `claim`

`POST /api/claims` — body `{"repo": "owner/name"}`, header `Authorization: Bearer`.

Resposta 200 (design master §10):

```json
{
  "demand": {"id": "3f1c9a2e-5b74-4d68-9a10-7c2e5b8d9f31", "status": "claimed", "claimed_at": "2026-11-10T12:34:56Z", "module": "login", "title": "Login de alunos"},
  "br": {"id": "BR-013", "path": "docs/BR/login/login.md"},
  "specs": [{"id": "SPEC-002", "path": "docs/SPEC/login/login-api.md"}],
  "spec_graph": [{"parent": "SPEC-001", "child": "SPEC-002", "type": "depends_on"}],
  "skill_manifest": [{"id": "business-discovery", "version": "1.0.0", "hash": "3f1c…"}],
  "knowledge_hits": []
}
```

Comportamento:

1. Monta o corpo `{"repo": resolve_repo()}`.
2. 200 → grava `kit/state.json`:
   - `demand_id` = `demand.id`
   - `repo` = o repo pedido
   - `spec_ids` = `[s["id"] for s in specs]`
   - `br_id` = `br["id"]` ou `null`
   - `claimed_at` = `demand.claimed_at` (ISO 8601) ou, se ausente, `now` local em UTC
     com sufixo `Z`
3. Imprime **a resposta do servidor verbatim** em stdout.
4. 404 (`code: "empty"`) ou 409 → stderr `sem demanda open para este repo` → **exit 3**.

`claim` escreve `kit/state.json` — isso **não** viola "pull é o único que escreve
arquivo": o estado do kit não é artefato de repo (§8).

### 6.2 `sync` (repo → servidor)

1. Varre, no repositório atual, `docs/BR/**/*.md`, `docs/SPEC/**/*.md`,
   `docs/implementation-artifacts/**/*.md`.
2. Para cada arquivo: `content` = texto UTF-8 do arquivo; `sha256` = hash do conteúdo.
3. `POST /api/artifacts/sync` — body:

```json
{
  "repo": "owner/name",
  "docs": [
    {"path": "docs/BR/login/login.md", "content": "---\nid: BR-013\n…\n---\n# Login\n…"}
  ]
}
```

O payload tem **exatamente** `repo` e `docs[{path, content}]` — o hash é cálculo local
(auditoria e diagnóstico), não campo do payload.

4. Resposta 200 → stdout:

```json
{
  "repo": "owner/name",
  "sent": 2,
  "documents": [
    {"path": "docs/BR/login/login.md", "sha256": "9f3a1c2b8e5d4c7a9b0c1d2e3f4a5b6c7d8e9f0a"},
    {"path": "docs/SPEC/login/login-api.md", "sha256": "1a2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d"}
  ],
  "conflicts": []
}
```

5. 409 (divergência) → stdout com o envelope de erro do servidor + stderr com o
   diagnóstico → **exit 4**. O corpo do 409 traz o hash local e o do servidor
   (design master §19) — o kit **não** resolve sozinho: a resolução é humana.
6. Idempotência: reenviar os mesmos documentos não muda nada (upsert por
   `(repo_id, path)` no servidor, F4).

### 6.3 `pull` (servidor → repo)

**Único comando que escreve artefato de repo.**

1. `GET /api/artifacts/pending?repo=<owner/name>` — e `&demand=<demand_id>` quando
   `kit/state.json` tem demanda.
2. Resposta 200:

```json
{
  "artifacts": [
    {
      "id": "BR-013",
      "kind": "br",
      "path": "docs/BR/login/login.md",
      "status": "approved",
      "content": "---\nid: BR-013\nstatus: draft\n…\n---\n# Login\n…"
    }
  ]
}
```

3. Para cada artefato:
   - `path` é relativo à raiz do repo. `path` absoluto ou com `..` → **não escrever**,
     reportar no `skipped` do stdout (proteção de traversal).
   - `content` **tem o status do frontmatter reescrito** para o `status` do servidor
     (o banco é a autoridade do status; o frontmatter é espelho — design master §9.2).
     Reescrita **sem PyYAML** (stdlib):
     1. se o conteúdo começa com `---\n`, achar a linha `---` de fechamento;
     2. dentro do bloco, substituir a linha que casa com `^status:.*$` por
        `status: <status>`; se não houver, inserir `status: <status>` antes do
        fechamento;
     3. se não houver frontmatter, escrever o conteúdo como está (não inventar
        frontmatter).
   - grava em `<repo_root>/<path>`, criando os diretórios.
4. `git add <paths>` + `git commit -m "sdd: pull <demand_id>"` **apenas** se houve
   alteração (`git diff --cached --quiet` → não commita). Sem demanda no estado, a
   mensagem é `sdd: pull`.
5. stdout:

```json
{
  "demand_id": "3f1c9a2e-5b74-4d68-9a10-7c2e5b8d9f31",
  "written": ["docs/BR/login/login.md", "docs/SPEC/login/login-api.md"],
  "skipped": [],
  "changed": true,
  "commit": "5b6c7d8e9f0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c"
}
```

`commit` é `null` quando nada mudou (`changed: false`).

6. 404 (rota ausente no servidor) → stderr `servidor sem GET /api/artifacts/pending` →
   **exit 4**.

`repo_root` = `git rev-parse --show-toplevel`; fallback: o diretório atual.

### 6.4 `status`

1. `GET /api/claims/current` → a demanda corrente (ou 404/empty → `null`).
2. `GET /api/events?demand=<demand_id>` → os eventos (ordenados por `at`).
3. stdout:

```json
{
  "demand": {"id": "3f1c9a2e-5b74-4d68-9a10-7c2e5b8d9f31", "status": "in_progress", "module": "login", "title": "Login de alunos"},
  "events": [
    {"id": 41, "type": "claim", "at": "2026-11-10T12:34:56Z", "payload": {"repo": "owner/name"}},
    {"id": 42, "type": "artifact_synced", "at": "2026-11-10T12:36:10Z", "payload": {"path": "docs/BR/login/login.md"}}
  ]
}
```

`status` **não** falha por não haver demanda: devolve `{"demand": null, "events": []}` e
sai com **0**. O exit 3 é de `claim` e `dossier`.

### 6.5 `lint [paths]`

1. Caminhos: se não forem informados, usa todos os `*.md` de `docs/BR/`,
   `docs/SPEC/` e `docs/implementation-artifacts/` (mesmos globs do `sync`).
2. `POST /api/lint` — body `{"repo": "owner/name", "docs": [{"path": "...", "content": "..."}]}`.
3. stdout = resposta do servidor verbatim:

```json
{
  "findings": [
    {"rule": "BR-001", "severity": "error", "message": "frontmatter ausente", "path": "docs/BR/login/login.md", "line": 1, "detail": {}}
  ],
  "summary": {"error": 1, "warning": 0}
}
```

4. **exit 1** se `summary.error > 0`; caso contrário **exit 0**. `warning` não bloqueia
   (Contrato Comum §7.2).

### 6.6 `skill sync`

1. `GET /api/skills/manifest` → lista:

```json
[
  {"id": "business-discovery", "version": "1.0.0", "hash": "3f1c9a2e5b744d689a107c2e5b8d9f31", "description": "Descoberta de requisitos"}
]
```

2. Destino: `--dest` se informado; senão `.claude/skills/` (o Claude Code lê as skills
   do projeto em `.claude/skills/`). O caminho é relativo à raiz do repo.
3. Para cada skill: o arquivo local é `<dest>/<id>/SKILL.md` (layout de skill do Claude
   Code: uma pasta por skill, com `SKILL.md` dentro).
   - Se o arquivo existe e `sha256(conteúdo) == manifest.hash` → `unchanged`.
   - Senão: `GET /api/skills/{skill_id}` → corpo com o conteúdo markdown da skill →
     grava `<dest>/<id>/SKILL.md` (cria a pasta).
4. Skills locais que sumiram do manifesto **não** são apagadas (remoção é manual; o kit
   não apaga arquivo do usuário fora do escopo do sync).
5. stdout:

```json
{"dest": ".claude/skills", "updated": ["business-discovery"], "unchanged": ["technical-planning"]}
```

`skill sync --dest plugin/skills` regenera a cópia embarcada no pacote do plugin (§4.5).

### 6.7 `review`

1. Se `kit/reviewer.py` **não existir** → stderr `reviewer.py ausente: hook pre-push
   (F9) ainda não instalado neste repo` → **exit 2**.
2. Se existir: executa
   `[sys.executable, str(KIT_DIR / "reviewer.py"), "--demand", demand_id, "--repo-root", str(repo_root)]`
   e lê o JSON do stdout.
3. Formato esperado (contrato F8 → F9, §8):

```json
{"verdict": "blocking", "findings": [{"severity": "blocking", "title": "…", "detail": "…", "ac": "AC-003", "suggestion": "…"}]}
```

4. stdout = o JSON do reviewer verbatim. Exit code:
   - `blocking` → **1**
   - `clean`, `suggestions` → **0**
   - `pending` (LLM indisponível, design master §19) → **0**
5. Sem demanda corrente → **exit 3**.

### 6.8 `knowledge "<q>"`

1. `GET /api/knowledge?q=<urlencode>&repo=<repo>&top=<top>` — `repo` só é enviado se
   `--repo` for informado (sem ele, o servidor busca no corpus `method`); `top` só é
   enviado se `--top` for informado (default do servidor: 10).
2. stdout = resposta do servidor verbatim:

```json
{"query": "quando criar um Output Port", "hits": [{"heading": "…", "text": "…", "score": 4.1823, "source_kind": "method", "artifact_id": null, "demand_id": null, "corpus_id": "method"}]}
```

### 6.9 `dossier`

1. `demand_id` vem de `kit/state.json`; sem demanda → **exit 3**.
2. `GET /api/knowledge/dossier/<demand_id>`.
3. stdout = resposta do servidor verbatim (a forma está na spec da F7, §10).

### 6.10 `report <sha>`

1. `demand_id` de `kit/state.json`; sem demanda → **exit 3**.
2. Metadados do commit, via `git`:
   - `message` = `git show -s --format=%B <sha>`
   - `branch` = `git rev-parse --abbrev-ref HEAD`
   - `author` = `git log -1 --format=%an <sha>`
   - `files` = `git show --name-only --format= <sha>` (lista, sem linhas vazias)
3. `POST /api/commits` — body **exatamente** a forma do design master §17:

```json
{
  "sha": "9f3a1c2b8e5d4c7a9b0c1d2e3f4a5b6c7d8e9f0a",
  "message": "feat(login): endpoint de autenticação (AC-001)",
  "branch": "feat/login",
  "files": ["src/app/api/login/route.ts"],
  "demand_id": "3f1c9a2e-5b74-4d68-9a10-7c2e5b8d9f31"
}
```

4. Review: se `reviewer.py` existir, o mesmo protocolo do §6.7; se não existir,
   `verdict = "pending"` e `findings = []` (o commit é registrado mesmo sem revisão —
   design master §19: indisponibilidade externa não bloqueia).
5. `POST /api/reviews` — body da forma do design master §17 **mais `demand_id`** (a
   rota é do F6, e o F6 exige `sha` e `demand_id`):

```json
{
  "sha": "9f3a1c2b8e5d4c7a9b0c1d2e3f4a5b6c7d8e9f0a",
  "verdict": "pending",
  "findings": [],
  "demand_id": "3f1c9a2e-5b74-4d68-9a10-7c2e5b8d9f31"
}
```

6. stdout:

```json
{
  "commit": {"id": "0a5f3c22-7d1e-4a6b-9c3d-2e8f1a4b5c6d", "sha": "9f3a1c2b8e5d4c7a9b0c1d2e3f4a5b6c7d8e9f0a"},
  "review": {"id": "7b8c9d0e-1f2a-3b4c-5d6e-7f8091a2b3c4", "verdict": "pending", "findings": []}
}
```

## 7. Mapeamento de rotas usadas

| Comando | Método | Rota | Design master |
| --- | --- | --- | --- |
| `claim` | POST | `/api/claims` | §17 |
| `sync` | POST | `/api/artifacts/sync` | §17 |
| `pull` | GET | `/api/artifacts/pending` | §10 (fluxo) |
| `status` | GET | `/api/claims/current` | §17 |
| `status` | GET | `/api/events?demand=` | §17 |
| `skill sync` | GET | `/api/skills/manifest` | §17 |
| `skill sync` | GET | `/api/skills/{skill_id}` | §17 |
| `lint` | POST | `/api/lint` | §17 |
| `review` | — | (nenhuma rota; `reviewer.py` local) | §13 |
| `knowledge` | GET | `/api/knowledge?q=&repo=&top=` | §17 |
| `dossier` | GET | `/api/knowledge/dossier/{demand_id}` | §17 |
| `report` | POST | `/api/commits` | §17 |
| `report` | POST | `/api/reviews` | §17 |

Nenhuma outra rota é usada. O kit **não** inventa endpoint.

**Nota de coordenação com o F4:** `GET /api/artifacts/pending` é a **única** rota usada
que não está na lista do §17 do design master. Ela vem do fluxo do §10
("`sdd.py pull` → `GET /api/artifacts/pending`") e é exigida pelo enunciado desta fase.
O F4 é dono de `app/routers/artifacts.py` e **precisa expor essa rota**; enquanto não
exposer, `pull` responde exit 4 com o diagnóstico
`servidor sem GET /api/artifacts/pending`. O `POST /api/reviews` é do F6 e exige `sha` e
`demand_id` no body (F6 §5.9) — o kit manda os dois.

## 8. Contrato F8 → F9 (o que a F8 define e a F9 implementa)

F8 define o **comando** e o **formato de saída**; F9 implementa a execução.

| Item | Definido por F8 | Implementado por F9 |
| --- | --- | --- |
| Arquivo | `plugin/kit/reviewer.py` (não existe nesta fase) | F9 (Contrato Comum §8) |
| Invocação | `[sys.executable, reviewer.py, "--demand", <demand_id>, "--repo-root", <repo_root>]` | F9 |
| stdout | **um** objeto JSON `{"verdict": "clean\|suggestions\|blocking\|pending", "findings": [ {"severity","title","detail","ac","suggestion"} ]}` | F9 |
| stderr | diagnóstico livre (não é parseado) | F9 |
| exit do reviewer | `0` quando produziu JSON; ≠ 0 → o kit trata como falha de operação (exit 4) | F9 |
| Ausência do arquivo | `review` → **exit 2** com mensagem clara; `report` → review `verdict="pending"` | — |

O `plugin/hooks/pre-push` (F9) consome `kit/sdd.py` — **não** edita
(`plugin/kit/sdd.py` é de F8, Contrato Comum §8).

## 9. `plugin/README.md` — instalação num repo de dev

Conteúdo obrigatório (seções, nesta ordem):

1. **O que é** — kit de acesso ao servidor SDD; sem `pip install`, sem `npm install`.
2. **Layout instalado**:

```text
<repo de dev>/
├── .claude-plugin/plugin.json   # manifesto do plugin
├── hooks/pre-push               # hook de push (F9)
├── kit/sdd.py                   # o CLI
├── kit/state.json               # estado da demanda (gitignored)
├── kit/config.local.json        # token (gitignored)
└── .claude/skills/              # skills sincronizadas (`sdd.py skill sync`)
```

3. **Instalação** — copiar as pastas `plugin/` para o repo de dev e criar
   `kit/config.local.json`:

```json
{"token": "sdd_<token>"}
```

4. **Variáveis de ambiente**:

| Variável | Obrigatória | Default |
| --- | --- | --- |
| `SDD_URL` | sim | — (sem barra final) |
| `SDD_TOKEN` | sim (ou `kit/config.local.json`) | — |
| `SDD_REPO` | não | remote git (`git remote get-url origin`) |

5. **Comandos** — tabela com os 10 comandos, o que fazem e o exit code.
6. **Exit codes** — a tabela completa (0/1/2/3/4/5).
7. **Hook de push** — instalação (comando do F9):

```bash
git config core.hooksPath .claude/hooks
chmod +x .claude/hooks/pre-push
```

   O hook `pre-push` é da F9; até ele existir, o comando só instala o path.

8. **Gitignore** —orientação para ignorar `kit/state.json` e `kit/config.local.json`.

## 10. Tarefas

1. `plugin/.claude-plugin/plugin.json` — §4.1.
2. `plugin/hooks/hooks.json` — §4.2.
3. `plugin/.gitignore` — §4.3.
4. `plugin/kit/state.json.example` — §4.4.
5. `plugin/skills/{.gitkeep,README.md}` — §4.5.
6. `plugin/kit/sdd.py` — §5 e §6 (argparse, HTTP, sha256, git, os 10 comandos).
7. `plugin/README.md` — §9.
8. `server/tests/test_kit_contract.py` — §12.

## 11. Critérios de aceitação

- [ ] `python plugin/kit/sdd.py --help` lista os 10 comandos: `claim`, `sync`, `pull`,
      `status`, `skill sync`, `lint`, `review`, `knowledge`, `dossier`, `report`.
- [ ] Todo comando (fora do `--help`) escreve **JSON em stdout** — parseável por
      `json.loads`.
- [ ] Diagnóstico sempre em **stderr**; stdout nunca recebe texto de log.
- [ ] `SDD_URL` ausente → **exit 2**.
- [ ] `SDD_TOKEN` ausente (e sem `kit/config.local.json`) → **exit 5**.
- [ ] Nenhum import fora da stdlib (§5.1).
- [ ] `claim` grava `kit/state.json` com os 5 campos do contrato; 409/404 → exit 3.
- [ ] `pull` é o único comando que escreve artefato em `docs/`; `sync` não escreve
      arquivo nenhum.
- [ ] `sync` com 409 → exit 4; `lint` com finding `error` → exit 1; `review` com
      `blocking` → exit 1; `dossier` sem demanda → exit 3.
- [ ] `skill sync` escreve em `.claude/skills/` e não reescreve skill já sincronizada
      (hash igual).
- [ ] `plugin/skills/` não contém skill escrita à mão.
- [ ] `pytest server/tests` verde.

## 12. Testes — `server/tests/test_kit_contract.py`

Teste de **contrato**, sem servidor real: sobe um `http.server.ThreadingHTTPServer`
(stdlib) em `127.0.0.1` que devolve respostas programadas por path/método, e roda o kit
como subprocesso.

```python
KIT = Path(__file__).resolve().parents[2] / "plugin" / "kit" / "sdd.py"
```

| Teste | Verifica |
| --- | --- |
| `test_help_lists_all_commands` | `--help` contém os 10 comandos e o texto `usage:` |
| `test_help_exits_zero` | `--help` → exit 0 |
| `test_missing_sdd_url_exit_2` | sem `SDD_URL` → exit 2 |
| `test_missing_sdd_token_exit_5` | com `SDD_URL`, sem token → exit 5 |
| `test_stdlib_only_imports` | `ast` do `sdd.py`: todo `import`/`from` raiz em `sys.stdlib_module_names` (ou `__future__`) |
| `test_unknown_command_exit_2` | comando inexistente → exit 2 |
| `test_output_is_json` | `claim` contra o servidor de teste → stdout parseável por `json.loads` |
| `test_diagnostics_go_to_stderr` | stderr não é JSON e stdout é JSON |
| `test_claim_success_writes_state` | 200 → exit 0 e `kit/state.json` escrito com os 5 campos |
| `test_claim_conflict_exit_3` | 409 → exit 3 |
| `test_claim_empty_exit_3` | 404 `code: "empty"` → exit 3 |
| `test_sync_conflict_exit_4` | 409 → exit 4 |
| `test_lint_error_exit_1` | resposta com `summary.error = 1` → exit 1 |
| `test_lint_warning_exit_0` | só warnings → exit 0 |
| `test_review_blocking_exit_1` | `reviewer.py` de teste no PATH do kit → exit 1 |
| `test_review_missing_reviewer_exit_2` | sem `reviewer.py` → exit 2 |
| `test_dossier_without_demand_exit_3` | sem `kit/state.json` → exit 3 |
| `test_kit_uses_only_contract_routes` | o source não contém nenhum path de API fora da tabela da §7 |
| `test_exit_code_constants` | as constantes do source batem com a tabela do Contrato Comum §11 |

Regras do teste:

- Rodar o kit com `env` construído do zero (sem `SDD_TOKEN`/`SDD_URL` herdados).
- O servidor de teste responde por path: `/api/claims` → 200/409 programados;
  `/api/lint` → findings programados; `/api/knowledge/dossier/<id>` → 200.
- Nada de rede externa: o `SDD_URL` do teste é sempre `http://127.0.0.1:<porta>`.
- O `kit/state.json` do teste é escrito num diretório temporário — o teste **não** deixa
  arquivo no repo.

## 13. Fora de escopo

Hook de push (`plugin/hooks/pre-push`, `install-hooks.sh`), `plugin/kit/reviewer.py`
(F9), MCP, dependências externas, empacotamento em marketplace, sincronização
automática por daemon, edição de arquivo fora de `pull`/`skill sync`, e qualquer
endpoint fora da tabela da §7.

## 14. Referências

- Contrato Comum §3 (formato de erro), §6 (auth: token opaco, Bearer), §7.7 (contrato
  do kit), §8 (matriz de ownership), §9 (ondas: F8 na onda 3), §10 (definição de
  pronto), §11 (contrato do kit + tabela de exit codes).
- Design master §4 (as duas peças: servidor × plugin), §5 (decisão "script, não MCP"),
  §7 (estrutura do servidor), §9.2 (direção dos comandos pull/sync), §10 (fluxo do
  agente + tabela de comandos), §13 (hook pre-push, `orphaned`, reconcile), §14.4
  (dossiê), §16.2 (token do kit), §17 (superfície de API), §19 (erros: 409 divergência,
  LLM indisponível não bloqueia), Apêndice A (contrato do kit), Apêndice B (manifesto
  do plugin).
- F3 (`GET /api/skills/manifest`, `GET /api/skills/{id}`, busca provisória em
  `/api/method/search`), F4 (`POST /api/claims`, `POST /api/artifacts/sync`,
  `GET /api/claims/current`, `GET /api/artifacts/pending`, `POST /api/commits`,
  `POST /api/reviews`), F2 (`POST /api/lint`), F6 (`POST /api/reviews`: `sha` e
  `demand_id` obrigatórios; `verdict` ∈ clean/suggestions/blocking/pending), F7
  (`GET /api/knowledge`, `GET /api/knowledge/dossier/{id}`).
