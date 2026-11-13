#!/usr/bin/env python3
"""Motor de review do kit SDD — fase F9.

Compara o diff do commit com a SPEC da demanda corrente usando o Claude Code CLI
(`claude -p`) e registra o veredito em `POST /api/reviews`.

Contrato (spec F9 §3.3):
  * stdlib apenas, sem `pip install`;
  * JSON em stdout, diagnóstico em stderr;
  * exit codes: 0 ok (clean/suggestions/pending) | 1 blocking | 2 erro de uso |
    3 sem demanda | 4 falha de sync | 5 auth;
  * só `blocking` bloqueia o push — falha de infraestrutura passa (design master §19).

É o mesmo módulo que `kit/sdd.py review` (F8) consome, para que hook e agente
nunca produzam vereditos divergentes.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

EXIT_OK = 0
EXIT_BLOCKING = 1
EXIT_USAGE = 2
EXIT_NO_DEMAND = 3
EXIT_SYNC_FAILED = 4
EXIT_AUTH = 5

DIFF_MAX_CHARS = 120_000
DIFF_MAX_LINES = 2_000
SPEC_MAX_CHARS = 60_000
DEFAULT_TIMEOUT = 120
HTTP_TIMEOUT = 30

CLAUDE_ARGS = [
    "-p",
    "--output-format", "json",
    "--permission-mode", "dontAsk",
    "--no-session-persistence",
    "--allowedTools", "",
    "--tools", "",
    "--max-turns", "1",
    "--strict-mcp-config",
]

PROMPT_TEMPLATE = """Você é o revisor de código de uma demanda Spec-Driven. Compare o DIFF com a SPEC e
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
{spec}

=== ACCEPTANCE CRITERIA ===
{acs}

=== DIFF ===
{diff}"""


class TransportError(Exception):
    """Servidor inacessível (rede, DNS, timeout, corpo não-JSON)."""


def _warn(message: str) -> None:
    print(f"[sdd] {message}", file=sys.stderr)


def _emit(result: dict) -> None:
    print(json.dumps(result, ensure_ascii=False))


# --------------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------------- #

def _truncate(text: str, max_chars: int, max_lines: int | None = None) -> tuple[str, bool]:
    """Corta o texto no primeiro limite atingido. Devolve (texto, truncou)."""
    truncated = False
    if max_lines is not None:
        lines = text.split("\n")
        if len(lines) > max_lines:
            text = "\n".join(lines[:max_lines])
            truncated = True
    if len(text) > max_chars:
        text = text[:max_chars]
        truncated = True
    return text, truncated


def _render_ac(ac: object) -> str:
    """Formata um AC como linha `- <id>: <texto>`."""
    if isinstance(ac, dict):
        ac_id = str(ac.get("id") or "").strip()
        title = str(ac.get("title") or "").strip()
        line = f"{ac_id}: {title}" if title else ac_id
    else:
        line = str(ac or "").strip()
    if not line:
        return ""
    return line if line.startswith("- ") else f"- {line}"


def build_prompt(spec_text: str, acs: list[str], diff_text: str) -> str:
    """Monta o prompt do revisor, anotando qualquer truncamento."""
    spec, spec_cut = _truncate(spec_text or "", SPEC_MAX_CHARS)
    diff, diff_cut = _truncate(diff_text or "", DIFF_MAX_CHARS, DIFF_MAX_LINES)
    if spec_cut:
        spec = spec + "\n[spec truncado]"
    if diff_cut:
        diff = diff + "\n[diff truncado]"
    rendered = "\n".join(line for line in (_render_ac(ac) for ac in acs or []) if line)
    return (
        PROMPT_TEMPLATE
        .replace("{spec}", spec)
        .replace("{acs}", rendered)
        .replace("{diff}", diff)
    )


# --------------------------------------------------------------------------- #
# Parse tolerante da resposta do LLM
# --------------------------------------------------------------------------- #

def _strip_fence(text: str) -> str:
    """Extrai o conteúdo entre cercas ``` quando existirem."""
    start = text.find("```")
    if start < 0:
        return text
    newline = text.find("\n", start)
    if newline < 0:
        return text
    end = text.find("```", newline)
    if end < 0:
        return text
    return text[newline + 1:end]


def _balanced(text: str, open_ch: str, close_ch: str) -> str | None:
    """Devolve o trecho entre o primeiro `open_ch` e o `close_ch` que o fecha."""
    start = text.find(open_ch)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == open_ch:
            depth += 1
        elif char == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _normalize(finding: dict) -> dict:
    """Normaliza um achado no formato do Contrato Comum §7.4."""
    severity = finding.get("severity")
    if severity not in ("blocking", "suggestion"):
        severity = "suggestion"
    ac = finding.get("ac")
    if not isinstance(ac, str) or not ac.strip():
        ac = None
    def _text(key: str) -> str:
        value = finding.get(key)
        return value if isinstance(value, str) else ""
    return {
        "severity": severity,
        "title": _text("title"),
        "detail": _text("detail"),
        "ac": ac,
        "suggestion": _text("suggestion"),
    }


def _parse_raw(raw: str) -> tuple[list[dict], bool]:
    """Devolve (achados, resposta_parseavel)."""
    text = _strip_fence(raw or "")
    blob = _balanced(text, "[", "]")
    if blob:
        try:
            data = json.loads(blob)
        except ValueError:
            data = None
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)], True
    found: list[dict] = []
    cursor = 0
    while True:
        start = text.find("{", cursor)
        if start < 0:
            break
        blob = _balanced(text[start:], "{", "}")
        if not blob:
            break
        try:
            item = json.loads(blob)
        except ValueError:
            item = None
        if isinstance(item, dict):
            found.append(item)
        cursor = start + 1
    if found:
        return found, True
    return [], False


def parse_findings(raw: str) -> list[dict]:
    """Achados da resposta do LLM, normalizados (lista vazia se não parseável)."""
    findings, _ = _parse_raw(raw)
    return [_normalize(item) for item in findings]


def decide(findings: list[dict]) -> str:
    """`blocking` > `suggestions` > `clean`."""
    items = [f for f in (findings or []) if isinstance(f, dict)]
    if any(f.get("severity") == "blocking" for f in items):
        return "blocking"
    if items:
        return "suggestions"
    return "clean"


# --------------------------------------------------------------------------- #
# Claude Code CLI
# --------------------------------------------------------------------------- #

def _timeout() -> int:
    raw = os.environ.get("SDD_REVIEW_TIMEOUT", "").strip()
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_TIMEOUT
    return value if value > 0 else DEFAULT_TIMEOUT


def call_claude(prompt: str, timeout: int) -> tuple[str | None, float, bool]:
    """Chama `claude -p` com o prompt em stdin.

    Devolve (texto, custo_usd, llm_disponivel)."""
    exe = shutil.which("claude")
    if not exe:
        _warn("Claude Code indisponível (claude não está no PATH) — revisão ignorada.")
        return None, 0.0, False
    command = [exe] + CLAUDE_ARGS
    model = os.environ.get("SDD_LLM_MODEL", "").strip()
    if model:
        command += ["--model", model]
    if exe.lower().endswith((".cmd", ".bat")):
        command = ["cmd", "/c"] + command
    try:
        proc = subprocess.run(
            command,
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        _warn(f"revisão expirou após {timeout}s — veredito pending, push liberado.")
        return None, 0.0, False
    except OSError as exc:
        _warn(f"Claude Code indisponível ({exc}) — revisão ignorada.")
        return None, 0.0, False
    if proc.returncode != 0:
        _warn(f"claude -p falhou (exit {proc.returncode}) — revisão ignorada.")
        return None, 0.0, False
    try:
        payload = json.loads(proc.stdout or "")
    except ValueError:
        _warn("resposta do claude -p não é JSON — revisão ignorada.")
        return None, 0.0, False
    if not isinstance(payload, dict):
        _warn("resposta do claude -p inesperado — revisão ignorada.")
        return None, 0.0, False
    if payload.get("is_error"):
        _warn("claude -p retornou is_error — revisão ignorada.")
        return None, 0.0, False
    text = payload.get("result")
    if not isinstance(text, str):
        text = ""
    try:
        cost = float(payload.get("total_cost_usd") or 0.0)
    except (TypeError, ValueError):
        cost = 0.0
    return text, cost, True


# --------------------------------------------------------------------------- #
# HTTP (stdlib)
# --------------------------------------------------------------------------- #

def _http(
    method: str,
    path: str,
    payload: dict | None = None,
    base_url: str = "",
    token: str = "",
    timeout: int = HTTP_TIMEOUT,
) -> tuple[int, object]:
    """Chama a API do servidor. Levanta TransportError em falha de rede."""
    url = base_url.rstrip("/") + path
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return response.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = None
        return exc.code, body
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise TransportError(str(exc)) from exc


# --------------------------------------------------------------------------- #
# Git
# --------------------------------------------------------------------------- #

def _git(repo_root: str, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", "-C", repo_root, *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return proc.returncode, proc.stdout.strip()


def _git_head(repo_root: str) -> str:
    code, out = _git(repo_root, "rev-parse", "HEAD")
    return out if code == 0 else ""


def _git_base(repo_root: str, sha: str) -> str:
    """Base do diff: merge-base com origin/HEAD ou o primeiro pai."""
    code, out = _git(repo_root, "merge-base", sha, "refs/remotes/origin/HEAD")
    if code == 0 and out:
        return out
    code, out = _git(repo_root, "rev-parse", "--verify", f"{sha}^")
    return out if code == 0 else ""


def _git_diff(repo_root: str, sha: str) -> str:
    base = _git_base(repo_root, sha)
    if base:
        code, out = _git(repo_root, "diff", "--no-color", f"{base}..{sha}")
    else:
        code, out = _git(repo_root, "show", "--no-color", "--format=", sha)
    return out if code == 0 else ""


# --------------------------------------------------------------------------- #
# Estado do kit
# --------------------------------------------------------------------------- #

def _kit_dir() -> Path:
    return Path(__file__).resolve().parent


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _base_url() -> str:
    """URL base da API: sem barra final e sem o sufixo `/api`.

    O kit (F8) normaliza o `SDD_URL` removendo o `/api` final; o reviewer faz o
    mesmo porque consome `SDD_URL` direto do ambiente.
    """
    raw = (os.environ.get("SDD_URL") or "").strip().rstrip("/")
    if raw.lower().endswith("/api"):
        raw = raw[: -len("/api")]
    return raw


def _resolve_token() -> str:
    token = (os.environ.get("SDD_TOKEN") or "").strip()
    if token:
        return token
    config = _read_json(_kit_dir() / "config.local.json")
    for key in ("token", "sdd_token"):
        value = config.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


# --------------------------------------------------------------------------- #
# SPEC / ACs
# --------------------------------------------------------------------------- #

def _collect_specs(
    specs: list, base_url: str, token: str
) -> str:
    """Conteúdo markdown das SPECs da demanda (busca o conteúdo se necessário)."""
    chunks: list[str] = []
    for spec in specs or []:
        if not isinstance(spec, dict):
            continue
        content = spec.get("content")
        spec_id = str(spec.get("id") or "").strip()
        if not isinstance(content, str) or not content.strip():
            if not spec_id:
                continue
            try:
                status, body = _http(
                    "GET",
                    f"/api/artifacts/{urllib.parse.quote(spec_id)}",
                    base_url=base_url,
                    token=token,
                )
            except TransportError as exc:
                _warn(f"SPEC {spec_id} indisponível ({exc}).")
                continue
            if status >= 400 or not isinstance(body, dict):
                _warn(f"SPEC {spec_id} indisponível (HTTP {status}).")
                continue
            content = body.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
        chunks.append(f"# {spec_id or 'SPEC'}\n{content}")
    return "\n\n".join(chunks)


def _collect_acs(acs: list) -> list[str]:
    result: list[str] = []
    for ac in acs or []:
        if isinstance(ac, dict):
            ac_id = str(ac.get("id") or "").strip()
            title = str(ac.get("title") or "").strip()
            if not ac_id:
                continue
            result.append(f"{ac_id}: {title}" if title else ac_id)
        elif isinstance(ac, str) and ac.strip():
            result.append(ac.strip())
    return result


# --------------------------------------------------------------------------- #
# Review
# --------------------------------------------------------------------------- #

def review(
    demand: dict,
    sha: str,
    diff_text: str,
    spec_text: str,
    acs: list[str],
) -> dict:
    """Roda o LLM, decide o veredito e devolve o resultado do review."""
    prompt = build_prompt(spec_text, acs, diff_text)
    text, cost, available = call_claude(prompt, _timeout())
    spec_found = bool((spec_text or "").strip())
    if not available:
        return {
            "verdict": "pending",
            "findings": [],
            "llm_available": False,
            "cost_usd": cost,
            "spec_found": spec_found,
        }
    findings, parsed = _parse_raw(text or "")
    if not parsed:
        _warn("resposta do claude -p sem JSON parseável — revisão ignorada.")
        return {
            "verdict": "pending",
            "findings": [],
            "llm_available": False,
            "cost_usd": cost,
            "spec_found": spec_found,
        }
    normalized = [_normalize(item) for item in findings]
    _, diff_cut = _truncate(diff_text or "", DIFF_MAX_CHARS, DIFF_MAX_LINES)
    _, spec_cut = _truncate(spec_text or "", SPEC_MAX_CHARS)
    if diff_cut or spec_cut:
        normalized.append({
            "severity": "suggestion",
            "title": "diff truncado" if diff_cut else "spec truncada",
            "detail": (
                "O diff foi cortado antes do envio ao revisor "
                f"(limite de {DIFF_MAX_CHARS} caracteres / {DIFF_MAX_LINES} linhas)."
                if diff_cut else
                f"A SPEC foi cortada antes do envio ao revisor (limite de {SPEC_MAX_CHARS} caracteres)."
            ),
            "ac": None,
            "suggestion": "Revisar manualmente o trecho que não foi enviado.",
        })
    return {
        "verdict": decide(normalized),
        "findings": normalized,
        "llm_available": True,
        "cost_usd": cost,
        "spec_found": spec_found,
    }


def _pending(spec_found: bool = False, cost: float = 0.0) -> dict:
    return {
        "verdict": "pending",
        "findings": [],
        "llm_available": False,
        "cost_usd": cost,
        "spec_found": spec_found,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reviewer.py",
        description="Revisa o diff de um commit contra a SPEC da demanda corrente.",
    )
    parser.add_argument("--demand", help="id da demanda corrente")
    parser.add_argument("--sha", help="sha local sendo enviado")
    parser.add_argument("--repo", help="owner/name do repositório")
    parser.add_argument("--repo-root", dest="repo_root", help="raiz do repositório git")
    parser.add_argument("--json", action="store_true", help="imprime o JSON de resultado (padrão)")
    return parser


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)

    demand_id = (args.demand or "").strip()
    if not demand_id:
        _warn("--demand é obrigatório")
        return EXIT_USAGE

    base_url = _base_url()
    if not base_url:
        _warn("SDD_URL ausente")
        return EXIT_USAGE

    token = _resolve_token()
    if not token:
        _warn("SDD_TOKEN ausente")
        return EXIT_AUTH

    repo_root = args.repo_root or os.getcwd()
    sha = (args.sha or "").strip() or _git_head(repo_root)
    if not sha:
        _warn("sha não identificável")
        return EXIT_USAGE

    # --- SPEC e ACs da demanda (dossiê do F7) ------------------------------ #
    try:
        status, dossier = _http(
            "GET",
            f"/api/knowledge/dossier/{urllib.parse.quote(demand_id)}",
            base_url=base_url,
            token=token,
        )
    except TransportError as exc:
        _warn(f"servidor indisponível ({exc}) — revisão ignorada.")
        _emit(_pending())
        return EXIT_OK

    if status == 404:
        _warn("demanda inexistente no servidor — revisão ignorada.")
        return EXIT_NO_DEMAND
    if status in (401, 403):
        _warn(f"sem permissão para ler o dossiê (HTTP {status}) — revisão ignorada.")
        return EXIT_AUTH
    if status >= 400:
        _warn(f"dossiê indisponível (HTTP {status}) — revisão ignorada.")
        _emit(_pending())
        return EXIT_OK

    if not isinstance(dossier, dict):
        dossier = {}
    proposta = dossier.get("proposta") if isinstance(dossier.get("proposta"), dict) else {}
    necessidade = dossier.get("necessidade") if isinstance(dossier.get("necessidade"), dict) else {}

    spec_text = _collect_specs(proposta.get("specs") or [], base_url, token)
    if not spec_text.strip():
        _warn("nenhuma SPEC encontrada para a demanda — review ignorado")
        _emit(_pending())
        return EXIT_OK

    acs = _collect_acs(necessidade.get("acs") or [])
    diff_text = _git_diff(repo_root, sha)

    result = review(
        {"id": demand_id, "repo": args.repo or ""},
        sha,
        diff_text,
        spec_text,
        acs,
    )

    # --- Registro no servidor --------------------------------------------- #
    payload = {
        "sha": sha,
        "verdict": result["verdict"],
        "findings": result["findings"],
        "demand_id": demand_id,
    }
    try:
        status, _ = _http("POST", "/api/reviews", payload, base_url=base_url, token=token)
        if status >= 400:
            _warn(f"POST /api/reviews respondeu {status} — revisão não registrada.")
    except TransportError as exc:
        _warn(f"falha ao registrar a revisão ({exc}) — push liberado.")

    _emit(result)
    return EXIT_BLOCKING if result["verdict"] == "blocking" else EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
