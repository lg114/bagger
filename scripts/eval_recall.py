"""Recall@5 / MRR evaluation for semantic memory retrieval.

Runs the hand-annotated golden queries in
``tests/fixtures/recall_golden.jsonl`` against the *real* memory database and
reports Recall@5 + MRR for each search mode (fts / vector / hybrid). This is the
guardrail from the design doc: swapping models or tuning RRF ``k`` should move
these numbers, not your gut feel.

A golden entry::

    {"query": "存储", "expect": ["Zvec", "Chroma"], "note": "..."}

``expect`` is a list of substrings that must appear in a returned record's
``content`` for that query to count as a hit (within top-5).

Usage::

    python scripts/eval_recall.py            # provider from config (default remote)
    python scripts/eval_recall.py fake       # offline hash embedder, no network
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from bagger.config import settings
from bagger.embedding import create_embedder
from bagger.services.embed import EmbedService
from bagger.services.hybrid_search import HybridSearch
from bagger.storage.sqlite import SqliteStorage

GOLDEN = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "recall_golden.jsonl"
TOP_K = 5


def load_golden(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def evaluate(queries: list[dict], hs: HybridSearch) -> None:
    for mode in ("fts", "vector", "hybrid"):
        recalls: list[int] = []
        mrrs: list[float] = []
        for g in queries:
            res = hs.search(g["query"], mode=mode, limit=TOP_K)
            hit = None
            for i, r in enumerate(res, 1):
                if any(sub in (r.get("content") or "") for sub in g["expect"]):
                    hit = i
                    break
            recalls.append(1 if hit else 0)
            mrrs.append(1.0 / hit if hit else 0.0)
        n = len(recalls) or 1
        print(
            f"  {mode:8}  Recall@{TOP_K}={sum(recalls) / n:.2f}   "
            f"MRR={sum(mrrs) / n:.2f}   ({sum(recalls)}/{len(recalls)} hits)"
        )


def main() -> None:
    provider = sys.argv[1] if len(sys.argv) > 1 else None
    golden = load_golden(GOLDEN)
    if not golden:
        print(f"no golden queries in {GOLDEN}")
        return
    storage = SqliteStorage(settings.db_path)
    storage.connect()
    try:
        embedder = create_embedder(provider)
        # Index first: populate embeddings + memory_fts so every mode has data to
        # search. Idempotent — a second run only embeds records still pending.
        summary = EmbedService(storage, embedder).backfill(reindex_fts=True)
        print(
            f"backfill: embedded={summary['embedded']} total={summary['stats']['total']} "
            f"model={embedder.model_name}"
        )
        hs = HybridSearch(storage, embedder)
        print(
            f"eval on {len(golden)} golden queries (provider={embedder.model_name}, top-{TOP_K}):"
        )
        evaluate(golden, hs)
    finally:
        storage.close()


if __name__ == "__main__":
    main()
