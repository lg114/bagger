"""Tests for memory-FTS query expansion (OR-expand-narrow, decided 2026-08-26).

Contracts under test:

1. ``expand_terms`` fires on full-phrase matches only — token-level
   substrings (``联网`` inside ``不联网``) must NOT trigger expansion;
2. queries with no matching phrase keep the exact original behavior
   (patching the expansion to return nothing must not change results);
3. the two target lexical-gap queries recall docs that use the expansion
   vocabulary but never the queried word itself (``瘦身`` → ``sidecar`` /
   ``打包``, ``不联网`` → ``本地``).
"""

from __future__ import annotations

import pytest

from bagger.embedding.fake import FakeEmbedder
from bagger.services.embed import EmbedService
from bagger.storage import query_expansion as qe
from bagger.storage.query_expansion import MEMORY_QUERY_SYNONYMS, expand_terms
from bagger.storage.sqlite import SqliteStorage, _tokenize_for_fts
from bagger.textnorm import content_fingerprint

pytest.importorskip("jieba")


def _seed(storage: SqliteStorage, rows: list[tuple[str, str, str, str, str]]) -> None:
    now = "2026-08-26T00:00:00+00:00"
    # Tests focus on FTS recall, not FK integrity; seeds may omit sessions rows.
    storage._conn.execute("PRAGMA foreign_keys=OFF")
    for r in rows:
        storage._conn.execute(
            "INSERT INTO memory_records"
            "(type, content, topics, confidence, source, session_id, created_at, content_hash) "
            "VALUES (?, ?, ?, 1.0, ?, ?, ?, ?)",
            (r[0], r[1], r[2], r[3], r[4], now, content_fingerprint(r[0], r[1])),
        )
    storage._conn.commit()


@pytest.fixture
def storage(tmp_path):
    s = SqliteStorage(tmp_path / "bagger.db")
    s.connect()
    yield s
    s.close()


# --- pure function ---------------------------------------------------------


def test_expand_terms_full_phrase_triggers():
    assert expand_terms("桌面应用体积太大怎么瘦身") == ["sidecar", "打包"]
    assert expand_terms("不联网也能用的个人工具") == ["本地"]


def test_expand_terms_token_substring_does_not_trigger():
    """``联网`` is a substring of the phrase ``不联网`` — it must not fire.

    This is the precision guard: docs like "联网检查受限" are antonyms of the
    intended expansion and must not be pulled in by a token-level match.
    """
    assert expand_terms("联网检查受限怎么办") == []
    assert expand_terms("要联网的部署方案") == []


def test_expand_terms_unrelated_query_returns_empty():
    assert expand_terms("怎么选存储向量的数据库") == []
    assert expand_terms("hybrid search pipeline") == []


def test_expand_terms_deduplicates_across_phrases():
    table = {"瘦身": ("sidecar", "打包"), "减体积": ("打包", "压缩")}
    assert expand_terms("瘦身且减体积", table) == ["sidecar", "打包", "压缩"]


def test_default_table_is_the_decided_narrow_table():
    assert MEMORY_QUERY_SYNONYMS == {"瘦身": ("sidecar", "打包"), "不联网": ("本地",)}


# --- integration: search_memory_fts ----------------------------------------


def test_expansion_recalls_sidecar_doc_for_shoushen_query(storage):
    """The 瘦身 gap: relevant docs say sidecar/打包, never 瘦身 (0 corpus hits)."""
    _seed(
        storage,
        [
            ("fact", "用 PyInstaller 打包后端并作为 Tauri sidecar 分发", "打包", "claude", "s1"),
            ("fact", "黄鹤楼登高见闻", "travel", "claude", "s2"),
        ],
    )
    EmbedService(storage, FakeEmbedder(model="fake")).backfill(reindex_fts=True)

    hits = storage.search_memory_fts("桌面应用体积太大怎么瘦身", limit=10)
    contents = [h["content"] for h in hits]
    assert "用 PyInstaller 打包后端并作为 Tauri sidecar 分发" in contents, (
        "expansion tokens (sidecar/打包) must recall the lexical-gap doc"
    )


def test_expansion_recalls_local_doc_for_offline_query(storage):
    """The 不联网 gap: relevant docs say 本地 (18 corpus hits, all 4 expected docs)."""
    _seed(
        storage,
        [
            ("fact", "所有数据存本地 SQLite 不需要任何网络服务", "本地", "claude", "s1"),
            ("fact", "黄鹤楼登高见闻", "travel", "claude", "s2"),
        ],
    )
    EmbedService(storage, FakeEmbedder(model="fake")).backfill(reindex_fts=True)

    hits = storage.search_memory_fts("不联网也能用的个人工具", limit=10)
    contents = [h["content"] for h in hits]
    assert "所有数据存本地 SQLite 不需要任何网络服务" in contents, (
        "expansion token (本地) must recall the lexical-gap doc"
    )


def test_unrelated_query_results_unchanged_without_expansion(storage, monkeypatch):
    """Patching the expansion away must not change results for a cold query."""
    _seed(
        storage,
        [
            ("fact", "向量数据库选型对比记录", "storage", "claude", "s1"),
            ("fact", "清华园漫步路线记录", "travel", "claude", "s2"),
        ],
    )
    EmbedService(storage, FakeEmbedder(model="fake")).backfill(reindex_fts=True)

    query = "怎么选存储向量的数据库"
    with_expansion = storage.search_memory_fts(query, limit=10)

    import bagger.storage.sqlite as sqlite_mod

    monkeypatch.setattr(sqlite_mod, "expand_terms", lambda q, table=None: [])
    without = storage.search_memory_fts(query, limit=10)
    monkeypatch.undo()

    assert with_expansion == without, "cold query must keep the exact original results"
    # And structurally: the table never matches this query anyway.
    assert qe.expand_terms(query) == []


def test_antonym_noise_documented_behavior(storage):
    """Known trade-off, measured on the real corpus (2026-08-26): the antonym
    doc (``本地沙箱…联网检查受限``) was already in the baseline top-10 for the
    不联网 query (it matches the raw ``联网`` query token at rank 4); expansion
    re-ranks it up (to rank 1) while pulling the true local-first doc from
    rank 9 to rank 2. This test pins the defensible invariants:

    1. the relevant local-first doc is recalled in the top-5 (the whole point
       of the expansion — baseline had it at rank 9);
    2. the antonym is NOT newly introduced by the expansion: it already
       matches the raw query tokens without any expansion tokens.
    """
    _seed(
        storage,
        [
            ("fact", "所有数据存本地 SQLite 不需要任何网络服务", "本地", "claude", "s1"),
            ("fact", "本地沙箱环境里联网检查受限的排查记录", "环境", "claude", "s2"),
        ],
    )
    EmbedService(storage, FakeEmbedder(model="fake")).backfill(reindex_fts=True)

    query = "不联网也能用的个人工具"
    hits = storage.search_memory_fts(query, limit=10)
    contents = [h["content"] for h in hits]
    local_first = "所有数据存本地 SQLite 不需要任何网络服务"

    # 1. relevant doc recalled in top-5.
    assert local_first in contents[:5], "expansion must recall the local-first doc"

    # 2. antonym matches the raw query token (联网) without expansion tokens.
    raw_tokens = set(storage._search._tokenized_memory_fts_query(query).split())
    antonym_tokens = set(_tokenize_for_fts("本地沙箱环境里联网检查受限的排查记录").split())
    assert raw_tokens & antonym_tokens, (
        "antonym doc must match raw query tokens (pre-existing noise, not new)"
    )
