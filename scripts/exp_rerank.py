"""Two-stage re-ranking prototype for OR-expand-narrow.

After OR-expand-narrow landed (2026-08-26), recall improved but a known
precision defect remained: the antonym doc "本地沙箱…联网检查受限"
(id=1538 on the real DB) gets pushed to rank 1 for the query "不联网也能用的个人工具".
Root cause: that doc matches the *raw* query token ``联网`` (not the expansion
token ``本地``), so "original > expansion" weighting alone cannot demote it.
Only an explicit conflict / antonym down-weight sinks it.

This script prototypes gc's proposed two-stage re-rank (2026-08-27), WITHOUT
touching production code:

    FTS recalls top-20            (expanded OR query, as now)
        -> original-token hit weighted above expansion-token hit
        -> full-phrase match bonus
        -> conflict / antonym word down-weight
        -> truncate to top-10

Each factor is isolated into its own variant so we can see which one actually
moves the antonym. Runs on both the fixture DB and the real (read-only) DB.

    python scripts/exp_rerank.py          # fixture mode
    python scripts/exp_rerank.py --prod   # read-only prod mode

Variants::

    baseline (OR-expand-narrow)   current production behavior
    rerank orig>exp               alpha=1.0 beta=0.3, no phrase/conflict
    rerank +phrase               + full-phrase bonus
    rerank +phrase+conflict      + conflict down-weight (full pipeline)
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

RECALL_TOP = 20  # stage-1 recall depth
BIG = 200  # depth for the per-token score maps

# phrase-level expansion: substring match on the raw query (not token level),
# so "不联网" fires as a concept while a bare "联网" does not.
SYNONYMS_NARROW = {
    "瘦身": ["sidecar", "打包"],
    "不联网": ["本地"],
}

# gc-signed conflict lexicon (2026-08-27): words whose presence in a doc
# signals the OPPOSITE of the query intent. For "不联网", any doc containing
# 联网检查 / 受限 / 沙箱 is an antonym and must be demoted.
CONFLICT = {
    "不联网": ["联网检查", "受限", "沙箱"],
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


def search_rerank(
    conn,
    query: str,
    limit: int = 20,
    source: str | None = None,
    synonyms: dict[str, list[str]] | None = None,
    conflict: dict[str, list[str]] | None = None,
    alpha: float = 1.0,
    beta: float = 0.3,
    phrase_bonus: float = 0.0,
    conflict_pen: float = 0.0,
    use_bm25_base: bool = False,
) -> list[dict]:
    """Two-stage re-rank: recall top-20 with the expanded OR query, then sort
    candidates by a composite score.

    Composite base:
      - use_bm25_base=False -> alpha*s_orig + beta*s_exp (original-token
        preference; gc's step 2). This HURTS queries whose relevant docs are
        expansion-only (the antonym match shares the original token 联网).
      - use_bm25_base=True  -> preserve the combined BM25 order, only applying
        the conflict down-weight. Isolates whether step 4 alone is sufficient.
    """
    synonyms = synonyms or {}
    terms = expand_terms(query, synonyms)
    if not terms:
        # no expansion triggered: identical to production, zero behavior change
        return exec_fts(conn, query, limit=limit, source=source)
    # stage 1 — recall
    candidates = exec_fts(conn, query, limit=RECALL_TOP, source=source, extra_tokens=terms)
    # per-token score maps (positive bm25: higher == better)
    orig_map = {r["id"]: -r["rank"] for r in exec_fts(conn, query, limit=BIG, source=source)}
    exp_map = {
        r["id"]: -r["rank"] for r in exec_fts(conn, " ".join(terms), limit=BIG, source=source)
    }
    triggered = next((p for p in synonyms if p in query), None)
    conflict_words = conflict.get(triggered) if (conflict and triggered) else None
    for d in candidates:
        if use_bm25_base:
            final = -d["rank"]  # preserve combined BM25 order
        else:
            s_orig = orig_map.get(d["id"], 0.0)
            s_exp = exp_map.get(d["id"], 0.0)
            final = alpha * s_orig + beta * s_exp
        if phrase_bonus and triggered and triggered in (d.get("content") or ""):
            final += phrase_bonus
        if conflict_words and any(w in (d.get("content") or "") for w in conflict_words):
            final -= conflict_pen
        d["_final"] = final
    candidates.sort(key=lambda d: (-d["_final"], d["id"]))
    return candidates[:limit]


def search_dispatch(
    conn,
    query: str,
    limit: int = 20,
    source: str | None = None,
    mode: str = "or-expand",
    **kw,
) -> list[dict]:
    if mode == "or-expand":
        terms = expand_terms(query, kw.get("synonyms", SYNONYMS_NARROW))
        return exec_fts(conn, query, limit=limit, source=source, extra_tokens=terms)
    if mode == "rerank":
        return search_rerank(conn, query, limit=limit, source=source, **kw)
    raise ValueError(f"unknown mode {mode!r}")


RERANK_VARIANTS: list[tuple[str, dict]] = [
    ("baseline (OR-expand-narrow)", {"mode": "or-expand", "synonyms": SYNONYMS_NARROW}),
    (
        "rerank orig>exp",
        {"mode": "rerank", "synonyms": SYNONYMS_NARROW, "alpha": 1.0, "beta": 0.3},
    ),
    (
        "rerank +phrase",
        {
            "mode": "rerank",
            "synonyms": SYNONYMS_NARROW,
            "alpha": 1.0,
            "beta": 0.3,
            "phrase_bonus": 2.0,
        },
    ),
    (
        "rerank +phrase+conflict",
        {
            "mode": "rerank",
            "synonyms": SYNONYMS_NARROW,
            "conflict": CONFLICT,
            "alpha": 1.0,
            "beta": 0.3,
            "phrase_bonus": 2.0,
            "conflict_pen": 100.0,
        },
    ),
    (
        "conflict-only (preserve bm25)",
        {
            "mode": "rerank",
            "synonyms": SYNONYMS_NARROW,
            "conflict": CONFLICT,
            "use_bm25_base": True,
            "conflict_pen": 100.0,
        },
    ),
]


def make_variant_fn(kw: dict):
    def search_fts(self, query: str, limit: int = 20, source: str | None = None) -> list[dict]:
        if not self._memory_fts_enabled():
            return []
        return search_dispatch(self._conn, query, limit=limit, source=source, **kw)

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
        rows = search_dispatch(conn, g["query"], limit=10, **kw)
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
        f"{'variant':<26}{'R@1':>6}{'R@5':>6}{'R@10':>6}{'MRR':>6}{'nDCG@10':>9}{'ΔR@5':>7}{'ΔnDCG':>7}"
    )
    print("-" * 88)
    for name, m in results:
        print(
            f"{name:<26}"
            f"{m['recall_at_1']:>6.2f}"
            f"{m['recall_at_5']:>6.2f}"
            f"{m['recall_at_10']:>6.2f}"
            f"{m['mrr']:>6.2f}"
            f"{m['ndcg_at_10']:>9.2f}"
            f"{m['recall_at_5'] - base['recall_at_5']:>+7.2f}"
            f"{m['ndcg_at_10'] - base['ndcg_at_10']:>+7.2f}"
        )


def print_miss_detail(conn, golden: list[dict]) -> None:
    from bagger.services.search_eval import relevant_ranks

    targets = [g for g in golden if g["query"] in MISS_QUERIES]
    for g in targets:
        print(f"\n--- {g['query']} (expect {[h[:8] for h in g['expect_hashes']]}) ---")
        for name, kw in RERANK_VARIANTS:
            rows = search_dispatch(conn, g["query"], limit=10, **kw)
            ranks = relevant_ranks(rows, g)
            antonym_rank = None
            for i, r in enumerate(rows, 1):
                if "联网检查" in (r.get("content") or "") or "受限" in (r.get("content") or ""):
                    antonym_rank = i
                    break
            top = " | ".join(f"{i}:{r['content'][:16]}" for i, r in enumerate(rows[:5], 1))
            ant = f" antonym#{antonym_rank}" if antonym_rank else ""
            print(f"  {name:<24} rel={ranks}{ant} top5= {top}")


def _diff_pairs(conn, golden, kw_a, kw_b):
    from bagger.services.search_eval import relevant_ranks

    out = []
    for g in golden:
        ra = relevant_ranks(search_dispatch(conn, g["query"], limit=10, **kw_a), g)
        rb = relevant_ranks(search_dispatch(conn, g["query"], limit=10, **kw_b), g)
        if rb != ra:
            out.append((g, ra, rb))
    return out


def _print_regression(pairs, name):
    print(f"\n--- rank diff: {name} vs baseline (changed queries) ---")
    worse = 0
    for g, ra, rb in pairs:

        def _score(ranks):
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
        results = [(name, metric_row(conn, golden, kw)) for name, kw in RERANK_VARIANTS]
        print_table(results, "prod DB (real corpus, fts only)")
        print_miss_detail(conn, golden)
        _print_regression(
            _diff_pairs(conn, golden, RERANK_VARIANTS[0][1], RERANK_VARIANTS[-1][1]),
            "rerank +phrase+conflict",
        )
    finally:
        conn.close()


def run_fixture(golden: list[dict]) -> None:
    with tempfile.TemporaryDirectory() as d:
        storage = build_recall_db(Path(d) / "exp.db")
        try:
            hs = HybridSearch(storage, FakeEmbedder(model="fake"))
            results: list[tuple[str, dict[str, float]]] = []
            for name, kw in RERANK_VARIANTS:
                orig = hs.storage._search.search_memory_fts
                hs.storage._search.search_memory_fts = types.MethodType(
                    make_variant_fn(kw), hs.storage._search
                )
                try:
                    report = evaluate(golden, hs)
                finally:
                    hs.storage._search.search_memory_fts = orig
                results.append((name, report["fts"]))
            regression = _diff_pairs(
                storage._search._conn, golden, RERANK_VARIANTS[0][1], RERANK_VARIANTS[-1][1]
            )
            print_table(results, "fixture DB (fts only)")
            print_miss_detail(storage._search._conn, golden)
            _print_regression(regression, "rerank +phrase+conflict")
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
