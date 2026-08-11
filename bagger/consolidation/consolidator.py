"""Consolidator: distill raw conversation events into ``memory_records``.

Pipeline per session::

    fetch new events (incremental via consolidation_state)
      -> chunk into windows of CHUNK_SIZE
      -> LLM.extract  (network, outside any transaction)
      -> validate + coerce  (pure)
      -> upsert: merge into an existing record, or insert a new one
      -> advance the consolidation_state cursor

The LLM backend is injected (``LLMClient`` Protocol), so the same code runs
against 智谱 / DeepSeek / Ollama-later / a mock — only the client changes.

Three properties make this safe to run repeatedly against live data:

**Idempotence.** Every record carries a type-scoped content fingerprint with a
UNIQUE index behind it. Re-extracting the same conversation reinforces existing
rows (``merge_count += 1``, topics unioned, provenance appended) instead of
duplicating them. ``--full`` is no longer a destructive operation, and a
crashed run can simply be re-run.

**Chunk-level atomicity.** Each chunk's writes happen inside a SAVEPOINT that is
released and committed on success, rolled back on failure. The LLM call sits
*outside* it, so a slow network never holds a write lock. A crash mid-run loses
at most the chunk in flight.

**Conservative cursor advance.** The incremental cursor stops at the last chunk
that succeeded *before the first failure*. Later chunks may still be processed
(dedup makes that harmless), but the cursor never jumps over a gap — so a
failed chunk is retried on the next run rather than silently lost forever.
"""

from __future__ import annotations

import contextlib
import sqlite3
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

from bagger.consolidation.dedup import find_fuzzy_clusters, merge_topics, plan_merge
from bagger.consolidation.errors import ConsolidationError
from bagger.consolidation.llm_client import LLMClient
from bagger.consolidation.models import (
    ChunkFailure,
    ConsolidationReport,
    DedupReport,
    MemoryRecord,
    ProgressEvent,
)
from bagger.consolidation.normalize import DEFAULT_FUZZY_THRESHOLD
from bagger.consolidation.prompts import RESPONSE_SCHEMA, SYSTEM_PROMPT
from bagger.consolidation.validation import coerce_records

CHUNK_SIZE = 15
# Only a sample of rejects is carried in the report: a pathological model can
# produce thousands, and the point is to show the operator *what kind* of thing
# is being dropped, not to mirror the whole stream into memory.
MAX_REPORTED_REJECTS = 20
MAX_REPORTED_FAILURES = 20

ProgressHook = Callable[[ProgressEvent], None]


@contextlib.contextmanager
def _ignore_missing_table():
    """Swallow ``no such table`` only — any other OperationalError still raises.

    ``memory_fts`` and ``embeddings`` arrive with migration v5. A database that
    predates it (or a test fixture built from a trimmed schema) must not make a
    dedup run fail over an index that was never created.
    """
    try:
        yield
    except sqlite3.OperationalError as e:
        if "no such table" not in str(e).lower():
            raise


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
    def __init__(self, storage, llm: LLMClient, *, chunk_size: int = CHUNK_SIZE):
        self.storage = storage
        self.llm = llm
        self.conn = storage.conn  # raw sqlite3 connection (facade exposes it)
        if chunk_size < 1:
            raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")
        self.chunk_size = chunk_size

    # -- incremental bookkeeping ----------------------------------

    def _get_last_event_id(self, source: str, session_id: str) -> int:
        row = self.conn.execute(
            "SELECT last_event_id FROM consolidation_state WHERE source=? AND session_id=?",
            (source, session_id),
        ).fetchone()
        return row["last_event_id"] if row else 0

    def _iter_sessions(self, source: str | None) -> Iterator[dict]:
        """Yield every session, optionally scoped to one source."""
        page, per = 1, 200
        while True:
            res = self.storage.list_sessions_paginated(page=page, per_page=per, source=source)
            yield from res["data"]
            if page >= res["meta"]["pages"]:
                break
            page += 1

    def _fetch_new_events(self, source: str, session_id: str, last_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, event_id, role, timestamp, content_text, source, session_id "
            "FROM events WHERE source=? AND session_id=? AND id > ? ORDER BY id",
            (source, session_id, last_id),
        ).fetchall()
        return [dict(r) for r in rows]

    def _chunk(self, events: list[dict]) -> Iterator[list[dict]]:
        for i in range(0, len(events), self.chunk_size):
            yield events[i : i + self.chunk_size]

    # -- extraction ------------------------------------------------

    def _extract_chunk(
        self, source: str, session_id: str, project: str, chunk: list[dict]
    ) -> tuple[list[MemoryRecord], list]:
        """Call the LLM for one chunk and validate what comes back.

        Network IO only — no database writes — so this can run outside a
        transaction and its failures are cleanly isolated.
        """
        user_content = _build_user_content(session_id, source, project, chunk)
        raw = self.llm.extract(SYSTEM_PROMPT, user_content, RESPONSE_SCHEMA)
        return coerce_records(
            raw,
            source=source,
            session_id=session_id,
            valid_event_ids={e["event_id"] for e in chunk if e.get("event_id")},
        )

    # -- persistence (L1 exact merge) ------------------------------

    def _upsert_record(self, record: MemoryRecord, now: str) -> bool:
        """Insert ``record``, or merge it into the row with the same fingerprint.

        Returns True when an existing record was reinforced rather than a new
        row created.

        The UNIQUE index on ``content_hash`` is the authority: the SELECT is an
        optimization, and the ``IntegrityError`` branch covers the case where a
        concurrent writer inserted the same fingerprint between our read and our
        write. Without that branch a race would abort the whole chunk.
        """
        fingerprint = record.fingerprint
        existing = self.conn.execute(
            "SELECT id, topics, confidence, merge_count FROM memory_records WHERE content_hash=?",
            (fingerprint,),
        ).fetchone()

        if existing is None:
            try:
                cursor = self.conn.execute(
                    "INSERT INTO memory_records "
                    "(type, content, topics, confidence, source, session_id, event_id, "
                    " created_at, updated_at, content_hash, merge_count, relevance, archived) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1.0, 0)",
                    (
                        record.type.value,
                        record.content,
                        ",".join(record.topics),
                        record.confidence,
                        record.source,
                        record.session_id,
                        record.event_id,
                        now,
                        now,
                        fingerprint,
                    ),
                )
            except sqlite3.IntegrityError:
                existing = self.conn.execute(
                    "SELECT id, topics, confidence, merge_count FROM memory_records "
                    "WHERE content_hash=?",
                    (fingerprint,),
                ).fetchone()
                if existing is None:
                    raise  # a different constraint failed — do not swallow it
            else:
                self._record_provenance(cursor.lastrowid, record, now)
                return False

        merged_topics = merge_topics(
            (existing["topics"] or "").split(","),
            record.topics,
        )
        self.conn.execute(
            "UPDATE memory_records SET topics=?, confidence=?, merge_count=merge_count+1, "
            "updated_at=? WHERE id=?",
            (
                ",".join(merged_topics),
                max(float(existing["confidence"] or 0.0), record.confidence),
                now,
                existing["id"],
            ),
        )
        self._record_provenance(existing["id"], record, now)
        return True

    def _record_provenance(self, record_id: int, record: MemoryRecord, now: str) -> None:
        """Append the (source, session, event) trail for a record.

        ``INSERT OR IGNORE``: re-consolidating the same session must not fail on
        the composite primary key, it must simply be a no-op.
        """
        self.conn.execute(
            "INSERT OR IGNORE INTO memory_provenance "
            "(record_id, source, session_id, event_id, observed_at) VALUES (?, ?, ?, ?, ?)",
            (record_id, record.source, record.session_id, record.event_id or "", now),
        )

    def _persist_chunk(self, records: list[MemoryRecord]) -> tuple[int, int]:
        """Write one chunk's records atomically. Returns ``(inserted, merged)``.

        A SAVEPOINT rather than a plain transaction: the storage facade shares
        this connection with the API and the watcher, and a bare ``rollback()``
        would discard *their* uncommitted work too.
        """
        now = datetime.now(UTC).isoformat()
        inserted = merged = 0
        self.conn.execute("SAVEPOINT bagger_chunk")
        try:
            for record in records:
                if self._upsert_record(record, now):
                    merged += 1
                else:
                    inserted += 1
        except Exception:
            self.conn.execute("ROLLBACK TO SAVEPOINT bagger_chunk")
            self.conn.execute("RELEASE SAVEPOINT bagger_chunk")
            raise
        self.conn.execute("RELEASE SAVEPOINT bagger_chunk")
        self.conn.commit()
        return inserted, merged

    def _save_cursor(self, source: str, session_id: str, last_event_id: int) -> None:
        """Advance the incremental cursor and refresh the session's record count.

        ``record_count`` is recomputed from ``memory_provenance`` rather than
        incremented. The old code added each run's insert count to the previous
        value, so a ``--full`` re-run inflated it without bound and it stopped
        meaning anything. Counting provenance rows is idempotent and true.
        """
        count = self.conn.execute(
            "SELECT COUNT(*) FROM memory_provenance WHERE source=? AND session_id=?",
            (source, session_id),
        ).fetchone()[0]
        self.conn.execute(
            "INSERT INTO consolidation_state "
            "(source, session_id, last_event_id, last_run_at, record_count) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(source, session_id) DO UPDATE SET "
            "last_event_id=excluded.last_event_id, "
            "last_run_at=excluded.last_run_at, "
            "record_count=excluded.record_count",
            (source, session_id, last_event_id, datetime.now(UTC).isoformat(), count),
        )
        self.conn.commit()

    # -- core ------------------------------------------------------

    def run(
        self,
        source: str | None = None,
        full: bool = False,
        limit: int | None = None,
        dry_run: bool = False,
        on_progress: ProgressHook | None = None,
    ) -> ConsolidationReport:
        """Run consolidation and return a structured report.

        Args:
            source: Restrict to one tool source (``claude`` / ``codex`` / ...).
            full: Ignore the incremental cursor and re-read every event. Safe to
                repeat now that extraction is idempotent.
            limit: Stop after this many sessions have actually been *processed*.
                (The previous implementation counted sessions *examined*, so on
                an incremental re-run — where most sessions are skipped — a
                ``--limit`` run did nothing at all.)
            dry_run: Build the prompt for each session's first unprocessed chunk
                and return it under ``previews`` without calling the LLM or
                writing anything. Used to eyeball the design before spending
                tokens.
            on_progress: Optional callback invoked with :class:`ProgressEvent`
                as work proceeds. The library never prints; the CLI renders.
        """
        report = ConsolidationReport()
        started = time.monotonic()

        def emit(event: ProgressEvent) -> None:
            if on_progress is not None:
                on_progress(event)

        try:
            for sess in self._iter_sessions(source):
                if limit is not None and report.sessions_processed >= limit:
                    break
                report.sessions_seen += 1

                sess_source = sess["source"]
                session_id = sess["id"]
                project = sess.get("project_path", "")
                last_id = 0 if full else self._get_last_event_id(sess_source, session_id)
                new_events = self._fetch_new_events(sess_source, session_id, last_id)

                if not new_events:
                    report.sessions_skipped += 1
                    emit(
                        ProgressEvent(
                            kind="session_skip",
                            source=sess_source,
                            session_id=session_id,
                            message="nothing new",
                        )
                    )
                    continue

                if dry_run:
                    report.sessions_processed += 1
                    chunk = new_events[: self.chunk_size]
                    preview = _build_user_content(session_id, sess_source, project, chunk)
                    report.previews.append(
                        f"[dry-run] session {session_id[:12]} — {len(new_events)} new "
                        f"event(s), first chunk ({len(chunk)} events):\n{preview}"
                    )
                    continue

                emit(
                    ProgressEvent(
                        kind="session_start",
                        source=sess_source,
                        session_id=session_id,
                        events=len(new_events),
                    )
                )
                self._consolidate_session(
                    sess_source, session_id, project, new_events, last_id, report, emit
                )
        except KeyboardInterrupt:
            # Everything committed so far stands; the cursor makes the next run
            # resume exactly where this one stopped.
            report.interrupted = True

        report.elapsed_seconds = round(time.monotonic() - started, 3)
        return report

    def _consolidate_session(
        self,
        source: str,
        session_id: str,
        project: str,
        new_events: list[dict],
        last_id: int,
        report: ConsolidationReport,
        emit: Callable[[ProgressEvent], None],
    ) -> None:
        """Process one session's new events, chunk by chunk."""
        inserted_total = merged_total = 0
        frontier = last_id
        # Once a chunk fails, the cursor must not advance past it even if later
        # chunks succeed — otherwise the gap is never revisited.
        sealed = False
        session_failed = False

        for index, chunk in enumerate(self._chunk(new_events)):
            report.chunks_total += 1
            try:
                records, rejects = self._extract_chunk(source, session_id, project, chunk)
                inserted, merged = self._persist_chunk(records)
            except (ConsolidationError, sqlite3.Error) as e:
                sealed = True
                session_failed = True
                report.chunks_failed += 1
                if len(report.failures) < MAX_REPORTED_FAILURES:
                    report.failures.append(
                        ChunkFailure(
                            source=source,
                            session_id=session_id,
                            chunk_index=index,
                            error=f"{type(e).__name__}: {e}",
                            retryable=getattr(e, "retryable", False),
                        )
                    )
                emit(
                    ProgressEvent(
                        kind="chunk_error",
                        source=source,
                        session_id=session_id,
                        message=f"chunk {index}: {e}",
                    )
                )
                continue

            report.chunks_ok += 1
            report.records_extracted += len(records)
            report.records_inserted += inserted
            report.records_merged += merged
            report.records_rejected += len(rejects)
            for reject in rejects:
                if len(report.rejects) < MAX_REPORTED_REJECTS:
                    report.rejects.append(reject)
            for record in records:
                key = record.type.value
                report.by_type[key] = report.by_type.get(key, 0) + 1
            inserted_total += inserted
            merged_total += merged
            if not sealed:
                frontier = max(e["id"] for e in chunk)

        if frontier > last_id:
            self._save_cursor(source, session_id, frontier)

        if session_failed:
            report.sessions_failed += 1
        report.sessions_processed += 1
        emit(
            ProgressEvent(
                kind="session_done",
                source=source,
                session_id=session_id,
                events=len(new_events),
                inserted=inserted_total,
                merged=merged_total,
            )
        )

    # -- maintenance ----------------------------------------------

    def reset(self) -> int:
        """Delete all memory records, provenance and incremental state.

        Returns the number of records removed. With fingerprint-based merging in
        place this is no longer required before a ``--full`` re-extraction — a
        re-run now reinforces existing records instead of duplicating them.
        Keep it for a genuine clean slate: a changed prompt, a new model, or a
        corpus you want re-derived from scratch.
        """
        removed = self.conn.execute("SELECT COUNT(*) FROM memory_records").fetchone()[0]
        self.conn.execute("DELETE FROM memory_provenance")
        self.conn.execute("DELETE FROM memory_records")
        self.conn.execute("DELETE FROM consolidation_state")
        self.conn.commit()
        return removed

    def dedup(
        self,
        threshold: float = DEFAULT_FUZZY_THRESHOLD,
        dry_run: bool = True,
        record_type: str | None = None,
    ) -> DedupReport:
        """Find (and optionally merge) near-duplicate records — the L2 pass.

        Unlike exact-fingerprint merging, this is a *lossy* judgement call: the
        duplicates' exact wording is deleted. It therefore defaults to
        ``dry_run=True`` and must be committed explicitly, so the operator sees
        which records would collapse before any of them do.
        """
        sql = (
            "SELECT id, type, content, topics, confidence, created_at, merge_count, relevance "
            "FROM memory_records WHERE archived=0"
        )
        params: list = []
        if record_type:
            sql += " AND type=?"
            params.append(record_type)
        rows = [dict(r) for r in self.conn.execute(sql + " ORDER BY id", params).fetchall()]

        clusters, _ = find_fuzzy_clusters(rows, threshold=threshold)
        report = DedupReport(
            scanned=len(rows),
            clusters=clusters,
            dry_run=dry_run,
            threshold=threshold,
        )
        if dry_run or not clusters:
            return report

        by_id = {r["id"]: r for r in rows}
        now = datetime.now(UTC).isoformat()
        self.conn.execute("SAVEPOINT bagger_dedup")
        try:
            for cluster in clusters:
                keeper = by_id[cluster.keeper_id]
                dups = [by_id[d] for d in cluster.duplicate_ids if d in by_id]
                plan = plan_merge(keeper, dups)
                self.conn.execute(
                    "UPDATE memory_records SET confidence=?, topics=?, created_at=?, "
                    "merge_count=?, relevance=?, updated_at=? WHERE id=?",
                    (
                        plan["confidence"],
                        plan["topics"],
                        plan["created_at"],
                        plan["merge_count"],
                        plan["relevance"],
                        now,
                        cluster.keeper_id,
                    ),
                )
                self._absorb_provenance(cluster.keeper_id, cluster.duplicate_ids)
                report.records_merged += len(cluster.duplicate_ids)
        except Exception:
            self.conn.execute("ROLLBACK TO SAVEPOINT bagger_dedup")
            self.conn.execute("RELEASE SAVEPOINT bagger_dedup")
            raise
        self.conn.execute("RELEASE SAVEPOINT bagger_dedup")
        self.conn.commit()
        return report

    def _absorb_provenance(self, keeper_id: int, duplicate_ids: list[int]) -> None:
        """Re-point duplicates' provenance at the keeper, then delete them.

        Order matters: re-point first, and use ``OR IGNORE`` because the keeper
        may already have a trail for the same (source, session, event). What the
        UPDATE cannot move (a primary-key collision) is dropped with the row.

        Derived artifacts keyed by the dead ids — vectors, the memory FTS index
        — are removed in the same transaction. Leaving them behind would let a
        semantic search return hits that resolve to nothing.
        """
        if not duplicate_ids:
            return
        placeholders = ",".join("?" for _ in duplicate_ids)
        self.conn.execute(
            f"UPDATE OR IGNORE memory_provenance SET record_id=? "  # noqa: S608 - ints only
            f"WHERE record_id IN ({placeholders})",
            [keeper_id, *duplicate_ids],
        )
        self.conn.execute(
            f"DELETE FROM memory_provenance WHERE record_id IN ({placeholders})",  # noqa: S608
            duplicate_ids,
        )
        derived = (
            f"DELETE FROM embeddings WHERE owner_type LIKE 'memory%' "  # noqa: S608
            f"AND owner_id IN ({placeholders})",
            f"DELETE FROM memory_fts WHERE record_id IN ({placeholders})",  # noqa: S608
        )
        for sql in derived:
            with _ignore_missing_table():
                # owner_id / record_id are TEXT in those tables.
                self.conn.execute(sql, [str(d) for d in duplicate_ids])
        self.conn.execute(
            f"DELETE FROM memory_records WHERE id IN ({placeholders})",  # noqa: S608
            duplicate_ids,
        )

    # -- query -----------------------------------------------------

    def get_memories_by_topic(
        self,
        topic: str,
        source: str | None = None,
        limit: int = 20,
        include_archived: bool = False,
    ) -> list[dict]:
        """Return memory records whose topics or content match ``topic``.

        Still a LIKE scan — at 364 records that is sub-millisecond, and the
        semantic/FTS replacement is tracked separately in
        ``SEMANTIC_SEARCH_DESIGN.md``. What changed here: archived records are
        excluded by default (phase-3 forgetting marks records archived, and a
        forgotten memory resurfacing in recall defeats the purpose), and
        corroboration (``merge_count``) participates in ranking.
        """
        like = f"%{topic}%"
        sql = (
            "SELECT id, type, content, topics, confidence, source, session_id, "
            "event_id, created_at, updated_at, merge_count "
            "FROM memory_records WHERE (topics LIKE ? OR content LIKE ?)"
        )
        params: list = [like, like]
        if not include_archived:
            sql += " AND archived=0"
        if source:
            sql += " AND source=?"
            params.append(source)
        sql += " ORDER BY confidence DESC, merge_count DESC, created_at DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def get_provenance(self, record_id: int) -> list[dict]:
        """Every (source, session, event) that confirmed ``record_id``."""
        rows = self.conn.execute(
            "SELECT source, session_id, event_id, observed_at FROM memory_provenance "
            "WHERE record_id=? ORDER BY observed_at",
            (record_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        """Corpus-level counters for ``bagger memories --stats`` and the API."""
        total, archived, merged_rows, confirmations = self.conn.execute(
            "SELECT COUNT(*), "
            "COALESCE(SUM(archived), 0), "
            "COALESCE(SUM(CASE WHEN merge_count > 1 THEN 1 ELSE 0 END), 0), "
            "COALESCE(SUM(merge_count), 0) FROM memory_records"
        ).fetchone()
        by_type = {
            r["type"]: r["n"]
            for r in self.conn.execute(
                "SELECT type, COUNT(*) AS n FROM memory_records GROUP BY type ORDER BY n DESC"
            ).fetchall()
        }
        sessions_done = self.conn.execute("SELECT COUNT(*) FROM consolidation_state").fetchone()[0]
        return {
            "records": total,
            "archived": archived,
            "records_with_merges": merged_rows,
            "total_confirmations": confirmations,
            "by_type": by_type,
            "sessions_consolidated": sessions_done,
        }
