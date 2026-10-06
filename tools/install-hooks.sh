#!/usr/bin/env bash
# Install the pre-commit hook by setting core.hooksPath = tools/hooks.
# Idempotent. Run once per clone.

set -e
cd "$(git rev-parse --show-toplevel)"

git config core.hooksPath tools/hooks
chmod +x tools/hooks/pre-commit

echo "hooks installed: core.hooksPath = $(git config core.hooksPath)"
echo "pre-commit will run tools/lint.py on every commit."