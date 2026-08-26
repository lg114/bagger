"""Behavioral tests for the memory-FTS tuning (content×2 BM25 + search-mode tokenization).

Covers three contracts decided on 2026-08-26:

1. memory search tokenizes queries with jieba ``cut_for_search`` (sub-words of
   long terms broaden lexical recall — R@10 on the real corpus);
2. events/sessions search keeps exact-mode tokenization (``_tokenized_fts_query``)
   so its keyword-oriented behavior does not change;
3. BM25 column weights favor content (2.0) over topics (1.0) — a content match
   outranks an equally-good topics-only match.
"""

from __future__ import annotations

import pytest

from bagger.embedding.fake import FakeEmbedder
from bagger.services.embed import EmbedService
from bagger.services.hybrid_search import HybridSearch
from bagger.storage.sqlite import SqliteStorage
from bagger.textnorm import content_fingerprint

pytest.importorskip("jieba")


def _seed(storage: SqliteStorage, rows: list[tuple[str, str, str, str, str]]) -> None:
    now = "2026-08-26T00:00:00+00:00"
    # Tests focus on FTS ranking, not FK integrity; seeds may omit sessions rows.
    storage._conn.execute("PRAGMA foreign_keys=OFF")
    for r in rows:
        storage._conn.execute(
            "INSERT INTO memory_records"
            "(type, content, topics, confidence, source, session_id, created_at, content_hash) "
            "VALUES (?, ?, ?, 1.0, ?, ?, ?, ?)",
            (r[0], r[1], r[2], r[3], r[4], now, content_fingerprint(r[0], r[1])),
        )
    storage._conn.commit()


def _fts(storage: SqliteStorage, query: str, limit: int = 10) -> list[dict]:
    return storage.search_memory_fts(query, limit=limit)


@pytest.fixture
def storage(tmp_path):
    s = SqliteStorage(tmp_path / "bagger.db")
    s.connect()
    yield s
    s.close()


def test_memory_query_uses_search_mode_tokenization(storage):
    """Querying a long compound word must recall sub-word-only content.

    ``清华园漫步`` contains ``清华`` but not the compound ``清华大学``.
    Exact-mode tokenization turns the query into a single ``清华大学`` token
    and misses it; search mode also emits ``清华``, which matches.
    """
    _seed(
        storage,
        [
            ("fact", "清华园漫步路线记录", "travel", "claude", "s1"),
            ("fact", "黄鹤楼登高见闻", "travel", "claude", "s2"),
        ],
    )
    EmbedService(storage, FakeEmbedder(model="fake")).backfill(reindex_fts=True)

    hits = _fts(storage, "清华大学")
    assert hits, "search-mode sub-word tokens must recall 清华园 content"
    assert "清华园漫步路线记录" in [h["content"] for h in hits]


def test_tokenization_modes_differ_only_for_memory(storage):
    """Method-level contract: events keep exact mode, memory uses search mode."""
    idx = storage._search
    # Exact mode keeps the compound as one token.
    assert idx._tokenized_fts_query("清华大学") == "清华大学"
    # Search mode splits it into sub-words (order per jieba dictionary).
    memory_tokens = idx._tokenized_memory_fts_query("清华大学").split()
    assert "清华" in memory_tokens
    assert "大学" in memory_tokens
    assert "清华大学" in memory_tokens


def test_content_match_outranks_topics_only_match(storage):
    """BM25 weight 2.0 on content must beat an equally-good topics-only match.

    Record A carries the query term in content; record B carries it only in
    topics. With equal column weights B's short tag text can win on BM25
    length normalization; with content×2 it must not.
    """
    _seed(
        storage,
        [
            ("fact", "云原生架构实践总结", "杂项", "claude", "s1"),
            ("fact", "杂项记录本整理", "云原生", "claude", "s2"),
            ("fact", "一段与查询完全无关的较长文本内容用于稀释平均列长度", "其他", "claude", "s3"),
        ],
    )
    EmbedService(storage, FakeEmbedder(model="fake")).backfill(reindex_fts=True)

    hits = _fts(storage, "云原生")
    assert hits, "query term appears in both records — at least one must match"
    assert hits[0]["content"] == "云原生架构实践总结", (
        "content match (weight 2.0) must rank above topics-only match (weight 1.0)"
    )


def test_hybrid_search_fts_mode_uses_tuned_pipeline(storage):
    """The HybridSearch fts path delegates to the tuned search_memory_fts."""
    _seed(
        storage,
        [("fact", "清华园漫步路线记录", "travel", "claude", "s1")],
    )
    embedder = FakeEmbedder(model="fake")
    EmbedService(storage, embedder).backfill(reindex_fts=True)
    hs = HybridSearch(storage, embedder)

    res = hs.search("清华大学", mode="fts", limit=5)
    assert res, "hybrid fts mode must go through the memory search pipeline"
    assert "清华园漫步路线记录" in [r["content"] for r in res]
