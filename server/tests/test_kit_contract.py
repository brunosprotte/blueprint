"""Teste de contrato do kit SDD (fase F8).

Servidor HTTP falso (stdlib) + kit executado como subprocesso. Sem rede externa.
O kit roda num diretório temporário: `kit/state.json` e `kit/config.local.json`
nunca tocam o repo.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
KIT = REPO_ROOT / "plugin" / "kit" / "sdd.py"

COMMANDS = [
    "claim",
    "sync",
    "pull",
    "status",
    "skill",
    "lint",
    "review",
    "knowledge",
    "dossier",
    "report",
]

# Imports permitidos pela spec F8 §5.1 (stdlib apenas).
ALLOWED_IMPORTS = {
    "__future__",
    "argparse",
    "hashlib",
    "json",
    "os",
    "re",
    "subprocess",
    "sys",
    "urllib",
    "pathlib",
}

# Rotas do contrato (spec F8 §7). Nada fora daqui.
ALLOWED_ROUTES = (
    "/api/claims",
    "/api/artifacts/sync",
    "/api/artifacts/pending",
    "/api/events",
    "/api/skills/manifest",
    "/api/skills/",
    "/api/lint",
    "/api/knowledge",
    "/api/commits",
    "/api/reviews",
)

EXIT_CODES = {
    "EXIT_OK": 0,
    "EXIT_BLOCKING": 1,
    "EXIT_USAGE": 2,
    "EXIT_NO_DEMAND": 3,
    "EXIT_SYNC_FAILED": 4,
    "EXIT_AUTH": 5,
}

CLAIM_RESPONSE = {
    "demand": {
        "id": "3f1c9a2e-5b74-4d68-9a10-7c2e5b8d9f31",
        "status": "claimed",
        "claimed_at": "2026-11-10T12:34:56Z",
        "module": "login",
        "title": "Login de alunos",
    },
    "br": {"id": "BR-013", "path": "docs/BR/login/login.md"},
    "specs": [{"id": "SPEC-002", "path": "docs/SPEC/login/login-api.md"}],
    "spec_graph": [{"parent": "SPEC-001", "child": "SPEC-002", "type": "depends_on"}],
    "skill_manifest": [{"id": "business-discovery", "version": "1.0.0", "hash": "3f1c"}],
    "knowledge_hits": [],
}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self):  # noqa: N802
        self._reply("GET")

    def do_POST(self):  # noqa: N802
        self._reply("POST")

    def _reply(self, method):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            self.rfile.read(length)
        routes = self.server.routes
        entry = routes.get((method, path))
        if entry is None:
            entry = routes.get((method, "*"))
        if entry is None:
            status = 404
            payload = {"error": {"code": "not_found", "message": path, "detail": {}}}
        else:
            status, payload = entry
        raw = (
            payload.encode("utf-8")
            if isinstance(payload, str)
            else json.dumps(payload).encode("utf-8")
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    httpd.routes = {}
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def kit_dir(tmp_path):
    """Kit instalado num diretório temporário (estado e token fora do repo)."""
    folder = tmp_path / "kit"
    folder.mkdir()
    shutil.copy(KIT, folder / "sdd.py")
    return folder


def run_kit(kit_dir, *args, env_extra=None, cwd=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("SDD_")}
    env.update(env_extra or {})
    return subprocess.run(
        [sys.executable, str(kit_dir / "sdd.py"), *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd) if cwd else str(kit_dir.parent),
    )


def is_json(text):
    try:
        json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return False
    return True


# --- Help e uso ---------------------------------------------------------------


def test_help_lists_all_commands(kit_dir):
    proc = run_kit(kit_dir, "--help")
    assert "usage:" in proc.stdout
    for command in COMMANDS:
        assert command in proc.stdout


def test_help_exits_zero(kit_dir):
    assert run_kit(kit_dir, "--help").returncode == 0


def test_missing_sdd_url_exit_2(kit_dir):
    proc = run_kit(kit_dir, "claim")
    assert proc.returncode == 2
    assert "SDD_URL ausente" in proc.stderr


def test_missing_sdd_token_exit_5(kit_dir, server):
    proc = run_kit(
        kit_dir,
        "claim",
        env_extra={"SDD_URL": f"http://127.0.0.1:{server.server_address[1]}"},
    )
    assert proc.returncode == 5
    assert "SDD_TOKEN ausente" in proc.stderr


def test_unknown_command_exit_2(kit_dir):
    assert run_kit(kit_dir, "bogus").returncode == 2


def test_unknown_command_writes_nothing_to_stdout(kit_dir):
    proc = run_kit(kit_dir, "bogus")
    assert proc.stdout.strip() == ""


def test_unreachable_server_exit_4(kit_dir):
    """Porta fechada: falha de rede -> exit 4 (contrato §11)."""
    proc = run_kit(
        kit_dir,
        "status",
        env_extra={
            "SDD_URL": "http://127.0.0.1:1",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
    )
    assert proc.returncode == 4
    assert is_json(proc.stdout)
    assert not is_json(proc.stderr)


# --- Contrato de código --------------------------------------------------------


def _import_roots(source):
    roots = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                roots.add(node.module.split(".")[0])
    return roots


def test_stdlib_only_imports():
    roots = _import_roots(KIT.read_text(encoding="utf-8"))
    assert roots <= ALLOWED_IMPORTS, f"import fora da lista da spec F8 §5.1: {roots - ALLOWED_IMPORTS}"
    stdlib = getattr(sys, "stdlib_module_names", None)
    if stdlib:
        assert all(name in stdlib or name == "__future__" for name in roots)


def test_kit_uses_only_contract_routes():
    source = KIT.read_text(encoding="utf-8")
    routes = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value.startswith("/api/"):
                routes.add(node.value)
    assert routes
    for route in routes:
        assert any(route.startswith(allowed) for allowed in ALLOWED_ROUTES), route


def test_exit_code_constants():
    source = KIT.read_text(encoding="utf-8")
    found = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in EXIT_CODES:
                found[name] = ast.literal_eval(node.value)
    assert found == EXIT_CODES


# --- claim --------------------------------------------------------------------


def test_claim_success_writes_state(kit_dir, server):
    server.routes[("POST", "/api/claims")] = (200, CLAIM_RESPONSE)
    proc = run_kit(
        kit_dir,
        "claim",
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
    )
    assert proc.returncode == 0, proc.stderr
    state = json.loads((kit_dir / "state.json").read_text(encoding="utf-8"))
    assert state == {
        "demand_id": "3f1c9a2e-5b74-4d68-9a10-7c2e5b8d9f31",
        "repo": "owner/name",
        "spec_ids": ["SPEC-002"],
        "br_id": "BR-013",
        "claimed_at": "2026-11-10T12:34:56Z",
    }


def test_output_is_json(kit_dir, server):
    server.routes[("POST", "/api/claims")] = (200, CLAIM_RESPONSE)
    proc = run_kit(
        kit_dir,
        "claim",
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == CLAIM_RESPONSE


def test_diagnostics_go_to_stderr(kit_dir, server):
    server.routes[("POST", "/api/claims")] = (409, {"error": {"code": "conflict", "message": "x", "detail": {}}})
    proc = run_kit(
        kit_dir,
        "claim",
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
    )
    assert proc.returncode == 3
    assert is_json(proc.stdout)
    assert not is_json(proc.stderr)
    assert proc.stderr.strip() != ""


def test_claim_conflict_exit_3(kit_dir, server):
    server.routes[("POST", "/api/claims")] = (409, {"error": {"code": "conflict", "message": "ja claimada", "detail": {}}})
    proc = run_kit(
        kit_dir,
        "claim",
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
    )
    assert proc.returncode == 3
    assert "sem demanda open para este repo" in proc.stderr
    assert not (kit_dir / "state.json").exists()


def test_claim_empty_exit_3(kit_dir, server):
    server.routes[("POST", "/api/claims")] = (404, {"error": {"code": "empty", "message": "fila vazia", "detail": {}}})
    proc = run_kit(
        kit_dir,
        "claim",
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
    )
    assert proc.returncode == 3
    assert not (kit_dir / "state.json").exists()


# --- sync / lint ---------------------------------------------------------------


def test_sync_conflict_exit_4(kit_dir, server):
    server.routes[("POST", "/api/artifacts/sync")] = (409, {"error": {"code": "conflict", "message": "divergente", "detail": {}}})
    proc = run_kit(
        kit_dir,
        "sync",
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
    )
    assert proc.returncode == 4


def test_sync_writes_no_file(kit_dir, server, tmp_path):
    server.routes[("POST", "/api/artifacts/sync")] = (200, {"ok": True})
    work = tmp_path / "work"
    (work / "docs" / "BR" / "login").mkdir(parents=True)
    (work / "docs" / "BR" / "login" / "login.md").write_text("# br\n", encoding="utf-8")
    proc = run_kit(
        kit_dir,
        "sync",
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
        cwd=work,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["sent"] == 1
    assert payload["documents"][0]["path"] == "docs/BR/login/login.md"
    assert payload["documents"][0]["sha256"] == hashlib.sha256(b"# br\n").hexdigest()


def test_lint_error_exit_1(kit_dir, server):
    server.routes[("POST", "/api/lint")] = (
        200,
        {
            "findings": [
                {
                    "rule": "BR-001",
                    "severity": "error",
                    "message": "frontmatter ausente",
                    "path": "docs/BR/login/login.md",
                    "line": 1,
                    "detail": {},
                }
            ],
            "summary": {"error": 1, "warning": 0},
        },
    )
    proc = run_kit(
        kit_dir,
        "lint",
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
    )
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["summary"]["error"] == 1


def test_lint_warning_exit_0(kit_dir, server):
    server.routes[("POST", "/api/lint")] = (
        200,
        {
            "findings": [
                {"rule": "BR-002", "severity": "warning", "message": "x", "path": "a.md", "line": 1, "detail": {}}
            ],
            "summary": {"error": 0, "warning": 1},
        },
    )
    proc = run_kit(
        kit_dir,
        "lint",
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
    )
    assert proc.returncode == 0


# --- review --------------------------------------------------------------------


REVIEWER_BLOCKING = """
import json

print(json.dumps({
    "verdict": "blocking",
    "findings": [
        {
            "severity": "blocking",
            "title": "AC sem cobertura",
            "detail": "AC-003 nao coberto",
            "ac": "AC-003",
            "suggestion": "cobrir AC-003",
        }
    ],
}))
"""


def test_review_blocking_exit_1(kit_dir, server):
    (kit_dir / "reviewer.py").write_text(REVIEWER_BLOCKING, encoding="utf-8")
    (kit_dir / "state.json").write_text(
        json.dumps({"demand_id": "3f1c9a2e-5b74-4d68-9a10-7c2e5b8d9f31"}), encoding="utf-8"
    )
    proc = run_kit(
        kit_dir,
        "review",
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
    )
    assert proc.returncode == 1
    assert json.loads(proc.stdout)["verdict"] == "blocking"


def test_review_missing_reviewer_exit_2(kit_dir, server):
    proc = run_kit(
        kit_dir,
        "review",
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
    )
    assert proc.returncode == 2
    assert "reviewer.py ausente" in proc.stderr


# --- dossier / pull / skill sync ----------------------------------------------


def test_dossier_without_demand_exit_3(kit_dir, server):
    proc = run_kit(
        kit_dir,
        "dossier",
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
    )
    assert proc.returncode == 3


def test_pull_writes_artifact_and_skips_traversal(kit_dir, server, tmp_path):
    server.routes[("GET", "/api/artifacts/pending")] = (
        200,
        {
            "artifacts": [
                {
                    "id": "BR-013",
                    "kind": "br",
                    "path": "docs/BR/login/login.md",
                    "status": "approved",
                    "content": "---\nid: BR-013\nstatus: draft\n---\n# Login\n",
                },
                {"id": "X", "kind": "br", "path": "../evil.md", "status": "approved", "content": "x"},
            ]
        },
    )
    work = tmp_path / "work"
    work.mkdir()
    proc = run_kit(
        kit_dir,
        "pull",
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
        cwd=work,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["written"] == ["docs/BR/login/login.md"]
    assert payload["skipped"] == ["../evil.md"]
    written = (work / "docs" / "BR" / "login" / "login.md").read_text(encoding="utf-8")
    assert "status: approved" in written
    assert not (work.parent / "evil.md").exists()


def test_skill_sync_writes_and_keeps_unchanged(kit_dir, server, tmp_path):
    content = "# Business Discovery\n"
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    server.routes[("GET", "/api/skills/manifest")] = (
        200,
        [
            {"id": "business-discovery", "version": "1.0.0", "hash": digest, "description": "d"},
            {"id": "technical-planning", "version": "1.0.0", "hash": digest, "description": "d"},
        ],
    )
    server.routes[("GET", "/api/skills/business-discovery")] = (200, content)
    server.routes[("GET", "/api/skills/technical-planning")] = (200, content)
    work = tmp_path / "work"
    work.mkdir()
    env = {
        "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
        "SDD_TOKEN": "sdd_test",
        "SDD_REPO": "owner/name",
    }
    proc = run_kit(kit_dir, "skill", "sync", env_extra=env, cwd=work)
    assert proc.returncode == 0, proc.stderr
    first = json.loads(proc.stdout)
    assert first["dest"] == ".claude/skills"
    assert sorted(first["updated"]) == ["business-discovery", "technical-planning"]
    assert (work / ".claude" / "skills" / "business-discovery" / "SKILL.md").exists()

    proc = run_kit(kit_dir, "skill", "sync", env_extra=env, cwd=work)
    assert proc.returncode == 0, proc.stderr
    second = json.loads(proc.stdout)
    assert second["updated"] == []
    assert sorted(second["unchanged"]) == ["business-discovery", "technical-planning"]


def test_status_returns_demand_and_events(kit_dir, server):
    server.routes[("GET", "/api/claims/current")] = (
        200,
        {"id": "3f1c9a2e-5b74-4d68-9a10-7c2e5b8d9f31", "status": "in_progress", "module": "login"},
    )
    server.routes[("GET", "/api/events")] = (
        200,
        {"events": [{"id": 41, "type": "claim", "at": "2026-11-10T12:34:56Z", "payload": {}}]},
    )
    proc = run_kit(
        kit_dir,
        "status",
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["demand"]["status"] == "in_progress"
    assert len(payload["events"]) == 1


def test_status_without_demand_exits_zero(kit_dir, server):
    server.routes[("GET", "/api/claims/current")] = (404, {"error": {"code": "empty", "message": "x", "detail": {}}})
    proc = run_kit(
        kit_dir,
        "status",
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == {"demand": None, "events": []}


def test_knowledge_returns_server_payload(kit_dir, server):
    hits = {
        "query": "quando criar um Output Port",
        "hits": [
            {
                "heading": "Output Port",
                "text": "...",
                "score": 4.1823,
                "source_kind": "method",
                "artifact_id": None,
                "demand_id": None,
                "corpus_id": "method",
            }
        ],
    }
    server.routes[("GET", "/api/knowledge")] = (200, hits)
    proc = run_kit(
        kit_dir,
        "knowledge",
        "quando criar um Output Port",
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == hits


def test_dossier_returns_server_payload(kit_dir, server):
    (kit_dir / "state.json").write_text(
        json.dumps({"demand_id": "3f1c9a2e-5b74-4d68-9a10-7c2e5b8d9f31"}), encoding="utf-8"
    )
    dossier = {"necessidade": {"br": [], "acs": []}, "proposta": {}, "implementacao": {}, "desvios": []}
    server.routes[("GET", "/api/knowledge/dossier/3f1c9a2e-5b74-4d68-9a10-7c2e5b8d9f31")] = (200, dossier)
    proc = run_kit(
        kit_dir,
        "dossier",
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == dossier


def test_report_registers_commit_and_review(kit_dir, server, tmp_path):
    (kit_dir / "state.json").write_text(
        json.dumps({"demand_id": "3f1c9a2e-5b74-4d68-9a10-7c2e5b8d9f31"}), encoding="utf-8"
    )
    work = tmp_path / "repo"
    work.mkdir()
    (work / "app.py").write_text("print('oi')\n", encoding="utf-8")
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "HOME": os.environ.get("HOME", ""),
        "GIT_AUTHOR_NAME": "Tester",
        "GIT_AUTHOR_EMAIL": "tester@example.com",
        "GIT_COMMITTER_NAME": "Tester",
        "GIT_COMMITTER_EMAIL": "tester@example.com",
    }
    subprocess.run(["git", "init", "-q"], cwd=work, env=env, check=True)
    subprocess.run(["git", "add", "app.py"], cwd=work, env=env, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Tester", "-c", "user.email=tester@example.com", "commit", "-q", "-m", "feat(login)"],
        cwd=work,
        env=env,
        check=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=work, env=env, capture_output=True, text=True, check=True
    ).stdout.strip()
    server.routes[("POST", "/api/commits")] = (200, {"id": "0a5f3c22", "sha": sha})
    server.routes[("POST", "/api/reviews")] = (200, {"id": "7b8c9d0e", "verdict": "pending", "findings": []})
    proc = run_kit(
        kit_dir,
        "report",
        sha,
        env_extra={
            "SDD_URL": f"http://127.0.0.1:{server.server_address[1]}",
            "SDD_TOKEN": "sdd_test",
            "SDD_REPO": "owner/name",
        },
        cwd=work,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["commit"]["sha"] == sha
    assert payload["review"]["verdict"] == "pending"
