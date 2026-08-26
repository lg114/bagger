"""One-factor-at-a-time FTS tuning experiments on the recall fixture.

Motivation: the locked fixture baseline has MRR=0.89 but R@5=0.67 — the first
relevant hit is almost always found, but for multi-relevant queries one
relevant record keeps sliding into ranks 6–10. Diagnosis points at the
rank 5-10 "noise band": OR-joined queries where function words (怎么/的/也)
and single-char tokens contribute BM25 score to irrelevant documents, plus
equal column weights on content vs topics.

This script never touches production code: it monkeypatches the memory-FTS
search path on a throwaway fixture DB and reports the metric delta of each
single change vs the current baseline.

Variants (one factor each)::

    python scripts/exp_fts_tuning.py            # run all, print comparison table

Each variant changes exactly one of: BM25 column weights, query stopword
filter, single-char token filter, jieba search-mode tokenization. Combinations
are only run after single factors show signal.
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
BASELINE = FIXTURES / "recall_baseline.json"

METRICS = ("recall_at_1", "recall_at_5", "recall_at_10", "mrr", "ndcg_at_10")
LABELS = {
    "recall_at_1": "R@1",
    "recall_at_5": "R@5",
    "recall_at_10": "R@10",
    "mrr": "MRR",
    "ndcg_at_10": "nDCG@10",
}

# Conservative function-word list only: words that carry query intent are
# deliberately NOT included (e.g. "报错", "问题" may carry signal in tech notes).
CJK_STOPWORDS = frozenset(
    {
        "的",
        "了",
        "是",
        "在",
        "我",
        "你",
        "他",
        "它",
        "这",
        "那",
        "这个",
        "那个",
        "也",
        "都",
        "和",
        "与",
        "及",
        "或",
        "让",
        "能",
        "会",
        "要",
        "想",
        "被",
        "把",
        "怎么",
        "怎样",
        "如何",
        "什么",
        "为什么",
        "哪",
        "哪些",
        "哪里",
        "谁",
        "呢",
        "吧",
        "啊",
        "吗",
        "么",
        "不",
        "太",
        "很",
        "就",
        "还",
        "又",
        "再",
        "有",
        "没",
        "没有",
        "一个",
        "一些",
        "进行",
        "出现",
        "发生",
        "时",
        "后",
        "前",
        "里",
        "中",
        "上",
        "下",
        "到",
        "给",
        "从",
        "对",
        "对于",
        "关于",
        "希望",
        "办",
        "做",
    }
)

ASCII_STOPWORDS = frozenset(
    {"a", "an", "the", "is", "are", "was", "to", "of", "in", "on", "for", "how", "what", "why"}
)


def load_golden(path: Path = GOLDEN) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def exec_fts(
    conn,
    query: str,
    limit: int = 20,
    source: str | None = None,
    bm25: tuple[float, ...] | None = None,
    stopwords: bool = False,
    drop_single: bool = False,
    search_mode: bool = False,
) -> list[dict]:
    """Run one memory-FTS query against ``conn`` with the given variant factors.

    Mirrors production ``SqliteSearchIndex.search_memory_fts`` SQL exactly
    except for the varied factors, so deltas are attributable.
    """
    tokens: list[str]
    if contains_cjk(query) and jieba_available():
        import jieba

        if search_mode:
            tokens = [t for t in jieba.cut_for_search(query) if t.strip()]
        else:
            tokens = [t for t in jieba.cut(query, HMM=False) if t.strip()]
    else:
        tokens = query.split()
    if stopwords:
        sw = CJK_STOPWORDS | ASCII_STOPWORDS
        tokens = [t for t in tokens if t.lower() not in sw]
    if drop_single:
        tokens = [t for t in tokens if len(t) >= 2]
    if not tokens:
        tokens = [query.strip()]
    safe = _escape_fts5_query(" ".join(tokens))
    weights = f", {', '.join(str(w) for w in bm25)}" if bm25 else ""
    rank_expr = f"bm25(memory_fts{weights})"
    sql = (
        "SELECT m.id, m.type, m.content, m.topics, m.source, m.session_id, m.content_hash, "
        "snippet(memory_fts, 0, '<mark>', '</mark>', '...', 32) as snippet, "
        f"{rank_expr} as rank "
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


def make_variant(
    bm25: tuple[float, ...] | None = None,
    stopwords: bool = False,
    drop_single: bool = False,
    search_mode: bool = False,
):
    """Build a search_memory_fts replacement with one factor changed."""

    def search_fts(self, query: str, limit: int = 20, source: str | None = None) -> list[dict]:
        if not self._memory_fts_enabled():
            return []
        return exec_fts(
            self._conn,
            query,
            limit=limit,
            source=source,
            bm25=bm25,
            stopwords=stopwords,
            drop_single=drop_single,
            search_mode=search_mode,
        )

    return search_fts


def run(golden: list[dict], hs: HybridSearch, name: str, variant_fn) -> dict[str, float]:
    orig = hs.storage._search.search_memory_fts
    hs.storage._search.search_memory_fts = types.MethodType(variant_fn, hs.storage._search)
    try:
        report = evaluate(golden, hs)
    finally:
        hs.storage._search.search_memory_fts = orig
    return report["fts"]


def run_prod(golden: list[dict]) -> None:
    """Validate variants against the real production DB (read-only).

    The fixture is small (133 records) and curated, so a win there may not
    transfer. This connects to ~/.bagger/bagger.db in read-only mode and runs
    the same golden queries through the same SQL, using the real corpus and
    the real golden hashes. Only ``fts`` is measured (no embedding involved).
    """
    import sqlite3

    from bagger.config import settings
    from bagger.services.search_eval import (
        ndcg_at_k,
        recall_at_k,
        reciprocal_rank,
        relevant_count,
        relevant_ranks,
    )

    uri = f"file:{str(settings.db_path).replace(chr(92), '/')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        has_fts = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_fts'"
        ).fetchone()
        if not has_fts:
            print("production DB has no memory_fts table — nothing to validate")
            return
        n = conn.execute("SELECT COUNT(*) FROM memory_records WHERE archived=0").fetchone()[0]
        print(f"[prod] read-only {settings.db_path} ({n} live memory records)")

        prod_experiments: list[tuple[str, dict]] = [
            ("baseline (production)", {}),
            ("bm25 content x5", {"bm25": (5.0, 1.0)}),
            ("bm25 content x2", {"bm25": (2.0, 1.0)}),
            ("bm25 topics x0.5", {"bm25": (1.0, 0.5)}),
            ("bm25 topics x0 (content only)", {"bm25": (1.0, 0.0)}),
            ("jieba search-mode query", {"search_mode": True}),
            ("stopwords filter", {"stopwords": True}),
            ("search-mode + stopwords", {"search_mode": True, "stopwords": True}),
            ("content x5 + search-mode", {"bm25": (5.0, 1.0), "search_mode": True}),
            ("topics x0.5 + search-mode", {"bm25": (1.0, 0.5), "search_mode": True}),
            ("content x2 + search-mode", {"bm25": (2.0, 1.0), "search_mode": True}),
        ]
        results: list[tuple[str, dict[str, float]]] = []
        for name, kw in prod_experiments:
            per: list[tuple[list[int], int]] = []
            for g in golden:
                rows = exec_fts(conn, g["query"], limit=10, **kw)
                ranks = relevant_ranks(rows, g)
                per.append((ranks, relevant_count(g)))
            m = len(per) or 1
            results.append(
                (
                    name,
                    {
                        "recall_at_1": sum(recall_at_k(r, c, 1) for r, c in per) / m,
                        "recall_at_5": sum(recall_at_k(r, c, 5) for r, c in per) / m,
                        "recall_at_10": sum(recall_at_k(r, c, 10) for r, c in per) / m,
                        "mrr": sum(reciprocal_rank(r) for r, _ in per) / m,
                        "ndcg_at_10": sum(ndcg_at_k(r, c, 10) for r, c in per) / m,
                    },
                )
            )
    finally:
        conn.close()

    base = results[0][1]
    header = (
        f"\n{'variant (prod DB)':<28}"
        f"{'R@1':>6}{'R@5':>6}{'R@10':>6}{'MRR':>6}{'nDCG@10':>9}{'ΔR@5':>7}{'ΔnDCG':>7}"
    )
    print(header)
    print("-" * 90)
    for name, m in results:
        dr5 = m["recall_at_5"] - base["recall_at_5"]
        dn = m["ndcg_at_10"] - base["ndcg_at_10"]
        print(
            f"{name:<28}"
            f"{m['recall_at_1']:>6.2f}"
            f"{m['recall_at_5']:>6.2f}"
            f"{m['recall_at_10']:>6.2f}"
            f"{m['mrr']:>6.2f}"
            f"{m['ndcg_at_10']:>9.2f}"
            f"{dr5:>+7.2f}"
            f"{dn:>+7.2f}"
        )


def main() -> None:
    if "--prod" in sys.argv:
        run_prod(load_golden())
        return
    golden = load_golden()
    experiments: list[tuple[str, object]] = [
        ("baseline (production)", None),
        ("bm25 topics x3", make_variant(bm25=(1.0, 3.0))),
        ("bm25 topics x5", make_variant(bm25=(1.0, 5.0))),
        ("bm25 content x5", make_variant(bm25=(5.0, 1.0))),
        ("stopwords filter", make_variant(stopwords=True)),
        ("drop single-char tokens", make_variant(drop_single=True)),
        ("jieba search-mode query", make_variant(search_mode=True)),
        # -- round 2: single factors with signal, combined -----------------
        ("bm25 content x2", make_variant(bm25=(2.0, 1.0))),
        ("content x5 + stopwords", make_variant(bm25=(5.0, 1.0), stopwords=True)),
        ("content x5 + search-mode", make_variant(bm25=(5.0, 1.0), search_mode=True)),
        ("search-mode + stopwords", make_variant(search_mode=True, stopwords=True)),
        (
            "content x5 + search + stopw",
            make_variant(bm25=(5.0, 1.0), search_mode=True, stopwords=True),
        ),
        (
            "content x2 + search + stopw",
            make_variant(bm25=(2.0, 1.0), search_mode=True, stopwords=True),
        ),
        ("bm25 topics x0.5", make_variant(bm25=(1.0, 0.5))),
        ("topics x0.5 + search-mode", make_variant(bm25=(1.0, 0.5), search_mode=True)),
        ("content x2 + search-mode", make_variant(bm25=(2.0, 1.0), search_mode=True)),
    ]
    with tempfile.TemporaryDirectory() as d:
        storage = build_recall_db(Path(d) / "exp.db")
        try:
            hs = HybridSearch(storage, FakeEmbedder(model="fake"))
            results: list[tuple[str, dict[str, float]]] = []
            for name, variant_fn in experiments:
                if variant_fn is None:
                    report = evaluate(golden, hs)
                    results.append((name, report["fts"]))
                else:
                    results.append((name, run(golden, hs, name, variant_fn)))
        finally:
            storage.close()

    base = results[0][1]
    print(
        f"\n{'variant':<28}{'R@1':>6}{'R@5':>6}{'R@10':>6}{'MRR':>6}{'nDCG@10':>9}{'ΔR@5':>7}{'ΔnDCG':>7}"
    )
    print("-" * 90)
    for name, m in results:
        dr5 = m["recall_at_5"] - base["recall_at_5"]
        dn = m["ndcg_at_10"] - base["ndcg_at_10"]
        print(
            f"{name:<28}"
            f"{m['recall_at_1']:>6.2f}"
            f"{m['recall_at_5']:>6.2f}"
            f"{m['recall_at_10']:>6.2f}"
            f"{m['mrr']:>6.2f}"
            f"{m['ndcg_at_10']:>9.2f}"
            f"{dr5:>+7.2f}"
            f"{dn:>+7.2f}"
        )
    print("\n(one factor per row vs baseline; positive Δ is better)")


if __name__ == "__main__":
    main()
