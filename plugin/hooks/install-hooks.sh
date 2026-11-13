#!/usr/bin/env bash
# Instala o hook pre-push do kit SDD no repositório atual.
# Idempotente. Executar uma vez por clone, de dentro do repo de dev.
#
# O gate roda em todo push: lint determinístico dos artefatos BR/SPEC tocados +
# review do diff contra a SPEC da demanda corrente. Só `blocking` aborta o push.

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$REPO_ROOT" ]; then
    echo "install-hooks: execute dentro de um repositório git." >&2
    exit 1
fi
cd "$REPO_ROOT"

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # <plugin>/hooks
DEST=".sdd/hooks"

if [ ! -f "$SRC/pre-push" ]; then
    echo "install-hooks: hook não encontrado em $SRC/pre-push" >&2
    exit 1
fi

mkdir -p "$DEST"
cp "$SRC/pre-push" "$DEST/pre-push"
chmod +x "$DEST/pre-push"

# Config local do repo: um clone não instalado não é afetado.
git config core.hooksPath "$DEST"

echo "hooks installed: core.hooksPath = $(git config core.hooksPath)"
echo "pre-push will run the SDD gate on every push."
