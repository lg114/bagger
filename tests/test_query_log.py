"""Query-log (v9) tests: write persistence + recent_queries aggregation."""

from pathlib import Path

from bagger.storage.sqlite import SqliteStorage


def test_log_query_persists_across_connections(tmp_path: Path):
    """log_query must commit: a fresh connection (the API's per-request model)
    has to see the row — the exact failure mode documented for storage writes."""
    db_path = tmp_path / "q.db"
    storage = SqliteStorage(db_path)
    storage.connect()
    try:
        assert storage.recent_queries() == []
        storage.log_query("向量存储", mode="hybrid", source=None, result_count=3)
        storage.log_query("向量存储", mode="fts", source=None, result_count=2)
        storage.log_query("sidecar 打包", mode="fts", source="claude", result_count=1)
    finally:
        storage.close()

    fresh = SqliteStorage(db_path)
    fresh.connect()
    try:
        rows = fresh.recent_queries()
        assert len(rows) == 2
        # Grouped + frequency-ordered: the twice-used query first.
        top = rows[0]
        assert top["query"] == "向量存储"
        assert top["uses"] == 2
        assert set(top["modes"].split(",")) == {"hybrid", "fts"}
        assert rows[1]["query"] == "sidecar 打包"
    finally:
        fresh.close()


def test_fresh_db_reaches_migration_v9(tmp_path: Path):
    storage = SqliteStorage(tmp_path / "v9.db")
    storage.connect()
    try:
        version = storage._conn.execute("PRAGMA user_version").fetchone()[0]
        assert version >= 9
        # Table exists on the same connection shape the API would open.
        assert storage.recent_queries() == []
    finally:
        storage.close()
