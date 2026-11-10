# Plugin SDD — kit de acesso ao servidor de demandas

## 1. O que é

Kit de acesso ao servidor SDD (Spec-Driven Development) para repos de dev. O plugin
traz o **CLI** (`kit/sdd.py`) que o agente executa dentro do repo de dev: ele pede
demandas, sincroniza artefatos, roda lint e review, e devolve **exit code** — nunca
texto para o agente interpretar.

Sem `pip install`, sem `npm install`: o kit é **stdlib apenas** (Python 3.9+).

## 2. Layout instalado

```text
<repo de dev>/
├── .claude-plugin/plugin.json   # manifesto do plugin
├── hooks/pre-push               # hook de push (F9)
├── kit/sdd.py                   # o CLI
├── kit/state.json               # estado da demanda (gitignored)
├── kit/config.local.json        # token (gitignored)
└── .claude/skills/              # skills sincronizadas (`sdd.py skill sync`)
```

## 3. Instalação

Copie as pastas do plugin (`plugin/`) para o repo de dev e crie
`kit/config.local.json`:

```json
{"token": "sdd_<token>"}
```

O token sai de `POST /api/admin/tokens` (UI do servidor). Ele é opaco, guardado só
como SHA-256 no servidor, e vale para o repo ao qual está amarrado.

## 4. Variáveis de ambiente

| Variável | Obrigatória | Default |
| --- | --- | --- |
| `SDD_URL` | sim | — (sem barra final) |
| `SDD_TOKEN` | sim (ou `kit/config.local.json`) | — |
| `SDD_REPO` | não | remote git (`git remote get-url origin`) |

O token vem do ambiente **ou** de `kit/config.local.json` (preferência: ambiente).

## 5. Comandos

| Comando | O que faz | Sai com |
| --- | --- | --- |
| `sdd.py claim` | pega a próxima demanda `open` do repo e grava `kit/state.json` | 3 se não houver |
| `sdd.py sync` | reporta os artefatos locais ao servidor (repo → servidor) | 4 se o sync falhar |
| `sdd.py pull` | escreve os artefatos do servidor no repo e commita (servidor → repo) | 4 se a rota faltar |
| `sdd.py status` | demanda corrente + timeline de eventos | 0 |
| `sdd.py skill sync` | alinha `.claude/skills/` com o servidor | 0 |
| `sdd.py lint [paths]` | linter de artefatos (via API) | 1 se houver violação `error` |
| `sdd.py review` | roda a review da demanda corrente (`kit/reviewer.py`) | 1 se `blocking` |
| `sdd.py knowledge "<q>"` | busca RAG no método e/ou no repo | 0 |
| `sdd.py dossier` | necessidade + proposta + implementação da demanda | 3 sem demanda |
| `sdd.py report <sha>` | registra commit + review | 0 |

Saída: **JSON em stdout**, sempre. Diagnóstico: **stderr**.

## 6. Exit codes

| Código | Significado |
| --- | --- |
| `0` | ok |
| `1` | lint/review bloqueante |
| `2` | erro de uso (argumento, `SDD_URL` ausente, repo não identificável) |
| `3` | sem demanda |
| `4` | sync falhou (ou falha de operação contra o servidor) |
| `5` | auth (token ausente, inválido, revogado ou sem escopo) |

## 7. Hook de push

O gate de push é o hook **git** `pre-push` (fase F9):

```bash
git config core.hooksPath .claude/hooks
chmod +x .claude/hooks/pre-push
```

Até a F9 existir, o comando só instala o path — não há arquivo `pre-push` no pacote
ainda.

## 8. Gitignore

No repo de dev, ignore o estado e o token:

```text
kit/state.json
kit/config.local.json
```

O `plugin/.gitignore` do pacote já traz essas duas entradas.
