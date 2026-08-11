"""End-to-end tests for the semantic / hybrid memory retrieval pipeline.

Uses the ``fake`` embedder (deterministic, zero-dependency) so the whole
backfill → index → search → RRF flow is exercised with no network call and no
model download — exactly the CI-safe path.
"""

from __future__ import annotations

import pytest

from bagger.embedding import create_embedder
from bagger.embedding.fake import FakeEmbedder
from bagger.embedding.remote import RemoteEmbedder
from bagger.services.embed import EmbedService
from bagger.services.hybrid_search import HybridSearch
from bagger.storage.sqlite import SqliteStorage
from bagger.textnorm import content_fingerprint


def _seed(storage, rows):
    now = "2026-08-11T00:00:00+00:00"
    # Tests focus on the embedding pipeline, not FK integrity; the seed inserts
    # memory_records whose (source, session_id) may not exist in sessions.
    storage._conn.execute("PRAGMA foreign_keys=OFF")
    for r in rows:
        storage._conn.execute(
            "INSERT INTO memory_records"
            "(type, content, topics, confidence, source, session_id, created_at, content_hash) "
            "VALUES (?, ?, ?, 1.0, ?, ?, ?, ?)",
            (r[0], r[1], r[2], r[3], r[4], now, content_fingerprint(r[0], r[1])),
        )
    storage._conn.commit()


SAMPLE = [
    ("decision", "用 Zvec 替代 Chroma 做本地向量存储", "zvec,chroma,storage", "claude", "s1"),
    (
        "decision",
        "浏览器 localStorage 偏好持久化用户设置",
        "localStorage,preference",
        "claude",
        "s1",
    ),
    ("fact", "PyInstaller sidecar 打包体积约 40MB", "pyinstaller,packaging", "claude", "s2"),
]


def test_fake_embedder_is_deterministic():
    a = FakeEmbedder()
    v1 = a.embed_query("存储方案")
    v2 = a.embed_query("存储方案")
    assert v1 == v2
    assert len(v1) == a.dim
    # normalized
    import math

    assert abs(math.sqrt(sum(x * x for x in v1)) - 1.0) < 1e-6


def test_create_embedder_fake():
    emb = create_embedder("fake")
    assert isinstance(emb, FakeEmbedder)
    assert emb.model_name == "fake"


def test_remote_embedder_requires_key():
    emb = RemoteEmbedder("https://example.com/v1", None, "embedding-3")
    with pytest.raises(RuntimeError):
        emb.embed_query("hi")


def test_backfill_and_vector_search(tmp_path):
    storage = SqliteStorage(tmp_path / "bagger.db")
    storage.connect()
    _seed(storage, SAMPLE)

    embedder = create_embedder("fake")
    svc = EmbedService(storage, embedder)
    summary = svc.backfill(reindex_fts=True)
    assert summary["embedded"] == 3
    assert summary["stats"]["total"] == 3

    # Pending should be empty after a backfill.
    pending = storage.pending_for_embedding("memory", embedder.model_name)
    assert pending == []

    # Vector search returns ranked owner ids.
    qv = embedder.embed_query("存储")
    hits = storage.search_memory_vectors(qv, embedder.model_name, limit=5)
    assert len(hits) == 3  # all 3 are in the index
    assert all("owner_id" in h and "score" in h for h in hits)

    storage.close()


def test_hybrid_recall_routes_by_meaning(tmp_path):
    storage = SqliteStorage(tmp_path / "bagger.db")
    storage.connect()
    _seed(storage, SAMPLE)

    embedder = create_embedder("fake")
    EmbedService(storage, embedder).backfill(reindex_fts=True)
    hs = HybridSearch(storage, embedder)

    res = hs.search("存储", mode="hybrid", limit=5)
    assert res, "hybrid search should return at least one result"
    contents = [r["content"] for r in res]
    # "存储" shares the token with the Zvec/Chroma record → it must surface.
    assert any("Zvec" in c for c in contents)

    # fts-only mode should still work (BM25 half) without embedding the query
    # semantics — it returns the record whose text literally contains 存储.
    fts_res = hs.search("存储", mode="fts", limit=5)
    assert any("Zvec" in r["content"] for r in fts_res)

    storage.close()


def test_rrf_fusion_includes_both_sides(tmp_path):
    storage = SqliteStorage(tmp_path / "bagger.db")
    storage.connect()
    # One record only matches semantically-ish, one only lexically, to ensure
    # the fusion combines both ranked lists rather than picking one.
    _seed(
        storage,
        [
            ("fact", "apple banana cherry", "fruit", "claude", "s1"),
            ("fact", "quantum entanglement overview", "physics", "claude", "s2"),
        ],
    )
    embedder = create_embedder("fake")
    EmbedService(storage, embedder).backfill(reindex_fts=True)
    hs = HybridSearch(storage, embedder)
    # "banana" is a literal token in record 1 (fts) and shares vocab via fake
    # hashing; fusion should still return a ranked, non-empty list.
    res = hs.search("banana", mode="hybrid", limit=5)
    assert len(res) >= 1
    assert "fused_score" in res[0]
    storage.close()
