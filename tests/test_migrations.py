"""Isolated tests for schema migrations (bagger.storage.migrations)."""

import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bagger.models.event import MemoryEvent, Role
from bagger.storage.migrations import _column_exists, apply_migrations
from bagger.storage.sqlite import SqliteStorage


def test_column_exists_detects_present_and_absent():
    # migrations run on a connection configured with sqlite3.Row (as
    # SqliteStorage.connect() sets it at line 1140), so mirror that here.
    # Use a name from KNOWN_TABLES so the allow-list guard passes; the actual
    # columns here are just (a, b) for the test.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE events (a TEXT, b TEXT)")
    assert _column_exists(conn, "events", "a") is True
    assert _column_exists(conn, "events", "b") is True
    assert _column_exists(conn, "events", "c") is False


def test_column_exists_rejects_unknown_table():
    # ``_column_exists`` interpolates `table` into a PRAGMA statement, which
    # cannot use bind parameters. Only allow-listed names may pass; an
    # untrusted or injection-shaped name must raise, never run SQL.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    with pytest.raises(ValueError):
        _column_exists(conn, "nope", "a")
    # Even a name packed with SQL metacharacters must raise, not be executed.
    with pytest.raises(ValueError):
        _column_exists(conn, "events; DROP TABLE events--", "a")


def test_apply_migrations_is_idempotent_on_fresh_db():
    """apply_migrations must be safe to call on an already-up-to-date (v4) DB
    without corrupting it — the connector calls it on every ``connect()``."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        storage = SqliteStorage(Path(tmpdir) / "test.db")
        storage.connect()

        # No-op backfill; migrations are gated on user_version so nothing runs,
        # but the call must not raise or leave the DB unusable.
        apply_migrations(storage.conn, backfill_event_edges=lambda: None)

        # DB still usable after a repeat migration pass.
        storage.insert_event(
            MemoryEvent(
                event_id="evt-mig",
                session_id="sess-mig",
                timestamp=datetime(2026, 6, 30, tzinfo=UTC),
                role=Role.USER,
                content_blocks=[],
            )
        )
        assert storage.get_event_count("sess-mig") == 1
        storage.close()


def test_migration_v11_drops_all_memories_tables_from_legacy_db():
    """A legacy database carrying the full memories footprint — the feature
    tables (``memory_records`` / ``memory_fts`` / ``memory_provenance`` /
    ``query_log``) plus the earlier orphaned ``consolidation_state`` /
    ``embeddings`` tables — must end up schema-identical to a fresh one after
    upgrade: every one of them dropped, ``user_version`` at 11, and the core
    tables intact."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db = Path(tmpdir) / "legacy.db"
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        # A faithful pre-v8 memory_records shape (columns v2..v7 added, no
        # ``archived`` — v8 was a no-op on upgrade).
        conn.execute(
            "CREATE TABLE memory_records ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "type TEXT NOT NULL, content TEXT NOT NULL,"
            "topics TEXT NOT NULL DEFAULT '', confidence REAL NOT NULL DEFAULT 0.5,"
            "source TEXT NOT NULL DEFAULT 'claude', session_id TEXT NOT NULL, event_id TEXT,"
            "created_at TEXT NOT NULL, content_hash TEXT NOT NULL DEFAULT '',"
            "merge_count INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL DEFAULT '',"
            "relevance REAL NOT NULL DEFAULT 1.0)"
        )
        # A faithful v5-era memory_fts and the v9 query_log.
        conn.execute(
            "CREATE VIRTUAL TABLE memory_fts USING fts5("
            "content, topics, record_id UNINDEXED, source UNINDEXED, tokenize='unicode61')"
        )
        conn.execute(
            "CREATE TABLE memory_provenance ("
            "memory_id INTEGER NOT NULL, event_id TEXT NOT NULL, source TEXT NOT NULL DEFAULT 'claude')"
        )
        conn.execute(
            "CREATE TABLE query_log ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL, mode TEXT NOT NULL,"
            "source TEXT, result_count INTEGER, created_at TEXT NOT NULL)"
        )
        # The two orphan tables v10 exists to remove.
        conn.execute(
            "CREATE TABLE consolidation_state ("
            "id INTEGER PRIMARY KEY CHECK (id = 1), last_event_id TEXT)"
        )
        conn.execute(
            "CREATE TABLE embeddings ("
            "record_id INTEGER NOT NULL, model TEXT NOT NULL, dim INTEGER NOT NULL,"
            "vector BLOB NOT NULL)"
        )
        conn.execute("CREATE INDEX idx_embeddings_model ON embeddings(model)")
        conn.execute("PRAGMA user_version = 7")
        conn.commit()

        apply_migrations(conn, backfill_event_edges=lambda: None)

        assert conn.execute("PRAGMA user_version").fetchone()[0] == 11
        remaining = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")
        }
        # The entire memories footprint is gone, orphan tables included.
        for gone in (
            "memory_records",
            "memory_fts",
            "memory_provenance",
            "query_log",
            "consolidation_state",
            "embeddings",
            "idx_embeddings_model",
        ):
            assert gone not in remaining
        # Re-running migrations on the upgraded DB is a no-op (idempotent).
        apply_migrations(conn, backfill_event_edges=lambda: None)
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 11
        conn.close()


def test_migration_v11_fresh_db_never_creates_memories_tables():
    """Fresh databases must not carry any memories-subsystem table — the v10/v11
    ``DROP TABLE IF EXISTS`` guards are no-ops there, and a fresh DB is already
    schema-identical to an upgraded legacy one."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        storage = SqliteStorage(Path(tmpdir) / "fresh.db")
        storage.connect()
        tables = {
            r["name"]
            for r in storage.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        assert storage.conn.execute("PRAGMA user_version").fetchone()[0] == 11
        for gone in (
            "memory_records",
            "memory_fts",
            "memory_provenance",
            "query_log",
            "consolidation_state",
            "embeddings",
        ):
            assert gone not in tables
        # Core tables survive as before.
        for kept in ("sessions", "events", "tool_uses", "event_edges", "events_fts"):
            assert kept in tables
        storage.close()
