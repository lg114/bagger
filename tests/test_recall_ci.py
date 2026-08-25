"""Offline CI gate for retrieval quality.

Builds the fixed corpus (``recall_memories.jsonl``) into a temp SQLite DB,
indexes FTS + fake-embedder vectors, runs the exact same ``evaluate`` used by
``scripts/eval_recall.py``, and asserts the ``fts`` metrics stay within
tolerance of the locked baseline (``recall_baseline.json``).

This deterministically validates the lexical (BM25 + jieba) half of hybrid
search — the part the planned optimizations (stopwords, jieba search mode,
BM25 column weights) actually move. The semantic half needs the real embedding
provider and is checked locally with ``eval_recall.py`` (no flag); it cannot
run in CI offline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bagger.embedding.fake import FakeEmbedder
from bagger.services.hybrid_search import HybridSearch
from bagger.services.recall_bench import TOP_K, build_recall_db, evaluate, load_fixture
from bagger.services.search_eval import regression_failures, validate_recall_inputs

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "recall_golden.jsonl"
FIXTURE = FIXTURES / "recall_memories.jsonl"
BASELINE = FIXTURES / "recall_baseline.json"
TOLERANCE = 0.03
METRICS = {"recall_at_1", "recall_at_5", "recall_at_10", "mrr", "ndcg_at_10"}


def _golden() -> list[dict]:
    rows: list[dict] = []
    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


@pytest.fixture
def recall_storage(tmp_path):
    if not FIXTURE.exists():
        pytest.skip("recall fixture missing")
    return build_recall_db(tmp_path / "recall.db")


def test_recall_ci_reproducible(recall_storage):
    if not BASELINE.exists():
        pytest.skip("recall baseline missing")
    golden = _golden()
    hs = HybridSearch(recall_storage, FakeEmbedder(model="fake"))
    report = evaluate(golden, hs)
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    got = {k: report["fts"][k] for k in METRICS}
    base = {k: baseline["fts"][k] for k in METRICS}
    # Any regression beyond 3% vs the locked baseline fails the build.
    assert regression_failures(got, base, TOLERANCE) == {}


def test_recall_depth_is_ten():
    assert TOP_K == 10


# -- validate_recall_inputs ------------------------------------------------


def test_validate_recall_inputs_ok():
    golden = _golden()
    fixture = load_fixture(FIXTURE)
    assert validate_recall_inputs(golden, fixture) == []


def test_validate_recall_inputs_missing_hash():
    golden = [{"query": "q", "expect_hashes": ["deadbeef"]}]
    fixture = [{"content_hash": "abc"}]
    errs = validate_recall_inputs(golden, fixture)
    assert any("not present in fixture" in e for e in errs)


def test_validate_recall_inputs_duplicate_and_empty():
    golden = [
        {"query": "q1", "expect_hashes": ["a", "a"]},
        {"query": "q2", "expect_hashes": []},
    ]
    fixture = [{"content_hash": "a"}, {"content_hash": "a"}]
    errs = validate_recall_inputs(golden, fixture)
    assert any("duplicate hash a" in e for e in errs)
    assert any("no expect_hashes" in e for e in errs)
    assert any("duplicate content_hash" in e for e in errs)


# -- regression_failures ---------------------------------------------------


def test_regression_failures_within_tolerance():
    base = {"recall_at_5": 0.50, "mrr": 0.80, "ndcg_at_10": 0.60}
    got = {"recall_at_5": 0.49, "mrr": 0.80, "ndcg_at_10": 0.60}
    assert regression_failures(got, base, TOLERANCE) == {}


def test_regression_failures_detects_drop():
    base = {"recall_at_5": 0.50, "mrr": 0.80, "ndcg_at_10": 0.60}
    got = {"recall_at_5": 0.45, "mrr": 0.80, "ndcg_at_10": 0.60}
    fails = regression_failures(got, base, TOLERANCE)
    assert "recall_at_5" in fails


def test_regression_failures_improvement_never_fails():
    base = {"recall_at_5": 0.50}
    assert regression_failures({"recall_at_5": 0.99}, base, TOLERANCE) == {}
