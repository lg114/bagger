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


def test_migration_v8_adds_archived_column_to_legacy_db():
    """A pre-v8 database (memory_records without ``archived``) must be upgraded
    in place: column added with default 0, user_version bumped to 8, and legacy
    rows read back as live (not archived). The base SCHEMA already declares the
    column for fresh DBs, so this only guards the upgrade path."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db = Path(tmpdir) / "legacy.db"
        conn = sqlite3.connect(db)
        conn.row_factory = sqlite3.Row
        # A faithful pre-v8 memory_records shape — every column v2..v7 added,
        # but no ``archived``.
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
        conn.execute("PRAGMA user_version = 7")
        conn.commit()

        assert _column_exists(conn, "memory_records", "archived") is False

        apply_migrations(conn, backfill_event_edges=lambda: None)

        assert _column_exists(conn, "memory_records", "archived") is True
        # v8 adds archived; v9 (query_log) rides along to the same latest version.
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 9
        # Legacy rows must not suddenly be treated as archived.
        conn.execute(
            "INSERT INTO memory_records(type, content, source, session_id, created_at) "
            "VALUES ('fact', 'legacy memory', 'claude', 's1', '2026-01-01T00:00:00')"
        )
        assert conn.execute("SELECT archived FROM memory_records").fetchone()[0] == 0
        conn.close()
