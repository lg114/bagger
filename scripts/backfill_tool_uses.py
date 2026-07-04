"""One-shot migration: backfill tool_uses table from existing events' content_json.

Run after upgrading to bagger >= 0.2.0, before running stats/search commands.
Safe to run multiple times (INSERT OR IGNORE).
"""

import json
import sqlite3
from pathlib import Path


def backfill(db_path: Path) -> tuple[int, int]:
    """Backfill tool_uses from events.content_json. Returns (events_processed, rows_inserted)."""
    conn = sqlite3.connect(str(db_path.resolve()))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Ensure table exists (connect() in SqliteStorage creates it, but paranoia).
    conn.execute(
        "CREATE TABLE IF NOT EXISTS tool_uses ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "event_id TEXT NOT NULL, "
        "tool_name TEXT NOT NULL, "
        "tool_id TEXT NOT NULL DEFAULT '', "
        "tool_input_json TEXT NOT NULL DEFAULT '{}', "
        "FOREIGN KEY (event_id) REFERENCES events(event_id)"
        ")"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_uses_event ON tool_uses(event_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tool_uses_name ON tool_uses(tool_name)")

    # Read events that have tool_use blocks in content_json
    rows = conn.execute(
        "SELECT event_id, content_json FROM events WHERE content_json LIKE '%tool_use%'"
    ).fetchall()

    total_inserted = 0
    for event_id, content_json_str in rows:
        try:
            blocks = json.loads(content_json_str)
        except (json.JSONDecodeError, TypeError):
            continue

        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("block_type") != "TOOL_USE":
                continue

            conn.execute(
                "INSERT OR IGNORE INTO tool_uses(event_id, tool_name, tool_id, tool_input_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    event_id,
                    block.get("tool_name", "unknown"),
                    block.get("tool_id", ""),
                    json.dumps(block.get("tool_input", {}), ensure_ascii=False),
                ),
            )
            total_inserted += 1

    conn.commit()
    conn.close()
    return len(rows), total_inserted


if __name__ == "__main__":
    db_path = Path.home() / ".bagger" / "bagger.db"
    if not db_path.exists():
        print(f"Database not found at {db_path}. Run 'bagger init' first.")
        exit(1)

    events_scanned, inserted = backfill(db_path)
    print(f"Scanned {events_scanned} events with tool_use blocks")
    print(f"Inserted {inserted} tool_uses rows")
    print("Done.")
