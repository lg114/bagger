"""Tests for memory-FTS query expansion (OR-expand-narrow, decided 2026-08-26)
and the conflict down-weight that fixes expansion-induced mis-ranking
(decided 2026-08-27).

Contracts under test:

1. ``expand_terms`` fires on full-phrase matches only — token-level
   substrings (``联网`` inside ``不联网``) must NOT trigger expansion;
2. ``conflict_words_for`` returns the antonym lexicon only for a triggered
   phrase (``不联网``), else ``None`` — so non-expansion queries are never
   demoted;
3. queries with no matching phrase keep the exact original behavior
   (patching the expansion to return nothing must not change results);
4. the two target lexical-gap queries recall docs that use the expansion
   vocabulary but never the queried word itself (``瘦身`` → ``sidecar`` /
   ``打包``, ``不联网`` → ``本地``);
5. the conflict lexicon demotes antonym docs (``本地沙箱…联网检查受限``) to
   the end of the result list, so they cannot be pushed to rank 1 by the
   expansion token alone, while the relevant local-first doc ranks first.
"""

from __future__ import annotations

import pytest

from bagger.embedding.fake import FakeEmbedder
from bagger.services.embed import EmbedService
from bagger.storage import query_expansion as qe
from bagger.storage.query_expansion import (
    MEMORY_QUERY_CONFLICTS,
    MEMORY_QUERY_SYNONYMS,
    conflict_words_for,
    expand_terms,
)
from bagger.storage.sqlite import SqliteStorage
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


def test_conflict_words_for_triggers_on_phrase():
    assert conflict_words_for("不联网也能用的个人工具") == ("联网检查", "受限", "沙箱")
    assert conflict_words_for("桌面应用体积太大怎么瘦身") is None
    assert conflict_words_for("怎么选存储向量的数据库") is None


def test_default_conflict_table_is_signed():
    assert MEMORY_QUERY_CONFLICTS == {"不联网": ("联网检查", "受限", "沙箱")}


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


def test_conflict_downweight_demotes_antonym_below_relevant(storage):
    """Conflict lexicon (不联网 -> 联网检查/受限/沙箱) must sink the antonym
    doc below the genuinely relevant local-first doc, even when the antonym
    would otherwise rank first on raw BM25 (it matches the raw ``联网`` token).
    This is the fix for the expansion-induced mis-ranking reported 2026-08-27.
    """
    _seed(
        storage,
        [
            ("fact", "所有数据存本地优先 SQLite 不需要任何网络服务", "本地", "claude", "s1"),
            ("fact", "本地沙箱环境里联网检查受限的排查记录", "环境", "claude", "s2"),
            ("fact", "黄鹤楼登高见闻", "travel", "claude", "s3"),
        ],
    )
    EmbedService(storage, FakeEmbedder(model="fake")).backfill(reindex_fts=True)

    query = "不联网也能用的个人工具"
    hits = storage.search_memory_fts(query, limit=10)
    contents = [h["content"] for h in hits]
    local_first = "所有数据存本地优先 SQLite 不需要任何网络服务"
    antonym = "本地沙箱环境里联网检查受限的排查记录"

    # Relevant doc must outrank the antonym (and sit at rank 1).
    assert contents[0] == local_first, "relevant doc must outrank the antonym"
    assert contents.index(local_first) < contents.index(antonym), (
        "conflict lexicon must demote the antonym below the relevant doc"
    )
    # Antonym is sunk to the end of the list.
    assert contents[-1] == antonym, "antonym must be sunk to the end of the list"


def test_conflict_downweight_only_fires_on_expansion(storage):
    """A query containing conflict words (受限/沙箱) but NOT the expansion
    phrase (不联网) must NOT be demoted — demotion is gated on expansion
    triggering, so unrelated queries keep their exact BM25 order."""
    _seed(
        storage,
        [
            ("fact", "本地沙箱环境里联网检查受限的排查记录", "环境", "claude", "s1"),
            ("fact", "黄鹤楼登高见闻", "travel", "claude", "s2"),
        ],
    )
    EmbedService(storage, FakeEmbedder(model="fake")).backfill(reindex_fts=True)

    query = "沙箱环境受限怎么排查"
    hits = storage.search_memory_fts(query, limit=10)
    contents = [h["content"] for h in hits]
    # No 不联网 phrase -> no expansion -> no demotion; antonym stays by BM25.
    assert contents[0] == "本地沙箱环境里联网检查受限的排查记录", (
        "non-expansion query must not be demoted"
    )


def test_conflict_overfetch_rescues_clean_doc_beyond_limit(storage, monkeypatch):
    """Regression for the over-fetch boundary (gc, 2026-08-27).

    When antonym docs occupy the top of the raw BM25 order, the original LIMIT
    would cut off a clean relevant doc sitting just past it — demoting the
    antonyms to the tail can't help if the clean doc was never fetched. With
    conflict demotion the query over-fetches (LIMIT = limit*2) so the demoted
    antonym tail can't starve that clean doc.

    This corpus is tuned so the clean doc ranks 4th by raw BM25 (matches only
    the expansion token 本地 once, long doc) while 3 antonym docs rank above it
    (they also match the raw 联网 token + conflict words). The antonym-only
    LIMIT=3 path must NOT surface the clean doc; the over-fetch path must.
    """
    _seed(
        storage,
        [
            ("fact", "本地沙箱联网检查受限", "环境", "claude", "sd0"),
            ("fact", "本地沙箱联网检查受限排查", "环境", "claude", "sd1"),
            ("fact", "本地沙箱里联网检查受限环境", "环境", "claude", "sd2"),
            (
                "fact",
                "项目所有数据存本地 SQLite 数据库做持久化存储架构设计",
                "本地",
                "claude",
                "sc",
            ),
        ],
    )
    EmbedService(storage, FakeEmbedder(model="fake")).backfill(reindex_fts=True)

    query = "不联网也能用的个人工具"
    clean = "项目所有数据存本地 SQLite 数据库做持久化存储架构设计"

    # Simulate the pre-fix behavior: no conflict table => LIMIT=limit, no
    # demotion. The clean doc (rank 4 by raw BM25) stays cut off at LIMIT=3.
    import bagger.storage.sqlite as sqlite_mod

    monkeypatch.setattr(sqlite_mod, "conflict_words_for", lambda q, table=None: None)
    raw = storage.search_memory_fts(query, limit=3)
    monkeypatch.undo()
    assert clean not in [h["content"] for h in raw], (
        "without over-fetch the clean doc beyond LIMIT must stay cut off"
    )

    # With conflict demotion (over-fetch active) the clean doc is rescued.
    over = storage.search_memory_fts(query, limit=3)
    assert clean in [h["content"] for h in over[:3]], (
        "over-fetch must rescue the clean doc past the original LIMIT"
    )
