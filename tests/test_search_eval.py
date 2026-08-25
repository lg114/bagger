"""Unit tests for retrieval-quality metrics (bagger.services.search_eval)."""

from bagger.services.search_eval import (
    is_relevant,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank,
    relevant_count,
    relevant_ranks,
)


def _results(*ids: int) -> list[dict]:
    return [{"id": i, "content": f"record {i}"} for i in ids]


def test_is_relevant_prefers_ids_over_substring():
    golden = {"query": "q", "expect_ids": [3], "expect": ["record"]}
    # Substring would match everything, but ids are authoritative.
    assert is_relevant({"id": 3, "content": "anything"}, golden) is True
    assert is_relevant({"id": 1, "content": "record"}, golden) is False


def test_is_relevant_prefers_stable_content_hash():
    golden = {"query": "q", "expect_hashes": ["hash-zvec"], "expect_ids": [3]}
    assert is_relevant({"id": 99, "content_hash": "hash-zvec"}, golden) is True
    assert is_relevant({"id": 3, "content_hash": "other"}, golden) is False


def test_is_relevant_substring_fallback_without_ids():
    golden = {"query": "q", "expect": ["Zvec"]}
    assert is_relevant({"id": 9, "content": "use Zvec here"}, golden) is True
    assert is_relevant({"id": 9, "content": "use milvus"}, golden) is False


def test_relevant_ranks_are_one_based_and_ascending():
    golden = {"query": "q", "expect_ids": [5, 2]}
    ranks = relevant_ranks(_results(1, 2, 3, 5), golden)
    assert ranks == [2, 4]


def test_recall_at_k_counts_only_hits_within_cutoff():
    # 2 relevant docs, one retrieved at rank 3 (within 5), one at rank 9 (outside 5).
    assert recall_at_k([3, 9], n_relevant=2, k=5) == 0.5
    assert recall_at_k([3, 9], n_relevant=2, k=10) == 1.0
    assert recall_at_k([], n_relevant=2, k=10) == 0.0
    # No annotation → recall is vacuously 0, never a ZeroDivisionError.
    assert recall_at_k([1], n_relevant=0, k=10) == 0.0


def test_reciprocal_rank():
    assert reciprocal_rank([1]) == 1.0
    assert reciprocal_rank([4]) == 0.25
    assert reciprocal_rank([]) == 0.0


def test_ndcg_perfect_ranking_is_one():
    assert ndcg_at_k([1, 2, 3], n_relevant=3, k=10) == 1.0


def test_ndcg_penalizes_late_and_missing_hits():
    perfect = ndcg_at_k([1, 2], n_relevant=2, k=10)
    late = ndcg_at_k([8, 9], n_relevant=2, k=10)
    partial = ndcg_at_k([1], n_relevant=2, k=10)
    assert perfect == 1.0
    assert 0.0 < late < partial < perfect


def test_ndcg_ignores_hits_beyond_cutoff():
    # A relevant doc at rank 12 must not count toward nDCG@10.
    assert ndcg_at_k([12], n_relevant=1, k=10) == 0.0


def test_relevant_count_dedupes_ids():
    assert relevant_count({"query": "q", "expect_ids": [7, 7, 8]}) == 2
    assert relevant_count({"query": "q", "expect": ["a", "b"]}) == 2


def test_relevant_count_dedupes_hashes():
    assert relevant_count({"query": "q", "expect_hashes": ["a", "a", "b"]}) == 2
