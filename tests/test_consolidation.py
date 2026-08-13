"""Tests for the production-grade consolidation pipeline.

Covers, bottom-up:

* text normalization + fingerprinting (``bagger.textnorm``)
* near-duplicate detection (``bagger.consolidation.normalize``)
* validation / coercion of untrusted LLM output (``validation.coerce_records``)
* the de-duplication / merge engine (``dedup``)
* error classification + retry (``llm_client`` / ``errors``)
* the ``Consolidator`` itself: insert + provenance, idempotent re-run,
  conservative cursor advance across a chunk failure, dry-run preview
* migration v6 (fingerprint columns, provenance table, exact-duplicate fold)
* CLI rendering for ``consolidate`` / ``memories-stats`` / ``memories-dedup``

No test touches the real ``~/.bagger`` database — integration tests build a
throwaway ``SqliteStorage`` and the CLI tests monkeypatch ``create_storage``
and ``settings.db_path`` to a temp file.
"""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path

import pytest

from bagger.consolidation.consolidator import Consolidator
from bagger.consolidation.dedup import (
    find_fuzzy_clusters,
    merge_topics,
    plan_merge,
)
from bagger.consolidation.errors import (
    ConsolidationError,
    LLMResponseError,
    LLMTransportError,
    LLMUnauthorizedError,
)
from bagger.consolidation.llm_client import (
    OpenAICompatibleClient,
    _records_from_payload,
    _strip_code_fence,
)
from bagger.consolidation.models import MemoryType, RejectReason
from bagger.consolidation.normalize import (
    DEFAULT_FUZZY_THRESHOLD,
    cluster_pairs,
    find_near_duplicate_pairs,
)
from bagger.consolidation.validation import coerce_records
from bagger.storage.migrations import _column_exists, apply_migrations
from bagger.textnorm import char_bigrams, content_fingerprint, jaccard, normalize_content

# ── test fixtures / helpers ─────────────────────────────────


def _open_storage(db_path: Path):
    from bagger.storage.sqlite import SqliteStorage

    storage = SqliteStorage(db_path)
    storage.connect()
    return storage


def _seed_session(storage, source: str = "claude", sid: str = "s1", project: str = "/proj"):
    storage.conn.execute(
        "INSERT INTO sessions (source, id, summary, project_path) VALUES (?,?,?,?)",
        (source, sid, "summary", project),
    )
    storage.conn.commit()


def _seed_events(storage, sid: str = "s1", source: str = "claude", n: int = 3, start: int = 1):
    now = "2026-01-01T00:00:00+00:00"
    for i in range(n):
        eid = f"e{start + i}"
        storage.conn.execute(
            "INSERT INTO events "
            "(event_id, session_id, timestamp, role, content_json, content_text, source) "
            "VALUES (?,?,?,?,?,?,?)",
            (eid, sid, now, "user", "{}", f"message {i}", source),
        )
    storage.conn.commit()


class _ScriptedClient:
    """Returns a fixed list of record dicts for every chunk (offline, scriptable)."""

    def __init__(self, records):
        self.records = [dict(r) for r in records]
        self.calls = 0

    def extract(self, system_prompt, user_content, response_schema):
        self.calls += 1
        return self.records


class _FlakyClient:
    """Raises on the Nth ``extract`` call to simulate a transient chunk failure."""

    def __init__(self, records_per_call, fail_on_call):
        self.records_per_call = [dict(r) for r in records_per_call]
        self.fail_on_call = fail_on_call
        self.calls = 0

    def extract(self, system_prompt, user_content, response_schema):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise ConsolidationError("simulated chunk failure")
        return [dict(r) for r in self.records_per_call]


# ── textnorm ────────────────────────────────────────────────


def test_normalize_content_strips_punctuation_and_whitespace():
    assert normalize_content("  Hello, World!  ") == "helloworld"
    assert normalize_content("测试：标点。") == "测试标点"
    assert normalize_content("Ｆｕｌｌｗｉｄｔｈ") == "fullwidth"  # NFKC fold


def test_content_fingerprint_type_scoped_and_stable():
    a = content_fingerprint("fact", "相同内容")
    b = content_fingerprint("fact", "相同内容")
    assert a == b
    assert len(a) == 16
    # same content, different type -> distinct cognitive units, distinct hash
    assert a != content_fingerprint("decision", "相同内容")


def test_char_bigrams_and_jaccard():
    assert char_bigrams("ab") == frozenset({"ab"})
    assert char_bigrams("") == frozenset()
    assert jaccard("abc", "abc") == 1.0
    assert jaccard("abc", "xyz") == 0.0
    mid = jaccard("abcd", "abce")
    assert 0.0 < mid < 1.0


# ── normalize (fuzzy detection) ─────────────────────────────


def test_default_fuzzy_threshold_is_conservative():
    assert 0.0 < DEFAULT_FUZZY_THRESHOLD <= 1.0
    assert DEFAULT_FUZZY_THRESHOLD >= 0.7


def test_find_near_duplicate_pairs_groups_paraphrases():
    items = [
        (1, "fact", "我喜欢用 Python 写单元测试"),
        (2, "fact", "我喜欢使用 Python 写单元测试"),
        (3, "fact", "今天天气非常好"),
    ]
    pairs = find_near_duplicate_pairs(items, threshold=0.5)
    pair_ids = {(a, b) for a, b, _ in pairs}
    assert (1, 2) in pair_ids
    assert (1, 3) not in pair_ids and (2, 3) not in pair_ids


def test_cluster_pairs_unions_transitive_edges():
    pairs = [
        (1, 2, 0.8),
        (2, 3, 0.8),
    ]
    clusters = cluster_pairs(pairs)
    merged = [c for c in clusters if 1 in c and 2 in c and 3 in c]
    assert merged
    assert all(len(c) >= 2 for c in clusters)


# ── validation.coerce_records ───────────────────────────────


def test_coerce_records_keeps_valid_and_rejects_branches():
    valid = {"e1", "e2"}
    raw = [
        {
            "type": "fact",
            "content": "这是一个有效的记忆事实",
            "topics": ["测试, pytest"],
            "confidence": 0.8,
            "event_id": "e1",
        },
        {"type": "banana", "content": "非法类型", "confidence": 0.5},
        {"type": "fact", "content": "", "confidence": 0.5},
        {"type": "fact", "content": "短", "confidence": 0.5},  # len 1 < MIN
        {
            "type": "decision",
            "content": "一个合理的决策内容",
            "confidence": 0.6,
            "event_id": "e999",  # hallucinated -> cleared
        },
    ]
    records, rejects = coerce_records(raw, source="claude", session_id="s1", valid_event_ids=valid)
    assert len(records) == 2  # the fact and the (cleared) decision
    reasons = {r.reason for r in rejects}
    assert RejectReason.UNKNOWN_TYPE in reasons
    assert RejectReason.EMPTY_CONTENT in reasons
    assert RejectReason.CONTENT_TOO_SHORT in reasons
    # comma inside a topic is rewritten to a space so storage stays unambiguous
    assert records[0].topics == ["测试", "pytest"]
    decision = next(r for r in records if r.type == MemoryType.DECISION)
    assert decision.event_id is None


def test_coerce_records_deduplicates_within_batch_keeping_best():
    raw = [
        {"type": "fact", "content": "重复内容", "confidence": 0.5},
        {"type": "fact", "content": "重复内容", "confidence": 0.9},
    ]
    records, rejects = coerce_records(raw, source="claude", session_id="s1", valid_event_ids=set())
    assert len(records) == 1
    assert records[0].confidence == 0.9  # higher confidence wins
    assert len(rejects) == 1
    assert rejects[0].reason == RejectReason.DUPLICATE_IN_BATCH


# ── dedup engine ─────────────────────────────────────────────


def test_merge_topics_unions_and_caps():
    assert merge_topics(["a", "b"], ["b", "c"]) == ["a", "b", "c"]


def test_plan_merge_applies_corroboration_rules():
    keeper = {
        "confidence": 0.5,
        "topics": "x",
        "created_at": "2026-02-01",
        "merge_count": 1,
        "relevance": 0.8,
    }
    dup = {
        "confidence": 0.9,
        "topics": "y",
        "created_at": "2026-01-01",
        "merge_count": 2,
        "relevance": 0.6,
    }
    plan = plan_merge(keeper, [dup])
    assert plan["confidence"] == 0.9  # max
    assert set(plan["topics"].split(",")) == {"x", "y"}
    assert plan["created_at"] == "2026-01-01"  # earliest
    assert plan["merge_count"] == 3  # sum
    assert plan["relevance"] == 0.8  # max


def test_find_fuzzy_clusters_identifies_keeper_and_duplicates():
    rows = [
        {"id": 10, "type": "fact", "content": "我喜欢用 Python 写单元测试", "topics": "python"},
        {"id": 20, "type": "fact", "content": "我喜欢使用 Python 写单元测试", "topics": "python"},
    ]
    clusters, _ = find_fuzzy_clusters(rows, threshold=0.5)
    assert len(clusters) == 1
    c = clusters[0]
    assert c.keeper_id == 10  # lowest id is the canonical keeper
    assert c.duplicate_ids == [20]
    assert c.keeper_content == "我喜欢用 Python 写单元测试"


# ── errors ──────────────────────────────────────────────────


def test_error_retryable_flags():
    assert LLMTransportError("x").retryable is True
    assert LLMUnauthorizedError("x").retryable is False
    assert LLMResponseError("x").retryable is False
    assert ConsolidationError("x").retryable is False


# ── llm_client ──────────────────────────────────────────────


def test_strip_code_fence_handles_wrapped_json():
    assert _strip_code_fence('```json\n{"a":1}\n```') == '{"a":1}'
    assert _strip_code_fence('{"a":1}') == '{"a":1}'


def test_records_from_payload_handles_shapes():
    assert _records_from_payload({"records": [{"content": "x"}]}) == [{"content": "x"}]
    assert _records_from_payload([{"content": "x"}]) == [{"content": "x"}]
    assert _records_from_payload({"content": "y", "type": "fact"}) == [
        {"content": "y", "type": "fact"}
    ]
    assert _records_from_payload({"foo": 1}) == []
    with pytest.raises(LLMResponseError):
        _records_from_payload("not a dict")


def test_extract_retries_on_transport_error_then_succeeds():
    sleeps = []
    client = OpenAICompatibleClient(
        "http://x", "key", "m", max_retries=2, sleep=lambda s: sleeps.append(s)
    )
    payload = {
        "choices": [
            {
                "message": {
                    "content": '{"records":[{"type":"fact","content":"hi","topics":["t"],"confidence":0.5}]}'
                }
            }
        ]
    }
    state = {"n": 0}

    def flaky(body):
        state["n"] += 1
        if state["n"] <= 2:
            raise LLMTransportError("retry me")
        return payload

    client._post = flaky
    records = client.extract("s", "u", {})
    assert records == [{"type": "fact", "content": "hi", "topics": ["t"], "confidence": 0.5}]
    assert state["n"] == 3  # initial attempt + 2 retries
    assert len(sleeps) == 2


def test_extract_does_not_retry_terminal_error():
    client = OpenAICompatibleClient("http://x", "key", "m", max_retries=3, sleep=lambda s: None)
    client._post = lambda body: (_ for _ in ()).throw(LLMUnauthorizedError("no key"))
    with pytest.raises(LLMUnauthorizedError):
        client.extract("s", "u", {})


def test_post_classifies_status_codes(monkeypatch):
    import urllib.error
    from unittest.mock import MagicMock, patch

    client = OpenAICompatibleClient("http://x", "key", "m")
    ok = MagicMock()
    ok.__enter__.return_value = ok
    ok.read.return_value = b'{"choices":[{"message":{"content":"{}"}}]}'
    with patch("urllib.request.urlopen", return_value=ok):
        assert client._post({"model": "m", "messages": []}) == {
            "choices": [{"message": {"content": "{}"}}]
        }

    unauthorized = urllib.error.HTTPError("u", 401, "nope", {}, None)
    with (
        patch("urllib.request.urlopen", side_effect=unauthorized),
        pytest.raises(LLMUnauthorizedError),
    ):
        client._post({})

    busy = urllib.error.HTTPError("u", 503, "busy", {}, None)
    with patch("urllib.request.urlopen", side_effect=busy), pytest.raises(LLMTransportError):
        client._post({})


# ── Consolidator integration ────────────────────────────────


def test_consolidate_inserts_records_with_provenance():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        storage = _open_storage(Path(d) / "b.db")
        _seed_session(storage, sid="s1")
        _seed_events(storage, sid="s1", n=3)
        client = _ScriptedClient(
            [
                {
                    "type": "fact",
                    "content": "用户偏好用 pytest 跑测试",
                    "topics": ["测试", "pytest"],
                    "confidence": 0.8,
                    "event_id": "e1",
                },
                {
                    "type": "decision",
                    "content": "选定 SQLite 作为本地存储",
                    "topics": ["存储"],
                    "confidence": 0.6,
                    "event_id": "e2",
                },
            ]
        )
        cons = Consolidator(storage, client)
        report = cons.run(full=True)

        assert report.records_extracted == 2
        assert report.records_inserted == 2
        assert report.records_merged == 0

        rows = storage.conn.execute("SELECT * FROM memory_records").fetchall()
        assert len(rows) == 2
        assert all(r["content_hash"] for r in rows)
        assert storage.conn.execute("SELECT COUNT(*) FROM memory_provenance").fetchone()[0] == 2
        storage.close()


def test_consolidate_is_idempotent_and_grows_provenance():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        storage = _open_storage(Path(d) / "b.db")
        _seed_session(storage, sid="s1")
        _seed_events(storage, sid="s1", n=3)

        client1 = _ScriptedClient(
            [
                {
                    "type": "fact",
                    "content": "合并事实记录内容",
                    "topics": ["t"],
                    "confidence": 0.7,
                    "event_id": "e1",
                }
            ]
        )
        cons = Consolidator(storage, client1)
        cons.run(full=True)
        assert storage.conn.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0] == 1
        assert (
            storage.conn.execute(
                "SELECT merge_count FROM memory_records WHERE content='合并事实记录内容'"
            ).fetchone()[0]
            == 1
        )
        assert storage.conn.execute("SELECT COUNT(*) FROM memory_provenance").fetchone()[0] == 1

        # Re-run with the same event id: no new row, no new provenance, count bumps.
        cons.run(full=True)
        assert (
            storage.conn.execute(
                "SELECT merge_count FROM memory_records WHERE content='合并事实记录内容'"
            ).fetchone()[0]
            == 2
        )
        assert storage.conn.execute("SELECT COUNT(*) FROM memory_provenance").fetchone()[0] == 1

        # Re-run with a *different* event id: provenance grows, count bumps again.
        client2 = _ScriptedClient(
            [
                {
                    "type": "fact",
                    "content": "合并事实记录内容",
                    "topics": ["t"],
                    "confidence": 0.7,
                    "event_id": "e2",
                }
            ]
        )
        Consolidator(storage, client2).run(full=True)
        assert (
            storage.conn.execute(
                "SELECT merge_count FROM memory_records WHERE content='合并事实记录内容'"
            ).fetchone()[0]
            == 3
        )
        assert storage.conn.execute("SELECT COUNT(*) FROM memory_provenance").fetchone()[0] == 2
        storage.close()


def test_consolidate_cursor_advances_only_before_first_failure():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        storage = _open_storage(Path(d) / "b.db")
        _seed_session(storage, sid="s1")
        _seed_events(storage, sid="s1", n=4)  # 2 chunks of 2

        flaky = _FlakyClient(
            records_per_call=[
                {
                    "type": "fact",
                    "content": "分块提取记录",
                    "topics": ["t"],
                    "confidence": 0.5,
                    "event_id": "e1",
                }
            ],
            fail_on_call=2,
        )
        report = Consolidator(storage, flaky, chunk_size=2).run(full=True)

        assert report.chunks_total == 2
        assert report.chunks_ok == 1
        assert report.chunks_failed == 1
        assert report.sessions_failed == 1

        # Cursor must stop at chunk 1's last event (id 2), not jump over the gap.
        cursor = storage.conn.execute(
            "SELECT last_event_id FROM consolidation_state WHERE source='claude' AND session_id='s1'"
        ).fetchone()
        assert cursor["last_event_id"] == 2
        assert storage.conn.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0] == 1

        # Resume with a working client: only events 3,4 are processed.
        resume = _ScriptedClient(
            [
                {
                    "type": "fact",
                    "content": "恢复后记录内容",
                    "topics": ["t"],
                    "confidence": 0.5,
                    "event_id": "e3",
                }
            ]
        )
        report2 = Consolidator(storage, resume, chunk_size=2).run(full=False)
        assert report2.records_inserted == 1
        cursor2 = storage.conn.execute(
            "SELECT last_event_id FROM consolidation_state WHERE source='claude' AND session_id='s1'"
        ).fetchone()
        assert cursor2["last_event_id"] == 4
        storage.close()


def test_consolidate_dry_run_produces_previews_without_writes():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        storage = _open_storage(Path(d) / "b.db")
        _seed_session(storage, sid="s1")
        _seed_events(storage, sid="s1", n=2)
        client = _ScriptedClient(
            [{"type": "fact", "content": "dry 内容", "topics": ["t"], "confidence": 0.5}]
        )
        report = Consolidator(storage, client).run(full=True, dry_run=True)
        assert report.previews
        assert storage.conn.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0] == 0
        storage.close()


# ── migration v6 ────────────────────────────────────────────


def test_migration_v6_folds_exact_duplicates_and_is_idempotent():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    # A pre-v6 (v5) memory_records shape: no fingerprint columns, no provenance.
    conn.execute(
        "CREATE TABLE memory_records ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT NOT NULL,"
        " content TEXT NOT NULL, topics TEXT NOT NULL DEFAULT '',"
        " confidence REAL NOT NULL DEFAULT 0.5, source TEXT NOT NULL DEFAULT 'claude',"
        " session_id TEXT NOT NULL, event_id TEXT, created_at TEXT NOT NULL,"
        " relevance REAL NOT NULL DEFAULT 1.0, archived INTEGER NOT NULL DEFAULT 0)"
    )
    conn.execute("PRAGMA user_version = 5")
    conn.execute(
        "INSERT INTO memory_records (type, content, topics, confidence, source, session_id, created_at)"
        " VALUES ('fact', '同一个事实', 'a,b', 0.7, 'claude', 's1', '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO memory_records (type, content, topics, confidence, source, session_id, created_at)"
        " VALUES ('fact', '同一个事实', 'b,c', 0.9, 'claude', 's2', '2026-02-01T00:00:00+00:00')"
    )

    apply_migrations(conn, backfill_event_edges=lambda: None)

    assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
    assert _column_exists(conn, "memory_records", "content_hash")
    assert _column_exists(conn, "memory_records", "merge_count")

    rows = conn.execute("SELECT * FROM memory_records").fetchall()
    assert len(rows) == 1  # the two exact duplicates collapsed into one
    keeper = rows[0]
    assert keeper["id"] == 1  # lowest id kept
    assert keeper["merge_count"] == 2
    assert set(keeper["topics"].split(",")) == {"a", "b", "c"}
    idx = conn.execute("PRAGMA index_list(memory_records)").fetchall()
    assert any(r["name"] == "idx_memory_records_hash" for r in idx)
    # Provenance preserves both original (source, session) trails.
    assert conn.execute("SELECT COUNT(*) FROM memory_provenance").fetchone()[0] >= 1

    # Re-running on the now-v6 DB must be a safe no-op.
    apply_migrations(conn, backfill_event_edges=lambda: None)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 7
    assert conn.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0] == 1


# ── CLI rendering (offline, temp DB) ────────────────────────


def test_cli_consolidate_stats_and_dedup_render(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from bagger.cli import main as cli_main

    db = tmp_path / "bagger.db"
    storage = _open_storage(db)
    _seed_session(storage, sid="s1")
    _seed_events(storage, sid="s1", n=2)
    storage.close()

    # ``settings`` is a frozen pydantic model, so replace the module-level
    # reference with a lightweight stand-in that only needs ``db_path``. The
    # mock paths exercised here never read the other settings fields.
    class _FakeSettings:
        db_path = db

    monkeypatch.setattr(cli_main, "settings", _FakeSettings())
    monkeypatch.setattr(cli_main, "create_storage", lambda: _open_storage(db))

    runner = CliRunner()

    r1 = runner.invoke(cli_main.cli, ["consolidate", "--mock"])
    assert r1.exit_code == 0, r1.output
    assert "Consolidation complete" in r1.output
    assert "extracted=2" in r1.output

    r2 = runner.invoke(cli_main.cli, ["memories-stats"])
    assert r2.exit_code == 0, r2.output
    assert "Memory corpus statistics" in r2.output

    # Seed two near-duplicate records so the dedup preview has something to show.
    st = _open_storage(db)
    st.conn.execute(
        "INSERT INTO memory_records "
        "(type, content, topics, confidence, source, session_id, created_at, content_hash, merge_count, relevance) "
        "VALUES ('fact', '我喜欢用 Python 写测试', 'python', 0.6, 'claude', 's1', "
        "'2026-01-01T00:00:00+00:00', 'dupA', 1, 1.0)"
    )
    st.conn.execute(
        "INSERT INTO memory_records "
        "(type, content, topics, confidence, source, session_id, created_at, content_hash, merge_count, relevance) "
        "VALUES ('fact', '我喜欢使用 Python 写测试', 'python', 0.6, 'claude', 's1', "
        "'2026-01-01T00:00:00+00:00', 'dupB', 1, 1.0)"
    )
    st.close()

    r3 = runner.invoke(cli_main.cli, ["memories-dedup", "--dry-run", "--threshold", "0.5"])
    assert r3.exit_code == 0, r3.output
    assert "Clusters:" in r3.output
