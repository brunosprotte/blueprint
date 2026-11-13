"""Busca no conhecimento: candidatos (Postgres FTS) + rerank BM25 em Python puro.

Fase F7. Duas etapas (design master §14.2):

1. **Candidatos** — `tsvector` (`portuguese`) + `plainto_tsquery`, `LIMIT 200`.
2. **Rerank** — BM25 em Python (`k1=1.5`, `b=0.75`), mesma fórmula do
   `tools/retrieve.py`, calculada **sobre o conjunto de candidatos**.

O corpus nunca cruza corpora: toda query carrega `WHERE corpus_id = $1` com o
corpus exato do pedido.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from app.services.indexer import METHOD_CORPUS, ensure_method_indexed, tokenize

__all__ = ["Hit", "Candidate", "bm25_rank", "search", "build_dossier"]

K1 = 1.5
B = 0.75
MAX_CANDIDATES = 200

_CANDIDATES_SQL = """
WITH q AS (SELECT plainto_tsquery('portuguese', $2::text) AS tsq)
SELECT c.id, c.artifact_id, c.demand_id, c.source_kind,
       c.heading, c.text, c.token_count, c.corpus_id, c.source_ref
  FROM chunks c, q
 WHERE c.corpus_id = $1
   AND c.tsv @@ q.tsq
 ORDER BY ts_rank_cd(c.tsv, q.tsq) DESC, c.id ASC
 LIMIT 200
"""


@dataclass
class Hit:
    """Hit de busca. A ordem dos 7 campos do contrato é posicional; `source_kind` é o último."""

    chunk_id: str
    artifact_id: str | None
    demand_id: str | None
    heading: str
    text: str
    score: float
    corpus_id: str
    source_kind: str = ""


@dataclass(frozen=True)
class Candidate:
    chunk_id: str
    tokens: tuple[str, ...]
    length: int


def bm25_rank(
    candidates: Sequence[Candidate],
    query_tokens: Sequence[str],
    *,
    k1: float = K1,
    b: float = B,
) -> list[tuple[str, float]]:
    """Rerank BM25 sobre o **conjunto de candidatos**.

    `N`, `df` e `avgdl` são calculados sobre os candidatos (≤ 200 chunks), não sobre
    o corpus inteiro. Termo com `df = 0` contribui 0; chunk com score 0 é descartado.
    Desempate: `score DESC, chunk_id ASC`.
    """
    n = len(candidates)
    if not n:
        return []

    df: Counter[str] = Counter()
    for cand in candidates:
        df.update(set(cand.tokens))
    avgdl = sum(c.length for c in candidates) / n
    if avgdl <= 0:
        avgdl = 1.0

    scores: list[tuple[str, float]] = []
    for cand in candidates:
        tf = Counter(cand.tokens)
        score = 0.0
        for term in dict.fromkeys(query_tokens):
            docs = df.get(term, 0)
            if docs == 0:
                continue
            freq = tf.get(term, 0)
            if freq == 0:
                continue
            idf = math.log(1 + (n - docs + 0.5) / (docs + 0.5))
            denom = freq + k1 * (1 - b + b * cand.length / avgdl)
            score += idf * (freq * (k1 + 1)) / denom
        if score > 0:
            scores.append((cand.chunk_id, score))
    scores.sort(key=lambda item: (-item[1], item[0]))
    return scores


def _as_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _json_list(value: Any) -> list:
    """Coluna `jsonb` (files, findings) pode chegar como lista ou como texto JSON.

    O asyncpg devolve `jsonb` como `str` quando não há codec registrado — sem esta
    normalização, `list(files)` viraria lista de caracteres.
    """
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


async def search(q: str, corpus_id: str, top: int = 10) -> list[Hit]:
    """Busca no corpus `corpus_id`. Nunca mistura corpus."""
    from app import db

    if corpus_id == METHOD_CORPUS:
        await ensure_method_indexed()

    top = max(1, min(int(top), MAX_CANDIDATES))
    pool = await db.get_pool()
    rows = await db.fetch(pool, _CANDIDATES_SQL, corpus_id, q)

    candidates: list[Candidate] = []
    by_id: dict[str, Any] = {}
    for row in rows:
        chunk_id = str(row["id"])
        tokens = tokenize(f"{row['heading'] or ''}\n{row['text'] or ''}")
        length = int(row["token_count"] or 0) or len(tokens)
        candidates.append(Candidate(chunk_id=chunk_id, tokens=tuple(tokens), length=length))
        by_id[chunk_id] = row

    hits: list[Hit] = []
    for chunk_id, score in bm25_rank(candidates, tokenize(q)):
        row = by_id[chunk_id]
        hits.append(
            Hit(
                chunk_id=chunk_id,
                artifact_id=_as_text(row["artifact_id"]),
                demand_id=_as_text(row["demand_id"]),
                heading=row["heading"] or "",
                text=row["text"] or "",
                score=score,
                corpus_id=row["corpus_id"],
                source_kind=row["source_kind"] or "",
            )
        )
        if len(hits) >= top:
            break
    return hits


# --- dossiê ---------------------------------------------------------------

_AC_ID_RE = re.compile(r"\bAC-\d{3}\b")
_AC_TITLE_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?(AC-\d{3})(?:\*\*)?\s*[:.\-–—]?\s*(.*)$"
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _norm_heading(text: str) -> str:
    """Normalização de heading do linter (F2 §5.2): minúsculas, sem acentos, sem pontuação."""
    plain = unicodedata.normalize("NFKD", text or "")
    plain = "".join(ch for ch in plain if not unicodedata.combining(ch))
    plain = re.sub(r"[^\w\s]", " ", plain.lower())
    return re.sub(r"\s+", " ", plain).strip()


def _frontmatter(content: str) -> dict:
    """Frontmatter YAML do conteúdo de um artefato (best effort)."""
    text = content or ""
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    try:
        import yaml

        data = yaml.safe_load(text[3:end]) or {}
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _body_of(content: str) -> str:
    text = content or ""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:]
    return text


def _section_body(body: str, wanted: str) -> str | None:
    """Corpo da seção cujo heading normalizado é `wanted` (None se não existir)."""
    lines = body.splitlines()
    wanted_norm = _norm_heading(wanted)
    start: int | None = None
    level = 0
    for idx, line in enumerate(lines):
        match = _HEADING_RE.match(line)
        if match is None:
            continue
        if start is None:
            if _norm_heading(match.group(2)) == wanted_norm:
                start = idx + 1
                level = len(match.group(1))
            continue
        if len(match.group(1)) <= level:
            return "\n".join(lines[start:idx])
    if start is None:
        return None
    return "\n".join(lines[start:])


def extract_acs(body: str) -> tuple[list[str], dict[str, str]]:
    """ACs do corpo de uma BR: ids (regex do linter F2 `BR-004`) e título da 1ª ocorrência."""
    ids: list[str] = []
    titles: dict[str, str] = {}
    for line in (body or "").splitlines():
        title_match = _AC_TITLE_RE.match(line)
        if title_match is not None and title_match.group(1) not in titles:
            titles[title_match.group(1)] = title_match.group(2).strip()
        for found in _AC_ID_RE.findall(line):
            if found not in ids:
                ids.append(found)
    return ids, titles


def _spec_covers(spec: dict) -> set[str]:
    """ACs cobertas por uma SPEC: seção 'Acceptance Criteria atendidos' ou frontmatter."""
    content = spec.get("content") or ""
    body = _body_of(content)
    front = spec.get("frontmatter") or {}

    covered: set[str] = set()
    found_section = False
    section = _section_body(body, "Acceptance Criteria atendidos")
    if section is not None:
        found_section = True
        covered.update(_AC_ID_RE.findall(section))

    raw = front.get("acceptanceCriteria")
    if raw:
        found_section = True
        if isinstance(raw, str):
            covered.update(_AC_ID_RE.findall(raw))
        elif isinstance(raw, (list, tuple)):
            for item in raw:
                covered.update(_AC_ID_RE.findall(str(item)))

    if not found_section:
        covered.update(_AC_ID_RE.findall(body))
    return covered


def _touches(commit_files: Iterable[Any], spec_path: str) -> bool:
    for item in commit_files or []:
        name = str(item).replace("\\", "/")
        if name == spec_path or name.endswith("/" + spec_path):
            return True
    return False


async def build_dossier(pool: Any, demand_id: Any) -> dict | None:
    """Monta o dossiê da demanda: necessidade, proposta, implementação e desvios.

    Retorna `None` se a demanda não existir.
    """
    from app import db

    demand = await db.fetchrow(pool, "SELECT * FROM demands WHERE id = $1", demand_id)
    if demand is None:
        return None

    artifact_rows = await db.fetch(
        pool,
        "SELECT id, kind, module, feature, path, status, content "
        "FROM artifacts WHERE demand_id = $1 ORDER BY id",
        demand_id,
    )
    artifacts = []
    for row in artifact_rows:
        item = {
            "id": str(row["id"]),
            "kind": row["kind"],
            "module": row["module"],
            "feature": row["feature"],
            "path": row["path"],
            "status": row["status"],
            "content": row["content"] or "",
        }
        item["frontmatter"] = _frontmatter(item["content"])
        artifacts.append(item)

    brs = [a for a in artifacts if a["kind"] == "br"]
    specs = [a for a in artifacts if a["kind"] == "spec"]
    spec_ids = [s["id"] for s in specs]

    edges = []
    if spec_ids:
        edge_rows = await db.fetch(
            pool,
            "SELECT parent_id, child_id, type FROM spec_edges "
            "WHERE parent_id = ANY($1::text[]) AND child_id = ANY($1::text[]) "
            "AND type = ANY($2::text[])",
            spec_ids,
            ["depends_on", "derives_from", "tests"],
        )
        edges = [
            {"parent": str(r["parent_id"]), "child": str(r["child_id"]), "type": r["type"]}
            for r in edge_rows
        ]

    commit_rows = await db.fetch(
        pool,
        "SELECT id, sha, message, branch, author, files, status, created_at "
        "FROM commits WHERE demand_id = $1 ORDER BY created_at ASC, sha ASC",
        demand_id,
    )
    commits = [
        {
            "id": str(r["id"]),
            "sha": r["sha"],
            "message": r["message"],
            "branch": r["branch"],
            "author": r["author"],
            "files": _json_list(r["files"]),
            "status": r["status"] or "present",
            "created_at": r["created_at"],
        }
        for r in commit_rows
    ]

    review_rows = await db.fetch(
        pool,
        "SELECT r.id, r.commit_id, r.verdict, r.findings, r.created_at, c.sha AS commit_sha "
        "FROM reviews r LEFT JOIN commits c ON c.id = r.commit_id "
        "WHERE r.demand_id = $1 ORDER BY r.created_at ASC, r.id ASC",
        demand_id,
    )
    reviews = [
        {
            "id": str(r["id"]),
            "commit_sha": r["commit_sha"],
            "verdict": r["verdict"],
            "findings": _json_list(r["findings"]),
            "created_at": r["created_at"],
        }
        for r in review_rows
    ]

    artifact_ids = [a["id"] for a in artifacts]
    doubts = []
    if artifact_ids:
        doubt_rows = await db.fetch(
            pool,
            "SELECT id, artifact_id, question, status, source FROM doubts "
            "WHERE artifact_id = ANY($1::text[])",
            artifact_ids,
        )
        doubts = [
            {
                "id": str(r["id"]),
                "artifact_id": str(r["artifact_id"]),
                "question": r["question"] or "",
                "status": r["status"],
                "source": r["source"],
            }
            for r in doubt_rows
        ]

    # --- necessidade ---
    br_view = [
        {
            "id": b["id"],
            "path": b["path"],
            "title": str(b["frontmatter"].get("title") or ""),
            "module": b["module"],
            "feature": b["feature"],
            "status": b["status"],
        }
        for b in brs
    ]

    coverage: dict[str, list[str]] = {}
    for spec in specs:
        for ac in _spec_covers(spec):
            coverage.setdefault(ac, []).append(spec["id"])

    ac_ids: list[str] = []
    ac_titles: dict[str, str] = {}
    for br in brs:
        found, titles = extract_acs(_body_of(br["content"]))
        ac_titles.update(titles)
        for ac in found:
            if ac not in ac_ids:
                ac_ids.append(ac)
    ac_ids.sort()

    ac_view = []
    for ac in ac_ids:
        covered_specs = sorted(coverage.get(ac, []))
        ac_view.append(
            {
                "id": ac,
                "title": ac_titles.get(ac, ""),
                "specs": covered_specs,
                "commits": _commits_for_ac(ac, covered_specs, specs, commits),
            }
        )

    # --- proposta ---
    spec_view = [
        {
            "id": s["id"],
            "path": s["path"],
            "title": str(s["frontmatter"].get("title") or ""),
            "module": s["module"],
            "status": s["status"],
        }
        for s in specs
    ]

    # --- implementação ---
    commit_view = [
        {
            "sha": c["sha"],
            "message": c["message"],
            "branch": c["branch"],
            "author": c["author"],
            "files": c["files"],
            "status": c["status"],
        }
        for c in commits
        if c["status"] != "orphaned"
    ]
    review_view = [
        {
            "id": r["id"],
            "commit_sha": r["commit_sha"],
            "verdict": r["verdict"],
            "findings": r["findings"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in reviews
    ]

    # --- desvios ---
    desvios: list[dict] = []
    for ac in ac_ids:
        covered_specs = sorted(coverage.get(ac, []))
        if not covered_specs:
            desvios.append(
                {
                    "kind": "ac_sem_spec",
                    "ac": ac,
                    "title": ac_titles.get(ac, ""),
                    "specs": [],
                    "detail": f"{ac} não é coberta por nenhuma SPEC da demanda",
                }
            )
            continue
        if not _commits_for_ac(ac, covered_specs, specs, commits):
            desvios.append(
                {
                    "kind": "ac_sem_commit",
                    "ac": ac,
                    "title": ac_titles.get(ac, ""),
                    "specs": covered_specs,
                    "detail": f"{ac} é coberta por {', '.join(covered_specs)}, "
                    "mas nenhum commit da demanda a referencia",
                }
            )

    blocking = []
    for review in reviews:
        for finding in review["findings"]:
            if not isinstance(finding, dict) or finding.get("severity") != "blocking":
                continue
            ac = str(finding.get("ac") or "")
            covered = set(coverage.get(ac, []))
            doubt = _open_doubt(doubts, covered, ac)
            if doubt is None:
                continue
            blocking.append(
                {
                    "kind": "finding_bloqueante",
                    "ac": ac or None,
                    "title": str(finding.get("title") or ""),
                    "detail": str(finding.get("detail") or ""),
                    "artifact_id": doubt["artifact_id"],
                    "commit_sha": review["commit_sha"],
                    "severity": "blocking",
                    "suggestion": str(finding.get("suggestion") or ""),
                    "doubt_status": doubt["status"],
                }
            )
    blocking.sort(key=lambda d: (str(d["commit_sha"] or ""), d["title"]))
    desvios.extend(blocking)

    return {
        "necessidade": {"br": br_view, "acs": ac_view},
        "proposta": {"specs": spec_view, "grafo": edges},
        "implementacao": {"commits": commit_view, "reviews": review_view},
        "desvios": desvios,
    }


def _commits_for_ac(
    ac: str,
    covered_specs: list[str],
    specs: list[dict],
    commits: list[dict],
) -> list[str]:
    """`sha[:7]` dos commits que referenciam a AC (mensagem ou path de SPEC coberta)."""
    paths = [s["path"] for s in specs if s["id"] in covered_specs and s.get("path")]
    found: list[str] = []
    for commit in commits:
        message = commit["message"] or ""
        hit = bool(_AC_ID_RE.search(message)) and ac in _AC_ID_RE.findall(message)
        if not hit:
            hit = any(_touches(commit["files"], path) for path in paths)
        if hit:
            found.append(commit["sha"][:7])
    return found


def _open_doubt(doubts: list[dict], covered_spec_ids: set[str], ac: str) -> dict | None:
    """Dúvida aberta que corresponde ao achado bloqueante (spec §10.3).

    A tabela `doubts` não tem coluna `ac`: a AC mora no início da `question`, no
    formato canônico do F6 (`"[<ac>] <title> — <detail>"`). Só dúvida de revisor
    (`source = 'reviewer'`) conta, e só enquanto `status <> 'cleaned'`.
    """
    prefix = f"[{ac}]" if ac else "[]"
    matches = [
        d
        for d in doubts
        if d["status"] != "cleaned"
        and d["source"] == "reviewer"
        and d["question"].startswith(prefix)
    ]
    if not matches:
        return None
    # Preferência: dúvida sobre uma SPEC que cobre a AC do achado.
    matches.sort(key=lambda d: (d["artifact_id"] not in covered_spec_ids, d["artifact_id"], d["id"]))
    return matches[0]
