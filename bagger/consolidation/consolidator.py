"""Consolidator: distill raw conversation events into ``memory_records``.

Pipeline per session:
    fetch new events (incremental via consolidation_state)
      -> chunk into windows of CHUNK_SIZE
      -> LLM.extract(structured records)
      -> validate + persist into memory_records
      -> advance the consolidation_state cursor

The LLM backend is injected (``LLMClient`` Protocol), so the same code runs
against 智谱 / DeepSeek / Ollama-later / a mock — only the client changes.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bagger.consolidation.llm_client import LLMClient
from bagger.consolidation.models import MemoryRecord, MemoryType
from bagger.consolidation.prompts import RESPONSE_SCHEMA, SYSTEM_PROMPT

CHUNK_SIZE = 15


def _build_user_content(session_id: str, source: str, project: str, events: list[dict]) -> str:
    """Render a chunk of events as a readable transcript for the LLM."""
    lines = [
        f"Session: {session_id} (source: {source})",
        f"Project: {project or '(unknown)'}",
        "",
        "--- 对话片段（事件编号在括号内，可用于 event_id 溯源）---",
    ]
    for e in events:
        ts = (e.get("timestamp") or "")[:19].replace("T", " ")
        text = (e.get("content_text") or "").strip().replace("\n", " ")
        lines.append(f"[{e['role']} {ts}] ({e['event_id']}) {text}")
    lines.append("")
    lines.append("请按系统指令，只输出 JSON 对象。")
    return "\n".join(lines)


class Consolidator:
    def __init__(self, storage, llm: LLMClient):
        self.storage = storage
        self.llm = llm
        self.conn = storage.conn  # raw sqlite3 connection (facade exposes it)

    # -- incremental bookkeeping ----------------------------------

    def _get_last_event_id(self, source: str, session_id: str) -> int:
        row = self.conn.execute(
            "SELECT last_event_id FROM consolidation_state WHERE source=? AND session_id=?",
            (source, session_id),
        ).fetchone()
        return row["last_event_id"] if row else 0

    def _iter_sessions(self, source: str | None):
        """Yield every session, optionally scoped to one source."""
        page, per = 1, 200
        while True:
            res = self.storage.list_sessions_paginated(
                page=page, per_page=per, source=source
            )
            for s in res["data"]:
                yield s
            if page >= res["meta"]["pages"]:
                break
            page += 1

    # -- core ------------------------------------------------------

    def _fetch_new_events(self, source: str, session_id: str, last_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, event_id, role, timestamp, content_text, source, session_id "
            "FROM events WHERE source=? AND session_id=? AND id > ? ORDER BY id",
            (source, session_id, last_id),
        ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _chunk(events: list[dict], size: int = CHUNK_SIZE):
        for i in range(0, len(events), size):
            yield events[i : i + size]

    def _extract_chunk(
        self, source: str, session_id: str, project: str, chunk: list[dict]
    ) -> list[MemoryRecord]:
        user_content = _build_user_content(session_id, source, project, chunk)
        raw = self.llm.extract(SYSTEM_PROMPT, user_content, RESPONSE_SCHEMA)
        records: list[MemoryRecord] = []
        for r in raw:
            try:
                rec = MemoryRecord(
                    type=MemoryType(r["type"]),
                    content=str(r["content"]).strip(),
                    topics=[str(t) for t in (r.get("topics") or [])],
                    confidence=float(r.get("confidence", 0.5)),
                    source=source,
                    session_id=session_id,
                    event_id=r.get("event_id") or None,
                )
                if rec.content:
                    records.append(rec)
            except (ValueError, KeyError, TypeError):
                # Malformed record from the model — drop it, keep the rest.
                continue
        return records

    def _insert_records(self, records: list[MemoryRecord]) -> int:
        now = datetime.now(UTC).isoformat()
        count = 0
        for rec in records:
            self.conn.execute(
                "INSERT INTO memory_records "
                "(type, content, topics, confidence, source, session_id, event_id, "
                " created_at, relevance, archived) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1.0, 0)",
                (
                    rec.type.value,
                    rec.content,
                    ",".join(rec.topics),
                    rec.confidence,
                    rec.source,
                    rec.session_id,
                    rec.event_id,
                    now,
                ),
            )
            count += 1
        return count

    def run(
        self,
        source: str | None = None,
        full: bool = False,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> dict:
        """Run consolidation. Returns a summary dict.

        ``dry_run`` builds the prompt for the first unprocessed chunk of each
        session and returns it under ``previews`` without calling the LLM or
        writing anything — used to eyeball the design before spending tokens.
        """
        total_records = 0
        sessions_seen = 0
        previews: list[str] = []

        for i, sess in enumerate(self._iter_sessions(source)):
            if limit is not None and i >= limit:
                break
            source_ = sess["source"]
            session_id = sess["id"]
            project = sess.get("project_path", "")
            last_id = 0 if full else self._get_last_event_id(source_, session_id)
            new_events = self._fetch_new_events(source_, session_id, last_id)
            if not new_events:
                continue

            sessions_seen += 1
            max_id = max(e["id"] for e in new_events)

            if dry_run:
                chunk = new_events[:CHUNK_SIZE]
                preview = _build_user_content(session_id, source_, project, chunk)
                previews.append(
                    f"[dry-run] session {session_id[:12]} — {len(new_events)} new "
                    f"event(s), first chunk ({len(chunk)} events):\n{preview}"
                )
                continue

            inserted = 0
            for chunk in self._chunk(new_events):
                recs = self._extract_chunk(source_, session_id, project, chunk)
                inserted += self._insert_records(recs)

            self.conn.execute(
                "INSERT INTO consolidation_state "
                "(source, session_id, last_event_id, last_run_at, record_count) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(source, session_id) DO UPDATE SET "
                "last_event_id=excluded.last_event_id, "
                "last_run_at=excluded.last_run_at, "
                "record_count=record_count + excluded.record_count",
                (source_, session_id, max_id, datetime.now(UTC).isoformat(), inserted),
            )
            self.conn.commit()
            total_records += inserted

        return {"sessions": sessions_seen, "records": total_records, "previews": previews}

    # -- query -----------------------------------------------------

    def get_memories_by_topic(
        self, topic: str, source: str | None = None, limit: int = 20
    ) -> list[dict]:
        """Return memory records whose topics or content match ``topic``."""
        like = f"%{topic}%"
        sql = (
            "SELECT id, type, content, topics, confidence, source, session_id, "
            "event_id, created_at "
            "FROM memory_records WHERE (topics LIKE ? OR content LIKE ?)"
        )
        params: list = [like, like]
        if source:
            sql += " AND source=?"
            params.append(source)
        sql += " ORDER BY confidence DESC, created_at DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
