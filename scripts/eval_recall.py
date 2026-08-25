"""Retrieval-quality evaluation for semantic memory search.

Runs the annotated golden queries (``tests/fixtures/recall_golden.jsonl``) and
reports, for each search mode (fts / vector / hybrid):

- Recall@1 / @5 / @10  — how many of the annotated relevant records surfaced
- MRR                 — position of the first relevant record
- nDCG@10             — overall ranking quality (binary relevance)

Two ways to run it
------------------
Local, real embeddings (eyeball tuning)::

    python scripts/eval_recall.py                # provider from config
    python scripts/eval_recall.py --verbose      # per-query hit ranks
    python scripts/eval_recall.py --dump-log     # recent logged queries

Offline, reproducible (CI gate)::

    python scripts/eval_recall.py --ci                   # build fixture DB, run
    python scripts/eval_recall.py --record-baseline      # lock the numbers
    python scripts/eval_recall.py --check                # CI: enforce, fail on regression
    python scripts/eval_recall.py --validate             # golden↔fixture integrity

The golden set is keyed by ``content_hash`` (CI-safe), but CI would still have
nothing to match against — so ``--ci`` builds a throwaway SQLite DB from
``tests/fixtures/recall_memories.jsonl``, reindexes FTS, and writes
fake-embedder vectors. The fake embedder is deterministic, so the numbers are
stable across machines. ``--record-baseline`` snapshots them; ``--check`` then
fails the build only on a regression beyond ``BASELINE_TOLERANCE`` of that
baseline (never on an absolute ideal target).

CI gate policy (decided 2026-08-25)
-----------------------------------
Only the **``fts``** mode is gated (it blocks CI on regression). ``fts`` is
fully offline and deterministic — it does not depend on an embedding model,
vector dimensions, or model version, so its numbers are reproducible. The
planned lexical optimizations (stopwords, jieba search mode, BM25 column
weights) all move ``fts`` directly.

The **``hybrid``** mode is reported for *trend observation only* — it never
fails CI. The fake embedder's vector path is not representative of real
semantic quality, so gating on ``hybrid`` would mislead. ``hybrid`` is
promoted to a gate only once we have a fixed embedding fixture, a pinned
model/version, a stable hybrid baseline, and at least 2–3 model/index
changes verified against it.

Golden entry::

    {"query": "存储", "expect_hashes": ["..."], "expect": ["Zvec"], "note": "..."}
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from bagger.config import settings
from bagger.embedding import create_embedder
from bagger.embedding.base import Embedder
from bagger.embedding.fake import FakeEmbedder
from bagger.services.embed import EmbedService
from bagger.services.hybrid_search import HybridSearch
from bagger.services.recall_bench import TOP_K, build_recall_db, evaluate, load_fixture
from bagger.services.search_eval import (
    regression_failures,
    validate_recall_inputs,
)
from bagger.storage.sqlite import SqliteStorage

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
GOLDEN = FIXTURES / "recall_golden.jsonl"
FIXTURE = FIXTURES / "recall_memories.jsonl"
BASELINE = FIXTURES / "recall_baseline.json"
BASELINE_TOLERANCE = 0.03  # a metric may drop at most 3% vs the locked baseline

# CI gate policy: only ``fts`` blocks the build. ``hybrid`` is reported for
# trend observation and never fails CI (see module docstring for rationale).
GATE_MODE = "fts"
GATE_METRICS = ("recall_at_5", "mrr", "ndcg_at_10")
OBSERVE_MODES = ("hybrid", "vector")
_METRIC_LABELS = {
    "recall_at_1": "R@1",
    "recall_at_5": "R@5",
    "recall_at_10": "R@10",
    "mrr": "MRR",
    "ndcg_at_10": "nDCG@10",
}
_ALL_METRIC_ORDER = ("recall_at_1", "recall_at_5", "recall_at_10", "mrr", "ndcg_at_10")


def _fmt_metrics(metrics: dict[str, float], keys: tuple[str, ...]) -> str:
    return "  ".join(f"{_METRIC_LABELS[k]}={metrics[k]:.2f}" for k in keys)


def print_report(report: dict[str, dict[str, float]]) -> None:
    """Render the metric table with the GATE / OBSERVE distinction explicit."""
    print("=== Retrieval quality report ===")
    if GATE_MODE in report:
        m = report[GATE_MODE]
        print(
            f"\n[GATE]    {GATE_MODE}  — blocks CI on regression "
            f"(tolerance ≤{BASELINE_TOLERANCE:.0%} vs baseline)"
        )
        print(f"          {_fmt_metrics(m, _ALL_METRIC_ORDER)}")
        print(f"          checked: {', '.join(_METRIC_LABELS[k] for k in GATE_METRICS)}")
    for mode in OBSERVE_MODES:
        if mode in report:
            m = report[mode]
            print(f"\n[OBSERVE] {mode}  — trend only, never fails CI")
            print(f"          {_fmt_metrics(m, _ALL_METRIC_ORDER)}")


def load_golden(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def ci_evaluate(golden: list[dict], verbose: bool) -> dict:
    """Build a fixture DB, run the eval offline with the fake embedder."""
    with tempfile.TemporaryDirectory() as d:
        storage = build_recall_db(Path(d) / "recall_ci.db")
        try:
            embedder: Embedder = FakeEmbedder(model="fake")
            hs = HybridSearch(storage, embedder)
            print(f"CI eval on {len(golden)} golden queries (fake embedder, depth {TOP_K}):")
            report = evaluate(golden, hs, verbose=verbose)
            print_report(report)
            return report
        finally:
            storage.close()


def gate(report: dict[str, dict[str, float]]) -> None:
    """Fail (exit 2) on a regression beyond tolerance of the locked baseline.

    The offline gate watches the **fts** mode, not hybrid: the fake embedder's
    vector path is deterministic noise, so ``hybrid`` here is just ``fts`` plus
    a fixed noise floor and is a blunt instrument. The planned lexical
    optimizations (stopwords, jieba search mode, BM25 column weights) all move
    ``fts`` directly, so it is the signal worth protecting in CI. The semantic
    half still needs the real provider and is validated locally with
    ``eval_recall.py`` (no flag).
    """
    if not BASELINE.exists():
        print(
            "no baseline file — run `python scripts/eval_recall.py --record-baseline` "
            "first to lock the current numbers",
            file=sys.stderr,
        )
        raise SystemExit(2)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    metric_names = {"recall_at_1", "recall_at_5", "recall_at_10", "mrr", "ndcg_at_10"}
    base_mode = {k: v for k, v in baseline.get("fts", {}).items() if k in metric_names}
    got_mode = {k: v for k, v in report.get("fts", {}).items() if k in metric_names}
    failures = regression_failures(got_mode, base_mode, BASELINE_TOLERANCE)
    if failures:
        lines = ", ".join(f"{m}: got {g} < floor {f}" for m, (g, f) in failures.items())
        print(f"CI check FAILED (tolerance {BASELINE_TOLERANCE:.0%}): {lines}", file=sys.stderr)
        raise SystemExit(2)
    print(
        f"CI check PASSED — [GATE] fts within {BASELINE_TOLERANCE:.0%} of baseline "
        f"(R@5={got_mode['recall_at_5']:.2f} MRR={got_mode['mrr']:.2f} "
        f"nDCG@10={got_mode['ndcg_at_10']:.2f}). "
        f"[OBSERVE] hybrid/vector reported for trend only, not gated."
    )


def validate() -> None:
    """Portable golden↔fixture integrity check (no database required)."""
    golden = load_golden(GOLDEN)
    fixture = load_fixture(FIXTURE)
    errors = validate_recall_inputs(golden, fixture)
    if errors:
        for e in errors:
            print(f"  ERROR: {e}", file=sys.stderr)
        print(f"validate FAILED: {len(errors)} issue(s)", file=sys.stderr)
        raise SystemExit(2)
    print(f"validate OK: {len(golden)} queries, {len(fixture)} fixture records, all hashes present")


def dump_query_log(limit: int = 50) -> None:
    """Print the most frequent recent queries from the search query log."""
    storage = SqliteStorage(settings.db_path)
    storage.connect()
    try:
        rows = storage.recent_queries(limit=limit)
    finally:
        storage.close()
    if not rows:
        print("query log is empty — search something via /api/memories/search first")
        return
    print(f"top {len(rows)} logged queries (count, last seen, modes, query):")
    for r in rows:
        print(f"  {r['uses']:>4}x  {r['last_used'][:19]}  {r['modes']:<18}  {r['query']}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    verbose = "--verbose" in sys.argv
    check = "--check" in sys.argv
    record_baseline = "--record-baseline" in sys.argv
    ci = "--ci" in sys.argv or check or record_baseline

    if "--dump-log" in sys.argv:
        dump_query_log()
        return

    if "--validate" in sys.argv:
        validate()
        return

    golden = load_golden(GOLDEN)
    if not golden:
        print(f"no golden queries in {GOLDEN}")
        return

    if ci:
        report = ci_evaluate(golden, verbose)
        if record_baseline:
            BASELINE.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"wrote baseline -> {BASELINE}")
            return
        if check:
            gate(report)
        return

    # Local path: evaluate against the real database with real embeddings.
    storage = SqliteStorage(settings.db_path)
    storage.connect()
    try:
        embedder = create_embedder(args[0] if args else None)
        summary = EmbedService(storage, embedder).backfill(reindex_fts=True)
        print(
            f"backfill: embedded={summary['embedded']} total={summary['stats']['total']} "
            f"model={embedder.model_name}"
        )
        hs = HybridSearch(storage, embedder)
        print(
            f"eval on {len(golden)} golden queries (provider={embedder.model_name}, depth {TOP_K}):"
        )
        report = evaluate(golden, hs, verbose=verbose)
        print_report(report)
    finally:
        storage.close()


if __name__ == "__main__":
    main()
