# tools/

Lightweight helpers for the Blueprint methodology. Stdlib only, no installs.

## `lint.py` — architectural linter

Pattern-matches the explicit "Architectural Violations" lists in `docs/ES/ES-005..009` and the LS-001 §8 Compliance Checklist. Not a full TS parser — catches import-direction mistakes, missing class declarations, missing `data-testid`, missing TS strict flag, invalid frontmatter / status.

```bash
python tools/lint.py                        # walks docs/ + implementation-artifacts/
python tools/lint.py --ignore PAT-001       # skip a rule (repeatable)
python tools/lint.py --code-root ../other   # point at a different code tree
```

Exit `0` = clean, `1` = violations. Each line: `path:line: [RULE_ID] message`.

## `retrieve.py` — BM25 retriever over docs/

When generating a SPEC, ask a short question in natural language and paste the top hits into the agent's context. Replaces the "remember to load ES-007" problem with a 1-second lexical lookup.

```bash
python tools/retrieve.py --query "quando devo criar um Output Port" --top 5
python tools/retrieve.py --query "test data-testid PAT-001" --top 3
```

Honest limits: lexical ≠ semantic. Misses synonyms, over-ranks exact terms. Good enough for technical Portuguese where query terms usually appear in the answer. Swap in an embedding backend when needed.

## `hooks/pre-commit` + `install-hooks.sh` — pre-commit lint

```bash
bash tools/install-hooks.sh    # one-time per clone: sets core.hooksPath = tools/hooks
```

After install, every commit runs `tools/lint.py --ignore META-004`. The `META-004` (metadata) rule is suppressed in the hook because several legacy docs (`AGENTS.md`, `write-tests.md`, `SK/caveman/README.md`, etc.) don't yet carry the YAML/table metadata. Architectural rules (ES, LS, PAT) still block. Remove the ignore once those docs are cleaned up. Staged files only (`.md` and `.ts`/`.tsx`); empty-stage commits exit immediately. Hook is bash — Windows users need WSL or Git Bash (already used by git on Windows).

## Hinge sections in ES/PAT docs

Every architectural rule doc (`ES-001..011`, `PAT-001`) carries an explicit `## Section: Hinge — …` H2 wrapper at the end. These are the canonical-decision chunks the retriever surfaces for questions like "when do I create an Output Port" or "how should I name a data-testid". The full prose still lives under the original numbered H1 sections; the Hinge section is the index.

## What's *not* here

- No JEV call. The methodology's gating decisions (artifact type, state transitions) are reasoning-heavy, not classification — JEV would be slower and weaker than the main model.
- No embedding-based RAG yet. BM25 + hinge H2 wrappers are the cheapest thing that works for Portuguese technical docs.
- No in-place rewrite of the skills. Trees in `docs/SK/*/SKILL.md` are appended under `## Árvores de Decisão`; original prose is preserved.