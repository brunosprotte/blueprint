#!/usr/bin/env python3
"""Kit SDD — CLI (stdlib only) para acesso ao servidor de demandas SDD.

Fase F8. Contrato vinculante: design/specs/2026-11-10-contrato-comum.md §7.7 e §11.
Spec da fase: design/specs/2026-11-10-fase-F8-plugin-kit.md §5 e §6.

O kit não interpreta, não sugere, não decide: executa o que o servidor decidiu e
devolve um exit code. Importações restritas à stdlib (§5.1 da spec F8): argparse,
hashlib, json, os, re, subprocess, sys, urllib.* e pathlib.
"""

from __future__ import annotations

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

# --- Exit codes (Contrato Comum §11) -----------------------------------------

EXIT_OK = 0
EXIT_BLOCKING = 1
EXIT_USAGE = 2
EXIT_NO_DEMAND = 3
EXIT_SYNC_FAILED = 4
EXIT_AUTH = 5

TIMEOUT = 30

# --- Layout do kit instalado -------------------------------------------------

KIT_DIR = Path(__file__).resolve().parent
STATE_FILE = KIT_DIR / "state.json"
CONFIG_FILE = KIT_DIR / "config.local.json"
REVIEWER_FILE = KIT_DIR / "reviewer.py"

DOC_BASES = ("docs/BR", "docs/SPEC", "docs/implementation-artifacts")


# --- Erros -------------------------------------------------------------------


class KitError(Exception):
    """Erro do kit que mapeia para um exit code do contrato."""

    code = "kit_error"
    exit_code = EXIT_USAGE

    def __init__(
        self,
        message: str,
        code: str | None = None,
        detail: dict | None = None,
        exit_code: int | None = None,
    ):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if exit_code is not None:
            self.exit_code = exit_code
        self.detail = detail or {}


class UsageError(KitError):
    code = "usage_error"
    exit_code = EXIT_USAGE


class AuthError(KitError):
    code = "auth_error"
    exit_code = EXIT_AUTH


class TransportError(KitError):
    code = "transport_error"
    exit_code = EXIT_SYNC_FAILED


class ServerError(KitError):
    """Resposta HTTP com status de erro. O corpo vai para stdout verbatim."""

    code = "server_error"
    exit_code = EXIT_SYNC_FAILED

    def __init__(self, status: int, body: object):
        super().__init__(f"HTTP {status}", code="server_error", detail={"status": status})
        self.status = status
        self.body = body


# --- HTTP (stdlib) -----------------------------------------------------------


class Api:
    """Cliente HTTP do kit. Só stdlib, timeout fixo, JSON em tudo."""

    def __init__(self, base_url: str, token: str):
        base = base_url.rstrip("/")
        # Apêndice A mostra SDD_URL com "/api" no fim; as rotas da spec já
        # começam com "/api". Normaliza para não duplicar o prefixo.
        if base.endswith("/api"):
            base = base[: -len("/api")]
        self.base_url = base
        self.token = token

    def request(
        self, method: str, path: str, payload: dict | None = None, expect_json: bool = True
    ) -> tuple[int, object, str]:
        """Retorna (status, corpo parseado, corpo cru). Levanta ServerError/TransportError."""
        url = self.base_url + path
        data = (
            json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        )
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json, text/plain, */*",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                status = resp.status
                raw = resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace")
            raise ServerError(exc.code, parse_error_body(raw))
        except (urllib.error.URLError, TimeoutError) as exc:
            raise TransportError(f"falha de rede: {exc}")
        if not raw:
            return status, None, raw
        if not expect_json:
            return status, raw, raw
        try:
            return status, json.loads(raw), raw
        except json.JSONDecodeError:
            raise TransportError("resposta do servidor nao e JSON")


def parse_error_body(raw: str) -> object:
    """Corpo de erro: JSON do servidor, ou envelope mínimo se não for JSON."""
    if not raw:
        return {"error": {"code": "http_error", "message": "resposta vazia", "detail": {}}}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": {"code": "http_error", "message": raw, "detail": {}}}


# --- Saída -------------------------------------------------------------------


def emit(payload: object) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def emit_raw(raw: str) -> None:
    sys.stdout.write(raw.strip() + "\n")
    sys.stdout.flush()


def warn(message: str) -> None:
    sys.stderr.write(message.rstrip("\n") + "\n")
    sys.stderr.flush()


def force_utf8(stream) -> None:
    """Garante UTF-8 na saida: JSON do servidor pode ter acento e o console
    legado (cp1252) quebraria com UnicodeEncodeError."""
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def emit_error(code: str, message: str, detail: dict | None = None) -> None:
    emit({"error": {"code": code, "message": message, "detail": detail or {}}})


# --- Git / filesystem ---------------------------------------------------------


def git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd) if cwd else None,
    )


def repo_root() -> Path:
    """Raiz do repo de dev. Fallback: diretório atual."""
    out = git(["rev-parse", "--show-toplevel"])
    if out.returncode == 0 and out.stdout.strip():
        return Path(out.stdout.strip())
    return Path.cwd()


def resolve_repo() -> str:
    """SDD_REPO → remote git origin → erro de uso."""
    env = os.environ.get("SDD_REPO", "").strip()
    if env:
        return env
    out = git(["remote", "get-url", "origin"])
    if out.returncode != 0 or not out.stdout.strip():
        raise UsageError("repo nao identificavel")
    match = re.search(r"[:/](?P<owner>[^/]+)/(?P<name>[^/]+?)(?:\.git)?\s*$", out.stdout.strip())
    if not match:
        raise UsageError("repo nao identificavel")
    return f"{match.group('owner')}/{match.group('name')}"


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now_iso() -> str:
    """Timestamp UTC ISO 8601 com sufixo Z.

    Sem `import datetime`/`time`: §5.1 da spec F8 restringe os imports do kit.
    """
    out = subprocess.run(
        [
            sys.executable,
            "-c",
            "import time;print(time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout.strip()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def rel_to(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def collect_docs(root: Path, explicit: list[str] | None = None) -> list[tuple[str, str]]:
    """(path relativo, conteúdo) dos documentos de artefato do repo."""
    out: list[tuple[str, str]] = []
    if explicit:
        for item in explicit:
            path = Path(item)
            full = path if path.is_absolute() else root / path
            if full.is_file():
                out.append((rel_to(root, full), read_text(full)))
        return out
    for base in DOC_BASES:
        folder = root / base
        if not folder.is_dir():
            continue
        for item in sorted(folder.rglob("*.md")):
            out.append((rel_to(root, item), read_text(item)))
    return out


def rewrite_status(content: str, status: str | None) -> str:
    """Espelha o status do servidor no frontmatter (sem PyYAML)."""
    if not status or not content.startswith("---"):
        return content
    lines = content.split("\n")
    if lines[0].strip() != "---":
        return content
    close = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            close = index
            break
    if close is None:
        return content
    block = lines[1:close]
    rewritten = []
    replaced = False
    for line in block:
        if re.match(r"^status:", line):
            rewritten.append(f"status: {status}")
            replaced = True
        else:
            rewritten.append(line)
    if not replaced:
        rewritten.append(f"status: {status}")
    return "\n".join(lines[:1] + rewritten + lines[close:])


# --- Estado e configuração ----------------------------------------------------


def load_token() -> str:
    token = os.environ.get("SDD_TOKEN", "").strip()
    if token:
        return token
    if CONFIG_FILE.exists():
        try:
            data = json.loads(read_text(CONFIG_FILE))
        except json.JSONDecodeError:
            return ""
        if isinstance(data, dict):
            return str(data.get("token") or "").strip()
    return ""


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        data = json.loads(read_text(STATE_FILE))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def current_demand_id() -> str | None:
    value = load_state().get("demand_id")
    return str(value) if value else None


def write_state(body: object, repo: str) -> dict:
    payload = body if isinstance(body, dict) else {}
    demand = payload.get("demand") if isinstance(payload.get("demand"), dict) else {}
    br = payload.get("br") if isinstance(payload.get("br"), dict) else {}
    specs = payload.get("specs") if isinstance(payload.get("specs"), list) else []
    state = {
        "demand_id": demand.get("id"),
        "repo": repo,
        "spec_ids": [s.get("id") for s in specs if isinstance(s, dict) and s.get("id")],
        "br_id": br.get("id") if br.get("id") else None,
        "claimed_at": demand.get("claimed_at") or utc_now_iso(),
    }
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return state


# --- Mapeamento status HTTP → exit code --------------------------------------


def exit_for_status(command: str, status: int) -> int:
    if status in (401, 403):
        return EXIT_AUTH
    if status == 404:
        return EXIT_NO_DEMAND if command in ("claim", "dossier") else EXIT_SYNC_FAILED
    if status == 409:
        return EXIT_NO_DEMAND if command == "claim" else EXIT_SYNC_FAILED
    if status in (400, 422):
        return EXIT_SYNC_FAILED if command == "sync" else EXIT_USAGE
    return EXIT_SYNC_FAILED


def diagnostic_for(command: str, status: int, body: object) -> str:
    code = ""
    message = ""
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        code = str(body["error"].get("code") or "")
        message = str(body["error"].get("message") or "")
    if command == "claim" and status in (404, 409):
        return "sem demanda open para este repo"
    if command == "pull" and status == 404:
        return "servidor sem GET /api/artifacts/pending"
    if code or message:
        return f"{command}: HTTP {status} ({code}: {message})"
    return f"{command}: HTTP {status}"


# --- Comandos -----------------------------------------------------------------


def cmd_claim(api: Api, args: argparse.Namespace) -> int:
    repo = resolve_repo()
    _, body, raw = api.request("POST", "/api/claims", {"repo": repo})
    write_state(body, repo)
    emit_raw(raw)
    return EXIT_OK


def cmd_sync(api: Api, args: argparse.Namespace) -> int:
    repo = resolve_repo()
    docs = collect_docs(repo_root())
    payload = {
        "repo": repo,
        "docs": [{"path": path, "content": content} for path, content in docs],
    }
    _, body, _ = api.request("POST", "/api/artifacts/sync", payload)
    conflicts = []
    if isinstance(body, dict) and isinstance(body.get("conflicts"), list):
        conflicts = body["conflicts"]
    emit(
        {
            "repo": repo,
            "sent": len(docs),
            "documents": [{"path": path, "sha256": sha256(content)} for path, content in docs],
            "conflicts": conflicts,
        }
    )
    return EXIT_OK


def cmd_pull(api: Api, args: argparse.Namespace) -> int:
    repo = resolve_repo()
    root = repo_root()
    demand_id = current_demand_id()
    query = {"repo": repo}
    if demand_id:
        query["demand"] = demand_id
    _, body, _ = api.request(
        "GET", "/api/artifacts/pending?" + urllib.parse.urlencode(query)
    )
    artifacts = []
    if isinstance(body, dict) and isinstance(body.get("artifacts"), list):
        artifacts = body["artifacts"]
    written: list[str] = []
    skipped: list[str] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        rel = str(artifact.get("path") or "")
        target = Path(rel)
        if not rel or target.is_absolute() or ".." in target.parts:
            skipped.append(rel)
            continue
        content = rewrite_status(
            str(artifact.get("content") or ""), artifact.get("status")
        )
        destination = root / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        written.append(rel)
    changed, commit = commit_written(root, written, demand_id)
    emit(
        {
            "demand_id": demand_id,
            "written": written,
            "skipped": skipped,
            "changed": changed,
            "commit": commit,
        }
    )
    return EXIT_OK


def commit_written(root: Path, paths: list[str], demand_id: str | None) -> tuple[bool, str | None]:
    """git add + commit só se houve alteração."""
    if not paths:
        return False, None
    add = git(["add", "--", *paths], cwd=root)
    if add.returncode != 0:
        warn(f"git add falhou: {add.stderr.strip()}")
        return True, None
    diff = git(["diff", "--cached", "--quiet"], cwd=root)
    if diff.returncode == 0:
        return False, None
    message = f"sdd: pull {demand_id}" if demand_id else "sdd: pull"
    commit = git(["commit", "-m", message], cwd=root)
    if commit.returncode != 0:
        warn(f"git commit falhou: {commit.stderr.strip()}")
        return True, None
    sha = git(["rev-parse", "HEAD"], cwd=root).stdout.strip()
    return True, sha or None


def cmd_status(api: Api, args: argparse.Namespace) -> int:
    demand = None
    try:
        _, body, _ = api.request("GET", "/api/claims/current")
    except ServerError as exc:
        if exc.status != 404:
            raise
        body = None
    if isinstance(body, dict):
        if "demand" in body:
            demand = body["demand"] if isinstance(body["demand"], dict) else None
        else:
            demand = body
    demand_id = None
    if isinstance(demand, dict):
        demand_id = demand.get("id")
    if not demand_id:
        demand_id = current_demand_id()
    events: list = []
    if demand_id:
        try:
            _, body, _ = api.request(
                "GET", "/api/events?" + urllib.parse.urlencode({"demand": demand_id})
            )
        except ServerError as exc:
            if exc.status != 404:
                raise
            body = None
        if isinstance(body, dict) and isinstance(body.get("events"), list):
            events = body["events"]
        elif isinstance(body, list):
            events = body
    emit({"demand": demand, "events": events})
    return EXIT_OK


def cmd_skill_sync(api: Api, args: argparse.Namespace) -> int:
    dest_arg = args.dest or ".claude/skills"
    dest = Path(dest_arg)
    if not dest.is_absolute():
        dest = repo_root() / dest
    _, body, _ = api.request("GET", "/api/skills/manifest")
    manifest = body if isinstance(body, list) else []
    if isinstance(body, dict) and isinstance(body.get("skills"), list):
        manifest = body["skills"]
    updated: list[str] = []
    unchanged: list[str] = []
    for skill in manifest:
        if not isinstance(skill, dict):
            continue
        skill_id = str(skill.get("id") or "")
        if not skill_id:
            continue
        target = dest / skill_id / "SKILL.md"
        expected = skill.get("hash")
        if target.exists() and expected and sha256(read_text(target)) == expected:
            unchanged.append(skill_id)
            continue
        _, content, raw = api.request(
            "GET", "/api/skills/" + urllib.parse.quote(skill_id, safe=""), expect_json=False
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(extract_skill_content(content, raw), encoding="utf-8")
        updated.append(skill_id)
    emit({"dest": dest_arg, "updated": updated, "unchanged": unchanged})
    return EXIT_OK


def extract_skill_content(content: object, raw: str) -> str:
    """O corpo pode ser markdown cru, string JSON ou {"content": "..."}."""
    if isinstance(content, dict) and "content" in content:
        return str(content["content"])
    if isinstance(content, str):
        return content
    return raw


def cmd_lint(api: Api, args: argparse.Namespace) -> int:
    repo = resolve_repo()
    docs = collect_docs(repo_root(), list(args.paths or []))
    payload = {
        "repo": repo,
        "docs": [{"path": path, "content": content} for path, content in docs],
    }
    _, body, raw = api.request("POST", "/api/lint", payload)
    emit_raw(raw)
    errors = 0
    if isinstance(body, dict):
        summary = body.get("summary")
        if isinstance(summary, dict) and "error" in summary:
            errors = int(summary.get("error") or 0)
        else:
            findings = body.get("findings")
            if isinstance(findings, list):
                errors = sum(
                    1
                    for f in findings
                    if isinstance(f, dict) and f.get("severity") == "error"
                )
    return EXIT_BLOCKING if errors > 0 else EXIT_OK


def cmd_review(api: Api, args: argparse.Namespace) -> int:
    if not REVIEWER_FILE.exists():
        raise UsageError(
            "reviewer.py ausente: hook pre-push (F9) ainda nao instalado neste repo"
        )
    demand_id = current_demand_id()
    if not demand_id:
        raise KitError("sem demanda corrente", code="no_demand", exit_code=EXIT_NO_DEMAND)
    verdict, findings = run_reviewer(demand_id)
    emit({"verdict": verdict, "findings": findings})
    return EXIT_BLOCKING if verdict == "blocking" else EXIT_OK


def run_reviewer(demand_id: str) -> tuple[str, list]:
    """Executa kit/reviewer.py (F9) e devolve (verdict, findings)."""
    proc = subprocess.run(
        [
            sys.executable,
            str(REVIEWER_FILE),
            "--demand",
            demand_id,
            "--repo-root",
            str(repo_root()),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise KitError(
            f"reviewer.py falhou (exit {proc.returncode})",
            code="reviewer_failed",
            exit_code=EXIT_SYNC_FAILED,
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise KitError(
            "reviewer.py nao devolveu JSON",
            code="reviewer_invalid_output",
            exit_code=EXIT_SYNC_FAILED,
        )
    if not isinstance(payload, dict):
        raise KitError(
            "reviewer.py nao devolveu JSON",
            code="reviewer_invalid_output",
            exit_code=EXIT_SYNC_FAILED,
        )
    verdict = str(payload.get("verdict") or "pending")
    findings = payload.get("findings")
    return verdict, findings if isinstance(findings, list) else []


def cmd_knowledge(api: Api, args: argparse.Namespace) -> int:
    query = {"q": args.query}
    if args.repo:
        query["repo"] = args.repo
    if args.top is not None:
        query["top"] = str(args.top)
    _, _, raw = api.request("GET", "/api/knowledge?" + urllib.parse.urlencode(query))
    emit_raw(raw)
    return EXIT_OK


def cmd_dossier(api: Api, args: argparse.Namespace) -> int:
    demand_id = current_demand_id()
    if not demand_id:
        raise KitError("sem demanda corrente", code="no_demand", exit_code=EXIT_NO_DEMAND)
    _, _, raw = api.request(
        "GET", "/api/knowledge/dossier/" + urllib.parse.quote(demand_id, safe="")
    )
    emit_raw(raw)
    return EXIT_OK


def cmd_report(api: Api, args: argparse.Namespace) -> int:
    demand_id = current_demand_id()
    if not demand_id:
        raise KitError("sem demanda corrente", code="no_demand", exit_code=EXIT_NO_DEMAND)
    sha = args.sha
    root = repo_root()
    message = git(["show", "-s", "--format=%B", sha], cwd=root).stdout.strip()
    branch = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root).stdout.strip()
    files = [
        line.strip()
        for line in git(["show", "--name-only", "--format=", sha], cwd=root).stdout.splitlines()
        if line.strip()
    ]
    _, commit_body, _ = api.request(
        "POST",
        "/api/commits",
        {
            "sha": sha,
            "message": message,
            "branch": branch,
            "files": files,
            "demand_id": demand_id,
        },
    )
    if REVIEWER_FILE.exists():
        verdict, findings = run_reviewer(demand_id)
    else:
        verdict, findings = "pending", []
    _, review_body, _ = api.request(
        "POST",
        "/api/reviews",
        {"sha": sha, "verdict": verdict, "findings": findings, "demand_id": demand_id},
    )
    emit({"commit": commit_body, "review": review_body})
    return EXIT_OK


HANDLERS = {
    "claim": cmd_claim,
    "sync": cmd_sync,
    "pull": cmd_pull,
    "status": cmd_status,
    "skill": cmd_skill_sync,
    "lint": cmd_lint,
    "review": cmd_review,
    "knowledge": cmd_knowledge,
    "dossier": cmd_dossier,
    "report": cmd_report,
}


# --- CLI ----------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sdd.py",
        description="Kit SDD - acesso ao servidor de demandas (fase F8).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("claim", help="pega a proxima demanda open do repo")
    sub.add_parser("sync", help="reporta os artefatos locais ao servidor (repo -> servidor)")
    sub.add_parser("pull", help="aplica no repo os artefatos do servidor (servidor -> repo)")
    sub.add_parser("status", help="estado da demanda corrente + timeline de eventos")
    skill = sub.add_parser("skill", help="comandos de skill")
    skill.add_argument("action", choices=["sync"], help="sincroniza as skills do servidor")
    skill.add_argument("--dest", default=None, help="destino (default: .claude/skills)")
    lint = sub.add_parser("lint", help="linter de artefatos (via API)")
    lint.add_argument("paths", nargs="*", help="caminhos (default: globs de docs/)")
    sub.add_parser("review", help="roda a review da demanda corrente (reviewer.py local)")
    knowledge = sub.add_parser("knowledge", help="busca RAG")
    knowledge.add_argument("query", help="termo de busca")
    knowledge.add_argument("--repo", default=None, help="owner/name (default: corpus method)")
    knowledge.add_argument("--top", type=int, default=None, help="numero de hits")
    sub.add_parser("dossier", help="necessidade + proposta + implementacao")
    report = sub.add_parser("report", help="reporta commit + findings")
    report.add_argument("sha", help="sha do commit")
    return parser


def dispatch(args: argparse.Namespace) -> int:
    command = args.command
    url = os.environ.get("SDD_URL", "").strip()
    if not url:
        raise UsageError("SDD_URL ausente")
    token = load_token()
    if not token:
        raise AuthError("SDD_TOKEN ausente")
    api = Api(url, token)
    try:
        return HANDLERS[command](api, args)
    except ServerError as exc:
        emit(exc.body if isinstance(exc.body, (dict, list)) else {"error": {"code": "http_error", "message": str(exc.body), "detail": {}}})
        warn(diagnostic_for(command, exc.status, exc.body))
        return exit_for_status(command, exc.status)


def main(argv: list[str] | None = None) -> int:
    force_utf8(sys.stdout)
    force_utf8(sys.stderr)
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return dispatch(args)
    except KitError as exc:
        emit_error(exc.code, exc.message, exc.detail)
        warn(exc.message)
        return exc.exit_code


if __name__ == "__main__":
    sys.exit(main())
