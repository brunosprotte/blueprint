"""Architectural linter for Blueprint projects. Stdlib only.

Run from project root:
    python tools/lint.py [--code-root PATH] [--docs-root PATH] [--strict]

Exit 0 = clean, 1 = violations.

Checks implemented (all rule ids come from the docs they enforce):
  META-004   file location + frontmatter + status lifecycle
  PAT-001    interactive JSX must have data-testid
  LS-001.3.1 domain entity must be a class (has behavior/invariant)
  LS-001.3.10 ApplicationFailure must extend Error or ApplicationFailure
  ES-008     use-case class must `implements <X>InputPort`
  ES-009.4   adapter must not import from domain/ (no business logic)
  LS-001     tsconfig.json must have "strict": true

This is pattern matching on file contents and paths, not a full TS parser.
It catches the explicit "Architectural Violations" lists in ES-005/006/008/009
and the LS-001 §8 Compliance Checklist. False positives are possible — narrow
the path glob or skip the rule with --ignore.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


DOC_ROOTS = {
    "BR", "PRD", "SPEC", "ES", "PAT", "LS", "TS", "TP", "RI", "META", "SK",
    "rules", "implementation-artifacts",
}

LIFECYCLE = {"draft", "pending", "on user review", "on agents review", "approved", "stable"}

JSX_INTERACTIVE = re.compile(r"<(button|a|input|select|textarea|form)\b", re.I)
DATATEST_RE = re.compile(r"data-testid")
ADAPTER_IMPORT_DOMAIN = re.compile(r"from\s+['\"][^'\"]*domain", re.I)
IMPLEMENTS_INPUT_PORT = re.compile(r"class\s+\w+[^{]*\bimplements\s+\w+InputPort\b")
DOMAIN_CLASS = re.compile(r"^\s*export\s+class\s+\w+", re.M)
APPFAIL_RE = re.compile(r"\bclass\s+\w*Failure\b[^{]*\{", re.M)
APPFAIL_OK_BASE = re.compile(r"extends\s+(Error|ApplicationFailure)")
TSCONFIG_STRICT = '"strict": true'


@dataclass
class Violation:
    path: str
    line: int
    rule: str
    msg: str


def lint_markdown(path: Path, text: str) -> list[Violation]:
    out: list[Violation] = []
    parts = path.parts
    if "docs" in parts:
        idx = parts.index("docs")
        if idx + 1 < len(parts) and parts[idx + 1] not in DOC_ROOTS:
            out.append(Violation(str(path), 1, "META-004",
                                 f"file under docs/ but not in allowed root: {parts[idx + 1]}"))

    # Accept either YAML frontmatter (`---\nstatus: …\n---`) or the project's
    # metadata-table convention (`| **Status** | Approved |`). YAML takes
    # priority; fall through to the table when YAML exists but lacks status.
    yaml_status: str | None = None
    if text.startswith("---"):
        m = re.search(r"^status:\s*(.+?)\s*$", text, re.M)
        if m:
            yaml_status = m.group(1).strip().lower()
        if yaml_status is not None:
            if yaml_status not in LIFECYCLE:
                out.append(Violation(str(path), 0, "META-004",
                                     f"invalid status {yaml_status!r}; expected one of {sorted(LIFECYCLE)}"))
            return out

    table_status: str | None = None
    if re.search(r"\|\s*\*\*?Status\*\*?\s*\|", text):
        m = re.search(r"\|\s*\*\*?Status\*\*?\s*\|\s*(.+?)\s*\|", text)
        if m:
            table_status = m.group(1).strip().strip("*").lower()
    if table_status is not None:
        if table_status not in LIFECYCLE:
            out.append(Violation(str(path), 0, "META-004",
                                 f"invalid status {table_status!r}; expected one of {sorted(LIFECYCLE)}"))
        return out

    out.append(Violation(str(path), 1, "META-004",
                         "missing metadata (no YAML frontmatter, no Status table row)"))
    return out


def lint_ts(path: Path, text: str) -> list[Violation]:
    out: list[Violation] = []
    posix = str(path).replace("\\", "/")

    if JSX_INTERACTIVE.search(text) and not DATATEST_RE.search(text):
        for i, line in enumerate(text.splitlines(), 1):
            if JSX_INTERACTIVE.search(line):
                out.append(Violation(str(path), i, "PAT-001",
                                     "interactive JSX without data-testid"))
                break

    if "/domain/" in posix:
        if not DOMAIN_CLASS.search(text):
            out.append(Violation(str(path), 1, "LS-001.3.1",
                                 "domain file has no `export class` (consider Contract/type instead)"))

    if "/use-cases/" in posix or "/application/use-cases/" in posix:
        if not IMPLEMENTS_INPUT_PORT.search(text):
            out.append(Violation(str(path), 1, "ES-008",
                                 "use-case class must `implements <X>InputPort`"))

    if "/adapters/" in posix or "/api/" in posix or "/routes/" in posix:
        for i, line in enumerate(text.splitlines(), 1):
            if ADAPTER_IMPORT_DOMAIN.search(line):
                out.append(Violation(str(path), i, "ES-009.4",
                                     "adapter imports from domain/ (no business logic in adapter)"))
                break

    if "Failure" in path.stem:
        m = APPFAIL_RE.search(text)
        if m and not APPFAIL_OK_BASE.search(text):
            line_no = text[: m.start()].count("\n") + 1
            out.append(Violation(str(path), line_no, "LS-001.3.10",
                                 "ApplicationFailure must extend Error or ApplicationFailure"))

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code-root", default="implementation-artifacts", type=Path)
    ap.add_argument("--docs-root", default="docs", type=Path)
    ap.add_argument("--ignore", action="append", default=[],
                    help="rule id to skip (repeatable)")
    ap.add_argument("--strict", action="store_true",
                    help="fail on warnings (currently same as default)")
    args = ap.parse_args()

    ignore = set(args.ignore)
    violations: list[Violation] = []

    if args.docs_root.exists():
        for p in args.docs_root.rglob("*.md"):
            try:
                text = p.read_text(encoding="utf-8")
            except OSError:
                continue
            violations.extend(v for v in lint_markdown(p, text) if v.rule not in ignore)
    else:
        print(f"warn: docs root not found: {args.docs_root}", file=sys.stderr)

    if args.code_root.exists():
        for ext in ("*.ts", "*.tsx"):
            for p in args.code_root.rglob(ext):
                try:
                    text = p.read_text(encoding="utf-8")
                except OSError:
                    continue
                violations.extend(v for v in lint_ts(p, text) if v.rule not in ignore)
        tsconfig = args.code_root / "tsconfig.json"
        if tsconfig.exists() and "LS-001" not in ignore:
            t = tsconfig.read_text(encoding="utf-8")
            if TSCONFIG_STRICT not in t:
                violations.append(Violation(str(tsconfig), 0, "LS-001",
                                           'tsconfig.json missing "strict": true'))
    else:
        print(f"warn: code root not found: {args.code_root}", file=sys.stderr)

    for v in violations:
        print(f"{v.path}:{v.line}: [{v.rule}] {v.msg}")
    print(f"\n{len(violations)} violation(s)")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())