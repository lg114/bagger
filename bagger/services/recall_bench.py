"""Build a fixed, portable recall-eval corpus from ``recall_memories.jsonl``.

The golden set is keyed by ``content_hash``, but CI has no ``memory_records``
whose hashes match. This module closes that gap: it builds a throwaway SQLite
database from the committed fixture, reindexes FTS, and writes fake-embedder
vectors — so ``scripts/eval_recall.py --ci`` (and the offline CI test) run the
exact same search pipeline against a reproducible corpus.

The fake embedder is deterministic (hash vectors), so the resulting metrics are
stable across machines and runs. That makes the CI gate meaningful for the
*lexical* (BM25 + jieba) half of hybrid search; the semantic half still needs
the real provider and is validated locally with ``eval_recall.py`` (no flag).
"""

from __future__ import annotations

import json
from pathlib import Path

from bagger.embedding.fake import FakeEmbedder
from bagger.services.embed import EmbedService
from bagger.services.hybrid_search import HybridSearch
from bagger.services.search_eval import (
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
    relevant_count,
    relevant_ranks,
)
from bagger.storage.sqlite import SqliteStorage

TOP_K = 10  # fetch depth; all @k metrics are computed for k ≤ TOP_K
KS = (1, 5, 10)

FIXTURE = (
    Path(__file__).resolve().parent.parent.parent / "tests" / "fixtures" / "recall_memories.jsonl"
)


def evaluate(queries: list[dict], hs: HybridSearch, verbose: bool = False) -> dict:
    """Run every golden query through each search mode and report metrics.

    Mirrors the measurement contract used everywhere else: for each of
    ``fts`` / ``vector`` / ``hybrid`` it returns ``recall_at_1/5/10``,
    ``mrr`` and ``ndcg_at_10`` (averaged over queries). Kept here (not in the
    CLI script) so both ``eval_recall.py`` and the offline CI test drive the
    exact same evaluation code.
    """
    report: dict[str, dict[str, float]] = {}
    for mode in ("fts", "vector", "hybrid"):
        per_query_ranks: list[tuple[str, list[int], int]] = []  # (query, ranks, n_relevant)
        for g in queries:
            res = hs.search(g["query"], mode=mode, limit=TOP_K)
            ranks = relevant_ranks(res, g)
            per_query_ranks.append((g["query"], ranks, relevant_count(g)))

        n = len(per_query_ranks) or 1
        report[mode] = {
            "recall_at_1": sum(recall_at_k(r, c, 1) for _, r, c in per_query_ranks) / n,
            "recall_at_5": sum(recall_at_k(r, c, 5) for _, r, c in per_query_ranks) / n,
            "recall_at_10": sum(recall_at_k(r, c, 10) for _, r, c in per_query_ranks) / n,
            "mrr": sum(reciprocal_rank(r) for _, r, _ in per_query_ranks) / n,
            "ndcg_at_10": sum(ndcg_at_k(r, c, TOP_K) for _, r, c in per_query_ranks) / n,
        }

        if verbose:
            for q, ranks, _ in per_query_ranks:
                mark = "hit@" + ",".join(map(str, ranks)) if ranks else "MISS"
                print(f"      {mark:12}  {q}")
    return report


def load_fixture(path: Path = FIXTURE) -> list[dict]:
    """Read the recall corpus fixture as a list of record dicts."""
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def import_fixture(storage: SqliteStorage, records: list[dict]) -> int:
    """Insert fixture records into a connected storage.

    Foreign keys are relaxed for the seed (the fixture carries no ``sessions``
    rows) — the eval only searches, never joins sessions, so this is safe for a
    throwaway database.
    """
    storage._conn.execute("PRAGMA foreign_keys=OFF")
    n = 0
    for r in records:
        storage._conn.execute(
            "INSERT INTO memory_records "
            "(type, content, topics, confidence, source, session_id, created_at, content_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r.get("type", "fact"),
                r.get("content", ""),
                r.get("topics", ""),
                r.get("confidence", 0.5),
                r.get("source", "claude"),
                r.get("session_id", "recall-fixture"),
                r.get("created_at", ""),
                r["content_hash"],
            ),
        )
        n += 1
    storage._conn.commit()
    return n


def build_recall_db(db_path: Path, fixture_path: Path = FIXTURE) -> SqliteStorage:
    """Create a fully-indexed temp DB from the fixture and return the storage.

    Steps mirror a production index: create schema (via migrations), import the
    corpus, rebuild ``memory_fts``, and backfill fake embeddings. The fake
    embedder's vectors carry the model bucket ``"fake"`` so they never collide
    with real model vectors.
    """
    records = load_fixture(fixture_path)  # fail fast before touching the database
    db_path.parent.mkdir(parents=True, exist_ok=True)
    storage = SqliteStorage(db_path)
    try:
        storage.connect()
        imported = import_fixture(storage, records)
        embedder = FakeEmbedder(model="fake")
        summary = EmbedService(storage, embedder).backfill(reindex_fts=True)
    except Exception:
        storage.close()
        raise
    print(
        f"[recall-bench] imported={imported} embedded={summary['embedded']} "
        f"model={embedder.model_name}"
    )
    return storage
