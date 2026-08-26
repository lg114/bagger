"""Query-expansion experiments for the two persistent semantic-gap misses.

Context: after the A-variant tuning (bm25 content x2 + cut_for_search) the
fixture gate is green, but two golden queries persistently miss because the
query vocabulary and the stored memory vocabulary never overlap:

- "桌面应用体积太大怎么瘦身"  -> expected doc says "sidecar 进程生命周期"
- "不联网也能用的个人工具"    -> expected docs say "本地优先 / 本地"

Real-DB word coverage (verified 2026-08-26, read-only):

    sidecar: 1  (the expected doc)   瘦身: 0 (dead token)
    打包: 8                        本地: 18 (all 4 expected docs)
    体积: 1 (irrelevant doc)        离线: 0 (useless expansion)
    本地优先: 0 (jieba splits it into 本地/优先 in the index)

This script never touches production code: it monkeypatches the memory-FTS
search path and compares expansion strategies on both the fixture DB and the
real production DB:

    python scripts/exp_query_expansion.py          # fixture mode
    python scripts/exp_query_expansion.py --prod   # read-only prod mode

Variants::

    baseline            current production behavior (cut_for_search, bm25 2.0/1.0)
    OR-expand-full      append all synonym tokens into the OR match
    OR-expand-narrow    only synonyms with proven doc coverage (sidecar/打包/本地)
    RRF-fuse w=0.5      separate synonym query, fused with RRF at half weight
    RRF-fuse w=0.3      same, lower weight (protects original ordering harder)
"""

from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bagger.embedding.fake import FakeEmbedder
from bagger.services.hybrid_search import HybridSearch
from bagger.services.recall_bench import build_recall_db, evaluate
from bagger.storage.sqlite import (
    _escape_fts5_query,
    _row_to_dict,
    contains_cjk,
    jieba_available,
)

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
GOLDEN = FIXTURES / "recall_golden.jsonl"

MISS_QUERIES = ("桌面应用体积太大怎么瘦身", "不联网也能用的个人工具")

# phrase-level expansion: substring match on the raw query, not token level,
# so "不联网" fires as a concept and a bare "联网" (e.g. "联网检查") does not.
SYNONYMS_FULL = {
    "瘦身": ["sidecar", "打包", "体积"],
    "不联网": ["本地", "离线"],
}
# only synonyms with proven real-DB doc coverage; dead terms removed
SYNONYMS_NARROW = {
    "瘦身": ["sidecar", "打包"],
    "不联网": ["本地"],
}


def load_golden(path: Path = GOLDEN) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def expand_terms(query: str, table: dict[str, list[str]]) -> list[str]:
    """Return synonym tokens for phrases found in the raw query."""
    out: list[str] = []
    for phrase, terms in table.items():
        if phrase in query:
            out.extend(t for t in terms if t not in out)
    return out


def tokenize(query: str) -> list[str]:
    """Current production memory-FTS tokenization (jieba cut_for_search)."""
    if contains_cjk(query) and jieba_available():
        import jieba

        return [t for t in jieba.cut_for_search(query) if t.strip()]
    return query.split()


def exec_fts(
    conn,
    query: str,
    limit: int = 20,
    source: str | None = None,
    extra_tokens: list[str] | None = None,
) -> list[dict]:
    """Memory-FTS query mirroring current production SQL (A-variant), with an
    optional list of extra OR tokens (the expansion under test)."""
    tokens = tokenize(query)
    if extra_tokens:
        tokens = tokens + [t for t in extra_tokens if t not in tokens]
    safe = _escape_fts5_query(" ".join(tokens) if tokens else query)
    sql = (
        "SELECT m.id, m.type, m.content, m.topics, m.source, m.session_id, m.content_hash, "
        "snippet(memory_fts, 0, '<mark>', '</mark>', '...', 32) as snippet, "
        "bm25(memory_fts, 2.0, 1.0) as rank "
        "FROM memory_fts fts "
        "JOIN memory_records m ON m.id = CAST(fts.record_id AS INTEGER) "
        "WHERE m.archived = 0 AND memory_fts MATCH ?"
    )
    params: list = [safe]
    if source:
        sql += " AND fts.source = ?"
        params.append(source)
    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)
    return [_row_to_dict(r) for r in conn.execute(sql, params).fetchall()]


def search_variant(
    conn,
    query: str,
    limit: int = 20,
    source: str | None = None,
    mode: str = "baseline",
    table: dict[str, list[str]] | None = None,
    fuse_weight: float = 0.5,
) -> list[dict]:
    """Dispatch one variant of the memory-FTS search."""
    if mode == "baseline":
        return exec_fts(conn, query, limit=limit, source=source)
    terms = expand_terms(query, table or {})
    if not terms:
        return exec_fts(conn, query, limit=limit, source=source)
    if mode == "or-expand":
        return exec_fts(conn, query, limit=limit, source=source, extra_tokens=terms)
    if mode == "rrf-fuse":
        base = exec_fts(conn, query, limit=limit, source=source)
        syn = exec_fts(conn, " ".join(terms), limit=limit, source=source)
        scores: dict[int, float] = {}
        by_id: dict[int, dict] = {}
        for i, r in enumerate(base):
            scores[r["id"]] = scores.get(r["id"], 0.0) + 1.0 / (60 + i + 1)
            by_id[r["id"]] = r
        for i, r in enumerate(syn):
            scores[r["id"]] = scores.get(r["id"], 0.0) + fuse_weight / (60 + i + 1)
            by_id.setdefault(r["id"], r)
        ordered = sorted(scores, key=lambda rid: (-scores[rid], rid))
        return [by_id[rid] for rid in ordered[:limit]]
    raise ValueError(f"unknown mode {mode!r}")


VARIANTS: list[tuple[str, dict]] = [
    ("baseline", {"mode": "baseline"}),
    ("OR-expand-full", {"mode": "or-expand", "table": SYNONYMS_FULL}),
    ("OR-expand-narrow", {"mode": "or-expand", "table": SYNONYMS_NARROW}),
    ("RRF-fuse w=0.5", {"mode": "rrf-fuse", "table": SYNONYMS_NARROW, "fuse_weight": 0.5}),
    ("RRF-fuse w=0.8", {"mode": "rrf-fuse", "table": SYNONYMS_NARROW, "fuse_weight": 0.8}),
    ("RRF-fuse w=1.0", {"mode": "rrf-fuse", "table": SYNONYMS_NARROW, "fuse_weight": 1.0}),
]


def make_variant_fn(kw: dict):
    """Build a search_memory_fts replacement for fixture monkeypatching."""

    def search_fts(self, query: str, limit: int = 20, source: str | None = None) -> list[dict]:
        if not self._memory_fts_enabled():
            return []
        return search_variant(self._conn, query, limit=limit, source=source, **kw)

    return search_fts


def metric_row(conn, golden: list[dict], kw: dict) -> dict[str, float]:
    from bagger.services.search_eval import (
        ndcg_at_k,
        recall_at_k,
        reciprocal_rank,
        relevant_count,
        relevant_ranks,
    )

    per: list[tuple[list[int], int]] = []
    for g in golden:
        rows = search_variant(conn, g["query"], limit=10, **kw)
        per.append((relevant_ranks(rows, g), relevant_count(g)))
    m = len(per) or 1
    return {
        "recall_at_1": sum(recall_at_k(r, c, 1) for r, c in per) / m,
        "recall_at_5": sum(recall_at_k(r, c, 5) for r, c in per) / m,
        "recall_at_10": sum(recall_at_k(r, c, 10) for r, c in per) / m,
        "mrr": sum(reciprocal_rank(r) for r, _ in per) / m,
        "ndcg_at_10": sum(ndcg_at_k(r, c, 10) for r, c in per) / m,
    }


def print_table(results: list[tuple[str, dict[str, float]]], title: str) -> None:
    base = results[0][1]
    print(f"\n{title}")
    print(
        f"{'variant':<20}{'R@1':>6}{'R@5':>6}{'R@10':>6}{'MRR':>6}{'nDCG@10':>9}{'ΔR@5':>7}{'ΔnDCG':>7}"
    )
    print("-" * 82)
    for name, m in results:
        print(
            f"{name:<20}"
            f"{m['recall_at_1']:>6.2f}"
            f"{m['recall_at_5']:>6.2f}"
            f"{m['recall_at_10']:>6.2f}"
            f"{m['mrr']:>6.2f}"
            f"{m['ndcg_at_10']:>9.2f}"
            f"{m['recall_at_5'] - base['recall_at_5']:>+7.2f}"
            f"{m['ndcg_at_10'] - base['ndcg_at_10']:>+7.2f}"
        )


def print_miss_detail(conn, golden: list[dict]) -> None:
    """Per-query detail for the two persistent-miss queries, per variant."""
    from bagger.services.search_eval import relevant_ranks

    targets = [g for g in golden if g["query"] in MISS_QUERIES]
    for g in targets:
        print(f"\n--- {g['query']} (expect {[h[:8] for h in g['expect_hashes']]}) ---")
        for name, kw in VARIANTS:
            rows = search_variant(conn, g["query"], limit=10, **kw)
            ranks = relevant_ranks(rows, g)
            top = " | ".join(f"{i}:{r['content'][:18]}" for i, r in enumerate(rows[:5], 1))
            print(f"  {name:<18} relevant_ranks={ranks} top5= {top}")


def _diff_pairs(
    conn, golden: list[dict], kw_a: dict, kw_b: dict
) -> list[tuple[dict, list[int], list[int]]]:
    """Per-query rank diff between two variants (queried while conn is open)."""
    from bagger.services.search_eval import relevant_ranks

    out: list[tuple[dict, list[int], list[int]]] = []
    for g in golden:
        ra = relevant_ranks(search_variant(conn, g["query"], limit=10, **kw_a), g)
        rb = relevant_ranks(search_variant(conn, g["query"], limit=10, **kw_b), g)
        if rb != ra:
            out.append((g, ra, rb))
    return out


def _print_regression(pairs: list[tuple[dict, list[int], list[int]]], name: str) -> None:
    """Flag any query whose ranks got worse under the variant."""
    print(f"\n--- rank diff: {name} vs baseline (changed queries) ---")
    worse = 0
    for g, ra, rb in pairs:

        def _score(ranks: list[int]) -> tuple[int, int]:
            return (len([r for r in ranks if r <= 10]), -sum(ranks) if ranks else 0)

        delta = ""
        if _score(rb) < _score(ra):
            delta = "  <-- WORSE"
            worse += 1
        print(f"  {g['query'][:24]:<26} {ra} -> {rb}{delta}")
    if not pairs:
        print("  (no query changed at all)")
    if not worse:
        print("  (no query got worse)")


def run_prod(golden: list[dict]) -> None:
    import sqlite3

    from bagger.config import settings

    uri = f"file:{str(settings.db_path).replace(chr(92), '/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        n = conn.execute("SELECT COUNT(*) FROM memory_records WHERE archived=0").fetchone()[0]
        print(f"[prod] read-only {settings.db_path} ({n} live memory records)")
        results = [(name, metric_row(conn, golden, kw)) for name, kw in VARIANTS]
        regression = [
            (q, ra, rb) for q, ra, rb in _diff_pairs(conn, golden, VARIANTS[0][1], VARIANTS[2][1])
        ]
    finally:
        conn.close()
    print_table(results, "prod DB (real corpus, fts only)")
    print_miss_detail_conn(golden)
    _print_regression(regression, "OR-expand-narrow")


def print_miss_detail_conn(golden: list[dict]) -> None:
    import sqlite3

    from bagger.config import settings

    uri = f"file:{str(settings.db_path).replace(chr(92), '/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        print_miss_detail(conn, golden)
    finally:
        conn.close()


def run_fixture(golden: list[dict]) -> None:
    with tempfile.TemporaryDirectory() as d:
        storage = build_recall_db(Path(d) / "exp.db")
        try:
            hs = HybridSearch(storage, FakeEmbedder(model="fake"))
            results: list[tuple[str, dict[str, float]]] = []
            for name, kw in VARIANTS:
                if kw["mode"] == "baseline":
                    report = evaluate(golden, hs)
                    results.append((name, report["fts"]))
                    continue
                orig = hs.storage._search.search_memory_fts
                hs.storage._search.search_memory_fts = types.MethodType(
                    make_variant_fn(kw), hs.storage._search
                )
                try:
                    report = evaluate(golden, hs)
                finally:
                    hs.storage._search.search_memory_fts = orig
                results.append((name, report["fts"]))
            regression = _diff_pairs(storage._search._conn, golden, VARIANTS[0][1], VARIANTS[-1][1])
            print_table(results, "fixture DB (fts only)")
            print_miss_detail(storage._search._conn, golden)
            _print_regression(regression, VARIANTS[-1][0])
        finally:
            storage.close()


def main() -> None:
    golden = load_golden()
    if "--prod" in sys.argv:
        run_prod(golden)
    else:
        run_fixture(golden)


if __name__ == "__main__":
    main()
