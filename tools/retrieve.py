"""BM25 retriever over Blueprint docs/. Stdlib only.

Usage:
    python tools/retrieve.py --query "quando criar um Output Port" --top 5
    python tools/retrieve.py --query "use case teste" --root docs --top 3

Goal: when generating a SPEC, the agent asks a short question in natural
language and pastes the top hits into its context (RAG-lite). No embeddings,
no model — pure lexical retrieval over H2/H3 sections.

Honest limits: lexical ≠ semantic. It will miss synonyms and will over-rank
exact-term matches. Good enough for technical docs in Portuguese where the
question vocabulary overlaps heavily with the answer vocabulary. For real
semantic retrieval, swap BM25 for an embedding-based backend later.
"""
from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

_WORD = re.compile(r"\w+", re.UNICODE)
_SPLIT = re.compile(r"^(#{1,3} .+)$", re.M)


def tokenize(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text) if len(w) > 1]


class Chunk:
    __slots__ = ("path", "heading", "body", "tokens")

    def __init__(self, path: str, heading: str, body: str, tokens: list[str]):
        self.path = path
        self.heading = heading
        self.body = body
        self.tokens = tokens


def chunk_file(path: Path) -> list[Chunk]:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    parts = _SPLIT.split(text)
    chunks: list[Chunk] = []
    for i in range(1, len(parts), 2):
        heading = parts[i].lstrip("# ").strip()
        body = parts[i + 1] if i + 1 < len(parts) else ""
        if not heading or not body.strip():
            continue
        body = body.strip()[:800]
        chunks.append(Chunk(str(path), heading, body, tokenize(heading + "\n" + body)))
    if not chunks:
        chunks.append(Chunk(str(path), path.stem, text[:800], tokenize(text[:800])))
    return chunks


class BM25:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.N = len(chunks)
        self.avgdl = sum(len(c.tokens) for c in chunks) / max(self.N, 1)
        self.df: dict[str, int] = defaultdict(int)
        self.tf: list[Counter] = []
        self.dl: list[int] = []
        for c in chunks:
            tf = Counter(c.tokens)
            self.tf.append(tf)
            self.dl.append(len(c.tokens))
            for term in set(c.tokens):
                self.df[term] += 1

    def score(self, query_tokens: list[str]) -> list[tuple[Chunk, float]]:
        scores = [0.0] * self.N
        for q in query_tokens:
            df = self.df.get(q, 0)
            if df == 0:
                continue
            idf = math.log(1 + (self.N - df + 0.5) / (df + 0.5))
            for j in range(self.N):
                f = self.tf[j].get(q, 0)
                if f == 0:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * self.dl[j] / self.avgdl)
                scores[j] += idf * (f * (self.k1 + 1)) / denom
        return sorted(
            ((self.chunks[i], s) for i, s in enumerate(scores) if s > 0),
            key=lambda x: -x[1],
        )


def build_index(root: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for p in sorted(root.rglob("*.md")):
        chunks.extend(chunk_file(p))
    return chunks


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="docs", type=Path)
    ap.add_argument("--query", required=True)
    ap.add_argument("--top", type=int, default=5)
    args = ap.parse_args()

    if not args.root.exists():
        print(f"root not found: {args.root}", file=sys.stderr)
        return 1
    chunks = build_index(args.root)
    if not chunks:
        print(f"no .md under {args.root}", file=sys.stderr)
        return 1
    bm25 = BM25(chunks)
    hits = bm25.score(tokenize(args.query))[: args.top]
    if not hits:
        print("no matches")
        return 0
    for chunk, score in hits:
        print(f"--- {chunk.path} :: {chunk.heading} (score={score:.2f})")
        snippet = chunk.body.strip().replace("\n", " ")
        if len(snippet) > 240:
            snippet = snippet[:240] + "…"
        print(snippet)
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())