"""Testes do gate de push da fase F9 (hook pre-push, instalador e reviewer).

Sem framework de mock pesado (Contrato Comum §1): pytest + `tmp_path` +
`subprocess` + scripts stub + um servidor HTTP em thread.

O kit (`kit/sdd.py`) e o Claude Code CLI (`claude`) são substituídos por stubs
que registram o que receberam; o `reviewer.py` e o hook são os reais.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_SOURCE = REPO_ROOT / "plugin" / "hooks" / "pre-push"
INSTALLER_SOURCE = REPO_ROOT / "plugin" / "hooks" / "install-hooks.sh"
REVIEWER_SOURCE = REPO_ROOT / "plugin" / "kit" / "reviewer.py"

ZERO_SHA = "0" * 40
REMOTE_URL = "https://example.com/acme/repo.git"
DEMAND_ID = "3f6c1c8e-5a2b-4d9f-9c11-8b7e2f0a4d61"
TOKEN = "sdd_teste_123"

GIT_ROOTS = (
    Path(r"C:\Program Files\Git"),
    Path(r"C:\Program Files (x86)\Git"),
)


def _git_candidate(*parts: str) -> Path | None:
    """Arquivo do Git for Windows (o git roda hooks com o `sh` dele)."""
    for root in GIT_ROOTS:
        candidate = root.joinpath(*parts)
        if candidate.is_file():
            return candidate
    return None


def _is_wsl_stub(path: str | Path) -> bool:
    """`C:\\WINDOWS\\system32\\bash.exe` e o stub do WSL: falha com
    `execvpe(/bin/bash) failed` quando o WSL nao esta instalado."""
    text = str(path).lower().replace("/", "\\")
    return text.endswith("\\bash.exe") and "\\system32\\" in text


def _find_bash() -> str | None:
    """Bash utilizavel: Git Bash primeiro; o `bash` do PATH so serve se nao for
    o stub do WSL."""
    candidate = _git_candidate("bin", "bash.exe") or _git_candidate("usr", "bin", "bash.exe")
    if candidate:
        return str(candidate)
    found = shutil.which("bash")
    if found and not _is_wsl_stub(found):
        return found
    return None


def _find_sh() -> str | None:
    """`sh` para rodar o hook (o git for Windows usa o `sh` do MSYS)."""
    candidate = _git_candidate("usr", "bin", "sh.exe") or _git_candidate("bin", "sh.exe")
    if candidate:
        return str(candidate)
    found = shutil.which("sh")
    if found and not _is_wsl_stub(found):
        return found
    return None


BASH = _find_bash()
SH = _find_sh()
GIT_USR_BIN = _git_candidate("usr", "bin")

requires_sh = pytest.mark.skipif(
    SH is None,
    reason="sem `sh` utilizavel (Git for Windows ausente e `sh` fora do PATH)",
)
requires_bash = pytest.mark.skipif(
    BASH is None,
    reason="sem `bash` utilizavel (Git for Windows ausente e o `bash` do PATH e o stub do WSL)",
)


# --------------------------------------------------------------------------- #
# Stubs
# --------------------------------------------------------------------------- #

BR_DOC = """---
id: BR-001
module: auth
feature: login
status: draft
createdBy: teste
createdFrom: null
version: 1.0.0
timestamp: 2026-11-10T12:00:00Z
---

# Contexto

Login com refresh token.
"""

SPEC_DOC = """---
id: SPEC-001
module: auth
status: draft
createdBy: teste
createdFrom: BR-001
version: 1.0.0
timestamp: 2026-11-10T12:00:00Z
technologyPack: python
doubtsIndex: null
---

# Especificação

O login renova o token expirado.
"""

KIT_STUB = '''\
"""Stub do kit SDD usado pelos testes do hook (F9)."""
import json
import os
import sys

log_path = os.environ.get("SDD_TEST_KIT_LOG", "")
command = sys.argv[1] if len(sys.argv) > 1 else ""
args = sys.argv[2:]

if log_path:
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"command": command, "args": args}, ensure_ascii=False) + "\\n")

if command == "lint":
    findings = json.loads(os.environ.get("SDD_TEST_LINT_FINDINGS", "[]"))
    payload = {
        "findings": findings,
        "summary": {
            "error": sum(1 for f in findings if f.get("severity") == "error"),
            "warning": sum(1 for f in findings if f.get("severity") == "warning"),
        },
    }
    print(json.dumps(payload, ensure_ascii=False))
    sys.exit(int(os.environ.get("SDD_TEST_LINT_EXIT", "0")))

print(json.dumps({}))
sys.exit(0)
'''

CLAUDE_STUB = '''\
"""Stub do Claude Code CLI usado pelos testes da F9."""
import json
import os
import sys
import time

try:
    # Bytes + UTF-8: o locale do console (cp1252) corromperia o prompt.
    received = sys.stdin.buffer.read().decode("utf-8", "replace")
except Exception:
    received = ""

prompt_file = os.environ.get("SDD_TEST_CLAUDE_PROMPT_FILE", "")
if prompt_file:
    try:
        with open(prompt_file, "w", encoding="utf-8") as handle:
            handle.write(received)
    except OSError:
        pass

mode = os.environ.get("SDD_TEST_CLAUDE_MODE", "result")
if mode == "sleep":
    time.sleep(float(os.environ.get("SDD_TEST_CLAUDE_SLEEP", "3")))
    sys.exit(0)
if mode == "garbage":
    sys.stdout.write("isto nao e json")
    sys.exit(0)

payload = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "result": os.environ.get("SDD_TEST_CLAUDE_RESULT", "[]"),
    "total_cost_usd": 0.0123,
}
sys.stdout.write(json.dumps(payload, ensure_ascii=False))
'''

# Formato real de `GET /api/demands/{id}` (F4): a demanda vem com `artifacts`
# e `events`; o conteudo da SPEC vem em `GET /api/artifacts/{id}`.
DEMAND = {
    "id": DEMAND_ID,
    "repo": "acme/repo",
    "module": "auth",
    "title": "Login com refresh token",
    "status": "in_progress",
    "artifacts": [
        {
            "id": "SPEC-001",
            "kind": "spec",
            "path": "docs/SPEC/auth/login.md",
            "status": "draft",
        },
    ],
    "events": [
        {
            "id": "ev-1",
            "type": "claimed",
            "payload": {},
            "actor": "tester",
            "at": "2026-11-10T12:00:00Z",
        },
    ],
}

ARTIFACTS = {
    "SPEC-001": {
        "id": "SPEC-001",
        "kind": "spec",
        "path": "docs/SPEC/auth/login.md",
        "status": "draft",
        "content": SPEC_DOC,
    },
}

DOSSIER = {
    "proposta": {
        "specs": [
            {"id": "SPEC-001", "path": "docs/SPEC/auth/login.md", "status": "draft"},
        ],
    },
    "necessidade": {
        "acs": [{"id": "AC-001", "title": "O login renova o token expirado"}],
    },
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} falhou: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _git_optional(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _path_for(bin_dir: Path | None = None, without_claude: bool = False) -> str:
    """PATH do processo filho, opcionalmente sem qualquer `claude` instalável.

    O `usr/bin` do Git entra na frente: e o que o git for Windows usa quando
    roda hooks (`dirname`, `printf` e ciavem dependem dele)."""
    entries: list[str] = []
    for part in os.environ.get("PATH", "").split(os.pathsep):
        if not part:
            continue
        folder = Path(part)
        if without_claude and any(
            (folder / f"claude{ext}").exists()
            for ext in (".exe", ".cmd", ".bat", ".com")
        ):
            continue
        entries.append(part)
    if GIT_USR_BIN is not None:
        entries.insert(0, str(GIT_USR_BIN))
    if bin_dir is not None:
        entries.insert(0, str(bin_dir))
    return os.pathsep.join(entries)


def _base_env(path: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PATH"] = path
    env["SDD_PYTHON"] = sys.executable
    return env


def _hook_env(
    kit: Path,
    api_url: str,
    token: str | None,
    path: str,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    env = _base_env(path)
    env["SDD_KIT_DIR"] = str(kit)
    env["SDD_URL"] = api_url
    if token:
        env["SDD_TOKEN"] = token
    else:
        env.pop("SDD_TOKEN", None)
    env.update(extra or {})
    return env


def _run_hook(
    repo: Path,
    env: dict[str, str],
    sha: str,
    remote_sha: str = ZERO_SHA,
    refs: str | None = None,
) -> SimpleNamespace:
    """Roda o hook instalado. Bytes crus no stdin: o git envia as refs com LF."""
    hook = repo / ".sdd" / "hooks" / "pre-push"
    stdin_text = refs if refs is not None else (
        f"refs/heads/feature {sha} refs/heads/feature {remote_sha}\n"
    )
    proc = subprocess.run(
        [SH, str(hook).replace("\\", "/"), "origin", REMOTE_URL],
        cwd=str(repo),
        input=stdin_text.encode("utf-8"),
        capture_output=True,
        env=env,
    )
    return SimpleNamespace(
        returncode=proc.returncode,
        stdout=proc.stdout.decode("utf-8", "replace"),
        stderr=proc.stderr.decode("utf-8", "replace"),
    )


def _run_reviewer(
    kit: Path,
    api_url: str,
    token: str,
    path: str,
    extra: dict[str, str] | None = None,
    sha: str = "deadbeef",
    repo_root: Path | None = None,
) -> subprocess.CompletedProcess:
    env = _base_env(path)
    env["SDD_URL"] = api_url
    env["SDD_TOKEN"] = token
    env.update(extra or {})
    command = [
        sys.executable,
        str(kit / "reviewer.py").replace("\\", "/"),
        "--demand", DEMAND_ID,
        "--sha", sha,
        "--json",
    ]
    if repo_root is not None:
        command += ["--repo-root", str(repo_root)]
    return subprocess.run(
        command,
        cwd=str(kit),
        capture_output=True,
        text=True,
        env=env,
    )


def _read_calls(log: Path) -> list[dict[str, Any]]:
    if not log.exists():
        return []
    return [
        json.loads(line)
        for line in log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_state(kit: Path) -> None:
    (kit / "state.json").write_text(
        json.dumps(
            {
                "demand_id": DEMAND_ID,
                "demand": {
                    "id": DEMAND_ID,
                    "title": "Login com refresh token",
                    "module": "auth",
                    "status": "in_progress",
                    "repo": "acme/repo",
                },
                "repo": "acme/repo",
                "branch": "feature",
                "updated_at": "2026-11-10T12:00:00Z",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _install(repo: Path) -> subprocess.CompletedProcess:
    assert BASH is not None
    return subprocess.run(
        [BASH, str(INSTALLER_SOURCE).replace("\\", "/")],
        cwd=str(repo),
        capture_output=True,
        text=True,
        env=_base_env(_path_for()),
    )


# --------------------------------------------------------------------------- #
# Servidor HTTP stub
# --------------------------------------------------------------------------- #

class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:
        """Silencia o log do http.server."""

    def _read_body(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except ValueError:
            return raw.decode("utf-8", "replace")

    def _respond(self, code: int, payload: Any) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802 - nome imposto pelo BaseHTTPRequestHandler
        if self.path.startswith("/api/knowledge/dossier/"):
            self._respond(200, self.server.dossier)  # type: ignore[attr-defined]
        elif self.path.startswith("/api/demands/"):
            self._respond(200, self.server.demand)  # type: ignore[attr-defined]
        elif self.path.startswith("/api/artifacts/"):
            artifact_id = self.path.rsplit("/", 1)[-1]
            artifact = self.server.artifacts.get(artifact_id)  # type: ignore[attr-defined]
            if artifact is None:
                self._respond(404, {"error": {"code": "not_found"}})
            else:
                self._respond(200, artifact)
        else:
            self._respond(404, {"error": {"code": "not_found"}})

    def do_POST(self) -> None:  # noqa: N802 - nome imposto pelo BaseHTTPRequestHandler
        body = self._read_body()
        self.server.requests.append(  # type: ignore[attr-defined]
            {
                "path": self.path,
                "body": body,
                "authorization": self.headers.get("Authorization"),
            }
        )
        self._respond(200, {"id": "stub"})


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.requests: list[dict[str, Any]] = []
        self.dossier: dict[str, Any] = json.loads(json.dumps(DOSSIER))
        self.demand: dict[str, Any] = json.loads(json.dumps(DEMAND))
        self.artifacts: dict[str, Any] = json.loads(json.dumps(ARTIFACTS))


@pytest.fixture
def api_server() -> Any:
    server = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _api_url(server: Any) -> str:
    return f"http://127.0.0.1:{server.server_address[1]}/api"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def git_repo(tmp_path: Path) -> SimpleNamespace:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "f9@test.local")
    _git(repo, "config", "user.name", "F9 Test")
    _git(repo, "config", "commit.gpgsign", "false")

    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "base")
    base_sha = _git(repo, "rev-parse", "HEAD")

    br = repo / "docs" / "BR" / "auth"
    spec = repo / "docs" / "SPEC" / "auth"
    br.mkdir(parents=True)
    spec.mkdir(parents=True)
    (br / "login.md").write_text(BR_DOC, encoding="utf-8")
    (spec / "login.md").write_text(SPEC_DOC, encoding="utf-8")
    _git(repo, "add", "docs")
    _git(repo, "commit", "-m", "artefatos")
    tip_sha = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", "-b", "feature")
    (spec / "login.md").write_text(SPEC_DOC + "\nlinha nova\n", encoding="utf-8")
    _git(repo, "commit", "-am", "ajuste")
    feature_sha = _git(repo, "rev-parse", "HEAD")

    _git(repo, "checkout", "main")
    _git(repo, "remote", "add", "origin", REMOTE_URL)

    return SimpleNamespace(root=repo, base=base_sha, tip=tip_sha, feature=feature_sha)


@pytest.fixture
def kit_dir(tmp_path: Path) -> Path:
    kit = tmp_path / "kit"
    kit.mkdir()
    shutil.copy(REVIEWER_SOURCE, kit / "reviewer.py")
    (kit / "sdd.py").write_text(KIT_STUB, encoding="utf-8")
    return kit


@pytest.fixture
def claude_bin(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "claude-bin"
    bin_dir.mkdir()
    script = bin_dir / "claude_stub.py"
    script.write_text(CLAUDE_STUB, encoding="utf-8")
    if os.name == "nt":
        (bin_dir / "claude.CMD").write_text(
            f'@echo off\r\n"{sys.executable}" "{script}"\r\n', encoding="utf-8"
        )
    else:
        stub = bin_dir / "claude"
        stub.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{script}"\n', encoding="utf-8"
        )
        stub.chmod(0o755)
    return bin_dir


@pytest.fixture
def reviewer() -> Any:
    spec = importlib.util.spec_from_file_location("sdd_f9_reviewer", REVIEWER_SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# Hook
# --------------------------------------------------------------------------- #

@requires_sh
def test_hook_without_token_exits_zero(
    git_repo: SimpleNamespace, kit_dir: Path, api_server: Any
) -> None:
    _install(git_repo.root)
    env = _hook_env(
        kit_dir, _api_url(api_server), None, _path_for(without_claude=True)
    )
    proc = _run_hook(git_repo.root, env, git_repo.feature)

    assert proc.returncode == 0, proc.stderr
    assert "token" in proc.stderr.lower()
    assert api_server.requests == []


@requires_sh
def test_hook_without_demand_runs_lint_only(
    git_repo: SimpleNamespace, kit_dir: Path, api_server: Any, tmp_path: Path
) -> None:
    _install(git_repo.root)
    log = tmp_path / "kit-calls.jsonl"
    env = _hook_env(
        kit_dir,
        _api_url(api_server),
        TOKEN,
        _path_for(without_claude=True),
        {"SDD_TEST_KIT_LOG": str(log)},
    )
    proc = _run_hook(git_repo.root, env, git_repo.feature)

    assert proc.returncode == 0, proc.stderr
    calls = _read_calls(log)
    assert [call["command"] for call in calls] == ["lint"]
    assert api_server.requests == []


@requires_sh
def test_hook_blocking_verdict_aborts_push(
    git_repo: SimpleNamespace, kit_dir: Path, api_server: Any, claude_bin: Path
) -> None:
    _install(git_repo.root)
    _write_state(kit_dir)
    findings = [
        {
            "severity": "blocking",
            "title": "SPEC violada",
            "detail": "refresh token nao implementado",
            "ac": "AC-001",
            "suggestion": None,
        }
    ]
    env = _hook_env(
        kit_dir,
        _api_url(api_server),
        TOKEN,
        _path_for(claude_bin),
        {"SDD_TEST_CLAUDE_RESULT": json.dumps(findings)},
    )
    proc = _run_hook(git_repo.root, env, git_repo.feature)

    assert proc.returncode == 1, proc.stderr
    assert "SPEC violada" in proc.stderr
    reviews = [r for r in api_server.requests if r["path"] == "/api/reviews"]
    assert len(reviews) == 1
    assert reviews[0]["body"]["verdict"] == "blocking"
    assert reviews[0]["body"]["sha"] == git_repo.feature
    assert reviews[0]["body"]["findings"][0]["severity"] == "blocking"


@requires_sh
def test_hook_with_suggestions_passes(
    git_repo: SimpleNamespace, kit_dir: Path, api_server: Any, claude_bin: Path
) -> None:
    _install(git_repo.root)
    _write_state(kit_dir)
    findings = [
        {
            "severity": "suggestion",
            "title": "Nome de variavel",
            "detail": "estilo",
            "ac": None,
            "suggestion": "renomear",
        }
    ]
    env = _hook_env(
        kit_dir,
        _api_url(api_server),
        TOKEN,
        _path_for(claude_bin),
        {"SDD_TEST_CLAUDE_RESULT": json.dumps(findings)},
    )
    proc = _run_hook(git_repo.root, env, git_repo.feature)

    assert proc.returncode == 0, proc.stderr
    reviews = [r for r in api_server.requests if r["path"] == "/api/reviews"]
    assert len(reviews) == 1
    assert reviews[0]["body"]["verdict"] == "suggestions"
    assert reviews[0]["body"]["findings"][0]["title"] == "Nome de variavel"


@requires_sh
def test_hook_llm_unavailable_yields_pending(
    git_repo: SimpleNamespace, kit_dir: Path, api_server: Any
) -> None:
    _install(git_repo.root)
    _write_state(kit_dir)
    env = _hook_env(
        kit_dir, _api_url(api_server), TOKEN, _path_for(without_claude=True)
    )
    proc = _run_hook(git_repo.root, env, git_repo.feature)

    assert proc.returncode == 0, proc.stderr
    reviews = [r for r in api_server.requests if r["path"] == "/api/reviews"]
    assert len(reviews) == 1
    assert reviews[0]["body"]["verdict"] == "pending"


@requires_sh
def test_hook_lint_error_aborts_push(
    git_repo: SimpleNamespace, kit_dir: Path, api_server: Any, tmp_path: Path
) -> None:
    _install(git_repo.root)
    log = tmp_path / "kit-calls.jsonl"
    findings = [
        {
            "rule": "BR-001",
            "severity": "error",
            "message": "frontmatter incompleto",
            "path": "docs/BR/auth/login.md",
            "line": 1,
        }
    ]
    env = _hook_env(
        kit_dir,
        _api_url(api_server),
        TOKEN,
        _path_for(without_claude=True),
        {
            "SDD_TEST_KIT_LOG": str(log),
            "SDD_TEST_LINT_FINDINGS": json.dumps(findings),
            "SDD_TEST_LINT_EXIT": "1",
        },
    )
    proc = _run_hook(git_repo.root, env, git_repo.feature)

    assert proc.returncode == 1, proc.stderr
    assert "BR-001" in proc.stderr


@requires_sh
def test_hook_reads_refs_from_stdin(
    git_repo: SimpleNamespace, kit_dir: Path, api_server: Any, tmp_path: Path
) -> None:
    _install(git_repo.root)
    _write_state(kit_dir)
    log = tmp_path / "kit-calls.jsonl"
    env = _hook_env(
        kit_dir,
        _api_url(api_server),
        TOKEN,
        _path_for(without_claude=True),
        {"SDD_TEST_KIT_LOG": str(log)},
    )
    refs = (
        f"refs/heads/main {git_repo.tip} refs/heads/main {git_repo.tip}\n"
        f"refs/heads/feature {git_repo.feature} refs/heads/feature {ZERO_SHA}\n"
    )
    proc = _run_hook(git_repo.root, env, git_repo.feature, refs=refs)

    assert proc.returncode == 0, proc.stderr
    calls = _read_calls(log)
    report = [call for call in calls if call["command"] == "report"]
    assert len(report) == 1
    assert report[0]["args"] == [git_repo.feature]
    assert git_repo.feature != git_repo.tip  # o sha vem do stdin, nao do HEAD


@requires_sh
def test_hook_tolerates_crlf_refs(
    git_repo: SimpleNamespace, kit_dir: Path, api_server: Any, tmp_path: Path
) -> None:
    """Refs com CRLF nao podem corromper o sha (branch nova x branch existente)."""
    _install(git_repo.root)
    log = tmp_path / "kit-calls.jsonl"
    env = _hook_env(
        kit_dir,
        _api_url(api_server),
        TOKEN,
        _path_for(without_claude=True),
        {"SDD_TEST_KIT_LOG": str(log)},
    )
    refs = f"refs/heads/feature {git_repo.feature} refs/heads/feature {ZERO_SHA}\r\n"
    proc = _run_hook(git_repo.root, env, git_repo.feature, refs=refs)

    assert proc.returncode == 0, proc.stderr
    calls = _read_calls(log)
    assert [call["command"] for call in calls] == ["lint"]


# --------------------------------------------------------------------------- #
# Instalador
# --------------------------------------------------------------------------- #

@requires_bash
def test_install_hooks_configures_core_hookspath(git_repo: SimpleNamespace) -> None:
    proc = _install(git_repo.root)
    assert proc.returncode == 0, proc.stderr

    assert _git(git_repo.root, "config", "--local", "core.hooksPath") == ".sdd/hooks"
    hook = git_repo.root / ".sdd" / "hooks" / "pre-push"
    assert hook.is_file()
    assert os.access(hook, os.X_OK)
    assert _git_optional("config", "--global", "--get", "core.hooksPath") != ".sdd/hooks"


@requires_bash
def test_install_hooks_is_idempotent(git_repo: SimpleNamespace) -> None:
    first = _install(git_repo.root)
    hook = git_repo.root / ".sdd" / "hooks" / "pre-push"
    content = hook.read_text(encoding="utf-8")

    second = _install(git_repo.root)

    assert first.returncode == 0 and second.returncode == 0
    assert _git(git_repo.root, "config", "--local", "core.hooksPath") == ".sdd/hooks"
    assert hook.read_text(encoding="utf-8") == content


# --------------------------------------------------------------------------- #
# Reviewer
# --------------------------------------------------------------------------- #

def test_reviewer_parses_json_with_fence(reviewer: Any) -> None:
    payload = [
        {
            "severity": "blocking",
            "title": "achado",
            "detail": "detalhe",
            "ac": "AC-001",
            "suggestion": None,
        }
    ]
    fenced = "```json\n" + json.dumps(payload) + "\n```"

    findings = reviewer.parse_findings(fenced)

    assert len(findings) == 1
    assert findings[0]["severity"] == "blocking"
    assert findings[0]["ac"] == "AC-001"


def test_reviewer_parses_json_without_fence(reviewer: Any) -> None:
    payload = [
        {
            "severity": "blocking",
            "title": "achado",
            "detail": "detalhe",
            "ac": "AC-001",
            "suggestion": None,
        }
    ]
    fenced = "```json\n" + json.dumps(payload) + "\n```"

    findings = reviewer.parse_findings(json.dumps(payload))

    assert findings == reviewer.parse_findings(fenced)
    assert findings[0]["title"] == "achado"


def test_reviewer_missing_claude_returns_pending(reviewer: Any, monkeypatch: Any) -> None:
    monkeypatch.setattr(reviewer.shutil, "which", lambda name: None)

    result = reviewer.review({"id": DEMAND_ID}, "abc123", "diff", "spec", ["AC-001"])

    assert result["verdict"] == "pending"
    assert result["llm_available"] is False


def test_reviewer_timeout_returns_pending(
    kit_dir: Path, api_server: Any, claude_bin: Path
) -> None:
    proc = _run_reviewer(
        kit_dir,
        _api_url(api_server),
        TOKEN,
        _path_for(claude_bin),
        {"SDD_REVIEW_TIMEOUT": "1", "SDD_TEST_CLAUDE_MODE": "sleep",
         "SDD_TEST_CLAUDE_SLEEP": "3"},
    )

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip())["verdict"] == "pending"


def test_reviewer_unparseable_response_yields_pending(
    kit_dir: Path, api_server: Any, claude_bin: Path
) -> None:
    proc = _run_reviewer(
        kit_dir,
        _api_url(api_server),
        TOKEN,
        _path_for(claude_bin),
        {"SDD_TEST_CLAUDE_MODE": "garbage"},
    )

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout.strip())["verdict"] == "pending"


def test_reviewer_posts_review_with_contract_shape(
    kit_dir: Path, api_server: Any, claude_bin: Path
) -> None:
    findings = [
        {
            "severity": "suggestion",
            "title": "estilo",
            "detail": "detalhe",
            "ac": "AC-001",
            "suggestion": "ajuste",
        }
    ]
    proc = _run_reviewer(
        kit_dir,
        _api_url(api_server),
        TOKEN,
        _path_for(claude_bin),
        {"SDD_TEST_CLAUDE_RESULT": json.dumps(findings)},
        sha="abc1234",
    )

    assert proc.returncode == 0, proc.stderr
    reviews = [r for r in api_server.requests if r["path"] == "/api/reviews"]
    assert len(reviews) == 1
    body = reviews[0]["body"]
    assert body["sha"] == "abc1234"
    assert body["verdict"] == "suggestions"
    assert body["findings"][0]["severity"] == "suggestion"
    assert reviews[0]["authorization"] == f"Bearer {TOKEN}"


def test_reviewer_prompt_carries_spec_and_diff(
    git_repo: SimpleNamespace,
    kit_dir: Path,
    api_server: Any,
    claude_bin: Path,
    tmp_path: Path,
) -> None:
    """O prompt leva o id da SPEC (via `artifacts` da demanda) e o diff do sha."""
    prompt_file = tmp_path / "prompt.txt"
    proc = _run_reviewer(
        kit_dir,
        _api_url(api_server),
        TOKEN,
        _path_for(claude_bin),
        {"SDD_TEST_CLAUDE_PROMPT_FILE": str(prompt_file)},
        sha=git_repo.feature,
        repo_root=git_repo.root,
    )

    assert proc.returncode == 0, proc.stderr
    prompt = prompt_file.read_text(encoding="utf-8")
    assert "SPEC-001" in prompt
    assert "AC-001" in prompt
    assert "diff --git" in prompt
    assert "linha nova" in prompt


# --------------------------------------------------------------------------- #
# Requisito sobre o kit do F8 (ainda nao existe neste worktree)
# --------------------------------------------------------------------------- #

@pytest.mark.skip(reason="F8 pendente")
def test_kit_review_delegates_to_reviewer() -> None:
    kit = REPO_ROOT / "plugin" / "kit" / "sdd.py"
    assert kit.is_file()
    assert "reviewer" in kit.read_text(encoding="utf-8")
