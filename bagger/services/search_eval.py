"""Retrieval-quality metrics for search evaluation (Recall@k / MRR / nDCG).

Pure functions, no I/O — ``scripts/eval_recall.py`` consumes them against the
real database, and unit tests pin the math. Relevance is *binary* for now:
a golden entry lists the records that count as relevant (by id when
annotated, by content substring as a legacy fallback), and every metric is
computed from the ranks at which those records were returned.

Golden entry format (``tests/fixtures/recall_golden.jsonl``)::

    {"query": "...", "expect_hashes": ["..."], "expect": ["Zvec"], "note": "..."}

``expect_hashes`` is the portable authoritative form. It uses the existing
content fingerprint, so the same golden file works in a fresh CI database.
``expect_ids`` is retained only as a local-database migration aid; ``expect``
substrings remain the final legacy fallback.
"""

from __future__ import annotations

import math


def is_relevant(result: dict, golden: dict) -> bool:
    """True if ``result`` (one row from a search) matches the golden entry.

    Content-hash match takes precedence, followed by the legacy local id
    match, and finally the substring fallback.
    """
    expect_hashes = {str(h) for h in (golden.get("expect_hashes") or [])}
    if expect_hashes:
        return str(result.get("content_hash") or "") in expect_hashes

    expect_ids = golden.get("expect_ids") or []
    if expect_ids:
        rid = result.get("id")
        return rid is not None and int(rid) in {int(i) for i in expect_ids}
    return any(sub in (result.get("content") or "") for sub in golden.get("expect", []))


def relevant_ranks(results: list[dict], golden: dict) -> list[int]:
    """1-based ranks (ascending) at which relevant results appear in ``results``."""
    return [i for i, r in enumerate(results, 1) if is_relevant(r, golden)]


def relevant_count(golden: dict) -> int:
    """Number of results that count as relevant for this golden entry.

    With ``expect_hashes`` or ``expect_ids`` this is exact. With substring
    ``expect`` the upper bound is the number of substrings; that legacy form
    is intentionally not suitable for a strict CI gate and should be migrated.
    """
    expect_hashes = golden.get("expect_hashes") or []
    if expect_hashes:
        return len({str(h) for h in expect_hashes})

    expect_ids = golden.get("expect_ids") or []
    if expect_ids:
        return len(set(int(i) for i in expect_ids))
    return len(golden.get("expect", []))


def recall_at_k(ranks: list[int], n_relevant: int, k: int) -> float:
    """Fraction of the ``n_relevant`` relevant docs retrieved in the top ``k``."""
    if n_relevant <= 0:
        return 0.0
    return len([r for r in ranks if r <= k]) / n_relevant


def reciprocal_rank(ranks: list[int]) -> float:
    """1 / (rank of the first relevant result), 0 when nothing was retrieved."""
    return 1.0 / ranks[0] if ranks else 0.0


def ndcg_at_k(ranks: list[int], n_relevant: int, k: int) -> float:
    """Normalized Discounted Cumulative Gain at ``k`` (binary relevance).

    DCG  = Σ over retrieved-relevant ranks r ≤ k of 1 / log2(r + 1)
    IDCG = the same sum for the ideal ranking (relevant docs at ranks 1..min(R, k))

    Unlike Recall/MRR this credits *how many* relevant docs were surfaced and
    in what order, making it the metric to watch once ranking changes (RRF
    tuning, rerankers, column weights) are on the table.
    """
    if n_relevant <= 0:
        return 0.0
    dcg = sum(1.0 / math.log2(r + 1) for r in ranks if r <= k)
    ideal_hits = min(n_relevant, k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


def regression_failures(
    metrics: dict[str, float], baseline: dict[str, float], tolerance: float = 0.03
) -> dict[str, tuple[float, float]]:
    """Metrics that dropped more than ``tolerance`` below ``baseline``.

    Returns ``{metric: (got, floor)}`` for every metric in ``baseline`` whose
    measured value ``got`` is below ``baseline * (1 - tolerance)``. An empty
    dict means no regression. Improvements (higher is better) never fail.
    """
    failures: dict[str, tuple[float, float]] = {}
    for metric, base in baseline.items():
        got = metrics.get(metric)
        if got is None or base is None:
            continue
        floor = base * (1.0 - tolerance)
        if got < floor - 1e-9:
            failures[metric] = (round(got, 4), round(floor, 4))
    return failures


def validate_recall_inputs(golden: list[dict], fixture: list[dict]) -> list[str]:
    """Portable integrity checks for the golden set + its fixture corpus.

    Catches the failure modes that would make a CI run silently all-miss or
    mask a broken annotation:

    * a golden hash absent from the fixture (CI can never hit it)
    * a duplicate hash within a query, or a duplicate across the fixture
    * a golden query with no ``expect_hashes`` (legacy / un-annotated)
    * a referenced record that is archived (retrieval filters it out)

    Returns a list of human-readable error strings; empty means valid.
    """
    errors: list[str] = []
    fixture_hashes = [r.get("content_hash") for r in fixture]
    fset = set(fixture_hashes)
    if len(fset) != len(fixture_hashes):
        errors.append(f"fixture has {len(fixture_hashes) - len(fset)} duplicate content_hash(es)")
    fmap = {r.get("content_hash"): r for r in fixture}

    for i, g in enumerate(golden):
        q = g.get("query", f"#{i}")
        hashes = g.get("expect_hashes") or []
        if not hashes:
            errors.append(f"query {q!r}: no expect_hashes (legacy / un-annotated)")
            continue
        seen: set[str] = set()
        for h in hashes:
            if h in seen:
                errors.append(f"query {q!r}: duplicate hash {h}")
            seen.add(h)
            rec = fmap.get(h)
            if rec is None:
                errors.append(f"query {q!r}: hash {h} not present in fixture")
            elif rec.get("archived"):
                errors.append(f"query {q!r}: hash {h} is archived")
    return errors
