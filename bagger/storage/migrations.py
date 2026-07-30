"""Schema migrations for the SQLite storage backend.

Kept separate from ``sqlite.py`` so the facade stays focused on query/repo
orchestration. ``apply_migrations`` is the single entry point called once from
``SqliteStorage.connect()`` after the base ``SCHEMA``/``FTS_SCHEMA`` are applied.

Migrations are numbered and gated on ``PRAGMA user_version`` so each runs at
most once per database. They are idempotent and crash-safe: a mid-migration
crash rolls back the open transaction and a re-run starts clean.
"""

import contextlib
import sqlite3


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """True if ``column`` is present on ``table`` (used by migrations)."""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r["name"] == column for r in rows)


def apply_migrations(conn: sqlite3.Connection, backfill_event_edges) -> None:
    """Apply all pending schema migrations in order.

    Args:
        conn: The live SQLite connection (already in WAL mode).
        backfill_event_edges: Zero-arg callable that recomputes ``event_edges``
            for the whole database (the facade passes its own implementation,
            since edges are derived data owned by the storage layer).
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < 2:
        _apply_migration_v2(conn)
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
    if version < 3:
        _apply_migration_v3(conn, backfill_event_edges)
        conn.execute("PRAGMA user_version = 3")
        conn.commit()
    if version < 4:
        _apply_migration_v4(conn)


def _apply_migration_v2(conn: sqlite3.Connection) -> None:
    """Add usage/provider columns to legacy (v1) databases.

    New databases get these columns from SCHEMA directly; this only patches
    databases created before this migration existed.
    """
    alters = [
        "ALTER TABLE events ADD COLUMN token_cache_read INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE events ADD COLUMN token_cache_write INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE events ADD COLUMN cost_usd REAL",
        "ALTER TABLE events ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD'",
        "ALTER TABLE events ADD COLUMN service_tier TEXT",
        "ALTER TABLE events ADD COLUMN provider TEXT",
    ]
    for sql in alters:
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(sql)  # column already exists
    conn.commit()


def _apply_migration_v3(conn: sqlite3.Connection, backfill_event_edges) -> None:
    """Add event-edge topology + session lineage columns.

    Idempotent and safe to re-run on any database that already has
    ``events``/``sessions``. The ``event_edges`` table is *derived* from
    ``events.parent_event_id``; this backfills it for existing data so a legacy
    DB is not left with an empty tree.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS event_edges (
            event_id TEXT PRIMARY KEY,
            parent_event_id TEXT,
            session_id TEXT NOT NULL,
            depth INTEGER NOT NULL DEFAULT 0,
            source TEXT,
            UNIQUE(event_id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_event_edges_session ON event_edges(session_id)")

    alters = [
        "ALTER TABLE sessions ADD COLUMN parent_session_id TEXT",
        "ALTER TABLE sessions ADD COLUMN resume_of TEXT",
        "ALTER TABLE sessions ADD COLUMN is_compaction INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE sessions ADD COLUMN compaction_of TEXT",
    ]
    for sql in alters:
        with contextlib.suppress(sqlite3.OperationalError):
            conn.execute(sql)  # column already exists

    backfill_event_edges()
    conn.commit()


def _apply_migration_v4(conn: sqlite3.Connection) -> None:
    """Introduce multi-source identity (design doc (a)).

    Rebuilds ``sessions`` (composite PK ``(source, id)``) and ``events``
    (composite UNIQUE ``(source, event_id)``) — SQLite cannot ALTER a
    PRIMARY KEY or DROP a UNIQUE constraint, so both tables are recreated.
    Legacy rows are backfilled with ``source='claude'``. ``event_edges`` /
    ``events_fts`` gain a ``source`` column (default 'claude') so joins and
    per-source filtering are correct.

    Crash-safe: all steps run inside one implicit transaction and
    ``user_version`` is set to 4 within the same commit, so a mid-migration
    crash rolls back and a re-run starts clean. ``PRAGMA foreign_keys=OFF``
    is issued *before* any DML (it is a no-op inside a transaction) so the
    ``DROP`` of ``events`` (referenced by ``tool_uses.event_id``) is allowed;
    it is re-enabled in ``finally``.

    Idempotent: a fresh (already-v4-shaped) database already carries the
    ``source`` column, so the table rebuilds are skipped and the migration
    only backfills the derived columns — safe to run on every connect().
    """
    c = conn
    c.execute("PRAGMA foreign_keys=OFF")  # must precede any DML; allows DROP of `events`
    try:
        # 1) sessions — rebuild with composite PK (cannot ALTER a PRIMARY KEY).
        #    Skip when the column already exists (fresh v4 DB).
        if not _column_exists(c, "sessions", "source"):
            c.execute("DROP TABLE IF EXISTS sessions_new")
            c.execute(
                """
                CREATE TABLE sessions_new (
                    source TEXT NOT NULL DEFAULT 'claude',
                    id TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    project_path TEXT NOT NULL DEFAULT '',
                    message_count INTEGER NOT NULL DEFAULT 0,
                    first_message_at TEXT,
                    last_message_at TEXT,
                    last_synced_at TEXT,
                    parent_session_id TEXT,
                    resume_of TEXT,
                    is_compaction INTEGER NOT NULL DEFAULT 0,
                    compaction_of TEXT,
                    PRIMARY KEY (source, id)
                )
                """
            )
            # SELECT 'claude', * mirrors sessions_new's (source, id, ...) order
            # automatically — adding a column to SCHEMA later won't silently drop it.
            c.execute("INSERT INTO sessions_new SELECT 'claude', * FROM sessions")
            c.execute("DROP TABLE sessions")
            c.execute("ALTER TABLE sessions_new RENAME TO sessions")

        # 2) events — rebuild with composite UNIQUE(source, event_id).
        #    (ON CONFLICT(event_id) alone would let a 2nd tool's event silently
        #    overwrite the 1st tool's row -> cross-source corruption)
        if not _column_exists(c, "events", "source"):
            c.execute("DROP TABLE IF EXISTS events_new")
            c.execute(
                """
                CREATE TABLE events_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    parent_event_id TEXT,
                    timestamp TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content_json TEXT NOT NULL,
                    content_text TEXT NOT NULL DEFAULT '',
                    token_input INTEGER NOT NULL DEFAULT 0,
                    token_output INTEGER NOT NULL DEFAULT 0,
                    cwd TEXT,
                    git_branch TEXT,
                    model TEXT,
                    token_cache_read INTEGER NOT NULL DEFAULT 0,
                    token_cache_write INTEGER NOT NULL DEFAULT 0,
                    cost_usd REAL,
                    currency TEXT NOT NULL DEFAULT 'USD',
                    service_tier TEXT,
                    provider TEXT,
                    source TEXT NOT NULL DEFAULT 'claude',
                    UNIQUE(source, event_id)
                )
                """
            )
            # old events has no `source` column, so SELECT *, 'claude' appends it last.
            c.execute("INSERT INTO events_new SELECT *, 'claude' FROM events")
            c.execute("DROP TABLE events")
            c.execute("ALTER TABLE events_new RENAME TO events")

        # Source now exists on events (rebuilt above, or already present on a
        # fresh DB) — safe to (re)create the composite index for either path.
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_source_session "
            "ON events(source, session_id, timestamp)"
        )

        # 3) event_edges — add source, backfill from sessions, reindex.
        with contextlib.suppress(sqlite3.OperationalError):
            c.execute("ALTER TABLE event_edges ADD COLUMN source TEXT")
        c.execute(
            "UPDATE event_edges SET source = COALESCE("
            "(SELECT s.source FROM sessions s WHERE s.id = event_edges.session_id), 'claude') "
            "WHERE source IS NULL"
        )
        c.execute(
            "CREATE INDEX IF NOT EXISTS idx_event_edges_source_session "
            "ON event_edges(source, session_id)"
        )

        # 4) events_fts — FTS5 *virtual* tables cannot be ALTERed at all
        #    (``virtual tables may not be altered``), so a plain
        #    ``ADD COLUMN source`` would silently no-op under ``suppress``
        #    and leave the table without ``source``. Rebuild it with the new
        #    column and backfill ``source`` from sessions instead. Skipped on
        #    fresh DBs where FTS_SCHEMA already includes ``source``.
        if not _column_exists(c, "events_fts", "source"):
            c.execute("DROP TABLE IF EXISTS events_fts_new")
            c.execute(
                """
                CREATE VIRTUAL TABLE events_fts_new USING fts5(
                    content_text,
                    session_id UNINDEXED,
                    event_id UNINDEXED,
                    source UNINDEXED,
                    tokenize='unicode61'
                )
                """
            )
            c.execute(
                "INSERT INTO events_fts_new(rowid, content_text, session_id, event_id, source) "
                "SELECT f.rowid, f.content_text, f.session_id, f.event_id, "
                "COALESCE((SELECT s.source FROM sessions s WHERE s.id = f.session_id), "
                "'claude') "
                "FROM events_fts f"
            )
            c.execute("DROP TABLE events_fts")
            c.execute("ALTER TABLE events_fts_new RENAME TO events_fts")

        # 5) tool_uses — the FK ``event_id -> events(event_id)`` is invalid once
        #    events.event_id is no longer a single-column unique key (it is now
        #    part of UNIQUE(source, event_id)). Rebuild tool_uses to carry
        #    ``source`` and reference the composite key. Skip on fresh DBs.
        if not _column_exists(c, "tool_uses", "source"):
            c.execute("DROP TABLE IF EXISTS tool_uses_new")
            c.execute(
                """
                CREATE TABLE tool_uses_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    tool_id TEXT NOT NULL DEFAULT '',
                    tool_input_json TEXT NOT NULL DEFAULT '{}',
                    source TEXT NOT NULL DEFAULT 'claude',
                    FOREIGN KEY (source, event_id) REFERENCES events(source, event_id)
                )
                """
            )
            c.execute(
                "INSERT INTO tool_uses_new "
                "(id, event_id, tool_name, tool_id, tool_input_json, source) "
                "SELECT t.id, t.event_id, t.tool_name, t.tool_id, t.tool_input_json, "
                "COALESCE((SELECT e.source FROM events e WHERE e.event_id = t.event_id), "
                "'claude') FROM tool_uses t"
            )
            c.execute("DROP TABLE tool_uses")
            c.execute("ALTER TABLE tool_uses_new RENAME TO tool_uses")
            c.execute("CREATE INDEX IF NOT EXISTS idx_tool_uses_event ON tool_uses(event_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_tool_uses_name ON tool_uses(tool_name)")

        c.execute("PRAGMA user_version = 4")
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.execute("PRAGMA foreign_keys=ON")
