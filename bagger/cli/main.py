"""bagger CLI — AI Coding Agent Data Collector."""

import logging
import sqlite3
from functools import wraps
from pathlib import Path

import click

from bagger import __version__ as __bagger_version__
from bagger.config import settings
from bagger.storage import create_storage

# ── Decorators ──────────────────────────────────────────────


def require_db():
    """Decorator: guard that ~/.bagger/bagger.db exists."""

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not settings.db_path.exists():
                click.echo("  Run 'bagger init' first.", err=True)
                return
            return f(*args, **kwargs)

        return wrapper

    return decorator


def with_storage(f):
    """Decorator: open + close a Storage backend around the command."""

    @wraps(f)
    def wrapper(*args, **kwargs):
        storage = create_storage()
        try:
            return f(storage, *args, **kwargs)
        finally:
            storage.close()

    return wrapper


@click.group()
@click.version_option(version=__bagger_version__, prog_name="bagger")
def cli():
    """bagger — sync Claude Code transcripts to a searchable local database."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


# ── init ────────────────────────────────────────────────────


@cli.command()
def init():
    """Initialize ~/.bagger directory and create SQLite database."""
    settings.bagger_dir.mkdir(parents=True, exist_ok=True)

    storage = create_storage()
    storage.close()

    click.echo(click.style(f"  {settings.bagger_dir} initialized", fg="green"))


@cli.command()
@click.argument("target", type=click.Path(path_type=Path, dir_okay=False))
@require_db()
@with_storage
def backup(storage, target):
    """Create an integrity-checked copy of the SQLite database.

    TARGET must not already exist. This makes repeated scheduled backups
    explicit and prevents an accidental overwrite of an older backup.
    """
    try:
        storage.backup_to(target)
    except FileExistsError:
        raise click.ClickException(
            f"Backup target already exists: {target}. Choose a new path."
        ) from None
    except (OSError, ValueError, sqlite3.Error) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(click.style(f"  Backup created: {target}", fg="green"))


# ── scan ────────────────────────────────────────────────────


@cli.command()
@click.option("--full", is_flag=True, help="Full re-scan (ignore incremental state)")
@click.option("--source", default=None, help="Limit to one source (default: all registered)")
@require_db()
@with_storage
def scan(storage, full, source):
    """Scan all registered AI tool transcript sources and import sessions.

    Omit --source to sync every registered parser (multi-tool support); pass
    --source claude (etc.) to limit to a single tool.
    """
    from bagger.services.scanner import scan_all

    scope = source or "all registered sources"
    click.echo(f"Scanning {scope} ...")
    stats = scan_all(storage, full=full, source=source)
    click.echo(f"  {stats['sessions']} sessions, {stats['events']} events imported")
    if stats["skipped"]:
        click.echo(f"  {stats['skipped']} sessions skipped (already synced)")
    if stats.get("errors"):
        click.echo(
            click.style(
                f"  {stats['errors']} file(s) failed to parse — see log above",
                fg="yellow",
            )
        )


# ── watch ───────────────────────────────────────────────────


@cli.command()
@click.option("--debounce", default=0.5, help="Coalesce bursts within this many seconds")
@click.option(
    "--rescan", default=60, help="Periodic re-scan safety-net, seconds (0=off; default 60)"
)
@click.option("--source", default=None, help="Limit to one source (default: all registered)")
@require_db()
@with_storage
def watch(storage, debounce, rescan, source):
    """Watch all registered AI tool transcript sources and sync new events live.

    Uses a filesystem observer (watchdog) so transcripts are synced the moment
    they change on disk — no per-second directory scan. Omit --source to watch
    every registered parser (multi-tool support); pass --source claude (etc.) to
    limit to a single tool.
    """
    from bagger.services.watcher import Watcher

    with Watcher(storage, source=source) as watcher:
        watcher.watch(debounce=debounce, rescan_interval=rescan)


# ── search ──────────────────────────────────────────────────


@cli.command()
@click.argument("query")
@click.option("--session", "-s", default=None, help="Filter by session ID prefix")
@click.option("--limit", "-n", default=20, help="Max results")
@require_db()
@with_storage
def search(storage, query, session, limit):
    """Search conversation history with full-text search."""
    results = storage.search(query, session_id=session, limit=limit)

    if not results:
        click.echo(f"  No results for: {query}")
        return

    click.echo(click.style(f"\n  Found {len(results)} result(s):\n", bold=True))

    for i, r in enumerate(results, 1):
        sid = r["session_id"][:8]
        summary = r.get("session_summary", "(no summary)")
        ts = r["timestamp"][:19].replace("T", " ")
        snippet = r.get("snippet", r["content_text"][:200])

        click.echo(
            click.style(f"  [{i}] ", fg="cyan")
            + click.style(f"session {sid}", fg="yellow")
            + f' "{summary}"'
        )
        click.echo(f"      {ts}  {r['role']}: {snippet}")
        click.echo("")


# ── embed ──────────────────────────────────────────────────


@cli.command()
@click.option(
    "--provider",
    type=click.Choice(["remote", "fake"]),
    default="remote",
    help="Embedding backend: remote API or offline fake (no network)",
)
@click.option("--model", default=None, help="Override embedding model name")
@click.option("--no-fts", is_flag=True, help="Skip rebuilding the memory_fts BM25 index")
@click.option("--batch-size", default=None, type=int, help="Texts per embedding request")
@require_db()
@with_storage
def embed(storage, provider, model, no_fts, batch_size):
    """Embed memory_records into vectors for semantic recall."""
    from bagger.embedding import create_embedder
    from bagger.services.embed import EmbedService

    embedder = create_embedder(provider, model=model)
    svc = EmbedService(storage, embedder)
    summary = svc.backfill(batch_size=batch_size, reindex_fts=not no_fts)
    click.echo(
        f"embedded {summary['embedded']} record(s) with model "
        f"'{summary['model']}' (dim={summary['dim']})"
    )
    click.echo(f"vector store: {summary['stats']}")


@cli.command()
@click.argument("query")
@click.option(
    "--mode",
    type=click.Choice(["hybrid", "vector", "fts"]),
    default="hybrid",
    help="hybrid = vector ∪ FTS fused; vector = semantic only; fts = BM25 only",
)
@click.option("--limit", "-n", default=10, help="Max results")
@click.option("--source", default=None, help="Filter by source label")
@click.option(
    "--provider",
    type=click.Choice(["remote", "fake"]),
    default=None,
    help="Embedding backend (default: config embedding_provider)",
)
@click.option("--model", default=None, help="Override embedding model name")
@require_db()
@with_storage
def recall(storage, query, mode, limit, source, provider, model):
    """Recall memory_records by meaning, not keywords."""
    from bagger.embedding import create_embedder
    from bagger.services.hybrid_search import HybridSearch

    embedder = create_embedder(provider, model=model)
    hs = HybridSearch(storage, embedder)
    try:
        results = hs.search(query, mode=mode, limit=limit, source=source)
    except RuntimeError as e:
        raise click.ClickException(str(e)) from e

    if not results:
        click.echo(f"  No matches for: {query}")
        return

    click.echo(click.style(f"\n  {len(results)} result(s) [{mode}]:\n", bold=True))
    for i, r in enumerate(results, 1):
        score = r.get("fused_score", "")
        content = r.get("content", "")[:140]
        click.echo(
            click.style(f"  [{i}] ", fg="cyan")
            + click.style(f"[{r.get('type', '')}] ", fg="yellow")
            + content
            + click.style(f"  (score={score})", fg="green")
        )


# ── replay ──────────────────────────────────────────────────


@cli.command()
@click.argument("session_id")
@require_db()
@with_storage
def replay(storage, session_id):
    """Replay a full conversation session."""
    from bagger.services.replay import replay_session

    # Prefix matching
    sessions = storage.list_sessions(limit=200)
    matched = [s for s in sessions if s["id"].startswith(session_id)]

    if not matched:
        click.echo(f"  No session found matching: {session_id}")
        return

    if len(matched) > 1:
        click.echo(f"  Multiple sessions match '{session_id}':")
        for s in matched:
            click.echo(f'    {s["id"][:16]}... "{s["summary"]}"')
        return

    click.echo(replay_session(storage, matched[0]["id"]))


# ── stats ───────────────────────────────────────────────────


@cli.command()
@require_db()
@with_storage
def stats(storage):
    """Show aggregate statistics."""
    s = storage.get_stats()
    click.echo()
    click.echo(click.style("  bagger Statistics", bold=True))
    click.echo("  " + "─" * 30)
    click.echo(f"  Sessions:     {s['total_sessions']}")
    click.echo(f"  Events:       {s['total_events']}")
    click.echo(f"  User msgs:    {s['user_events']}")
    click.echo(f"  Assistant:    {s['assistant_events']}")
    click.echo(f"  Tool uses:    {s['tool_uses']}")
    click.echo(f"  Total tokens: {s['total_tokens']:,}")
    click.echo()

    if s["total_sessions"] > 0:
        click.echo("  Recent sessions:")
        for sess in storage.list_sessions(limit=5):
            ts = (sess.get("last_message_at") or "")[:10]
            click.echo(
                f'    {ts}  {sess["id"][:12]}  ({sess["message_count"]} msgs)  "{sess["summary"]}"'
            )
        click.echo()


# ── doctor ──────────────────────────────────────────────────


@cli.command()
def doctor():
    """Run self-diagnostics."""
    issues_found = False

    click.echo()
    click.echo(click.style("  bagger Doctor", bold=True))
    click.echo("  " + "─" * 30)

    # Check Claude projects dir
    from bagger.parsers import ParserRegistry

    claude_files = ParserRegistry.get("claude").discover_sessions()
    if claude_files:
        click.echo(click.style(f"  {len(claude_files)} Claude sessions found", fg="green"))
    else:
        claude_dir = Path.home() / ".claude" / "projects"
        if claude_dir.exists():
            click.echo(click.style("  0 Claude sessions found", fg="yellow"))
        else:
            click.echo(click.style("  Claude projects dir not found", fg="yellow"))
            issues_found = True

    # Check database
    if settings.db_path.exists():
        storage = create_storage()
        try:
            issues = storage.check_integrity()
            s = storage.get_stats()

            click.echo(click.style(f"  {s['total_sessions']} sessions in DB", fg="green"))
            click.echo(click.style(f"  {s['total_events']} events in DB", fg="green"))

            fts_ok = storage.fts_enabled()
            click.echo(
                click.style(
                    f"  FTS5 {'enabled' if fts_ok else 'not enabled'}",
                    fg="green" if fts_ok else "yellow",
                )
            )
            if not fts_ok:
                click.echo(
                    click.style("    Run 'bagger rebuild-index' to create FTS5 index", fg="yellow")
                )
                issues_found = True

            # reconciliation guard — was dead code before; doctor now
            # actually runs it so orphan / dangling event_edges are surfaced.
            edge_report = storage.reconcile_event_edges()
            if edge_report["consistent"]:
                click.echo(click.style("  event_edges: consistent", fg="green"))
            else:
                click.echo(click.style("  event_edges: INCONSISTENT", fg="red"))
                for orphan in edge_report["orphan_edges"]:
                    click.echo(click.style(f"    orphan edge: {orphan}", fg="red"))
                if edge_report["dangling_parent_count"]:
                    click.echo(
                        click.style(
                            f"    dangling parents: {edge_report['dangling_parent_count']}",
                            fg="red",
                        )
                    )
                issues_found = True

            has_error = any(i["level"] == "error" for i in issues)
            click.echo(
                click.style(
                    f"  SQLite {'OK' if not has_error else 'ISSUES'}",
                    fg="green" if not has_error else "red",
                )
            )

            for issue in issues:
                color = {"error": "red", "warn": "yellow", "info": "blue"}.get(
                    issue["level"], "white"
                )
                click.echo(click.style(f"    [{issue['level']}] {issue['message']}", fg=color))
                if issue["level"] in ("error", "warn"):
                    issues_found = True
        finally:
            storage.close()
    else:
        click.echo(click.style("  Database not found. Run 'bagger init'.", fg="yellow"))
        issues_found = True

    # Check bagger dir
    click.echo(
        click.style(
            f"  ~/.bagger {'exists' if settings.bagger_dir.exists() else 'not found'}",
            fg="green" if settings.bagger_dir.exists() else "yellow",
        )
    )
    if not settings.bagger_dir.exists():
        issues_found = True

    click.echo()
    if not issues_found:
        click.echo(click.style("  All checks passed.", fg="green", bold=True))
    click.echo()


# ── export ──────────────────────────────────────────────────


@cli.command()
@click.argument("session_id")
@click.option(
    "--format",
    "fmt",
    default="markdown",
    type=click.Choice(["markdown"]),
    help="Export format (markdown)",
)
@click.option("-o", "--output", default=None, help="Write to this file (default: stdout)")
@click.option(
    "--dir",
    "out_dir",
    default=None,
    help="Write to DIR using an auto-generated <session>.md filename",
)
@click.option("--source", default=None, help="Limit to a single source (multi-tool IDs)")
@require_db()
@with_storage
def export(storage, session_id, fmt, output, out_dir, source):
    """Export a conversation session to a readable document.

    SESSION_ID may be a full or prefix match. With no -o/--dir the Markdown is
    printed to stdout; with -o it is written to a file; with --dir it is written
    to DIR/<session>.md.
    """
    from bagger.exporters.markdown import SUPPORTED_FORMATS, render_session

    if fmt not in SUPPORTED_FORMATS:
        click.echo(f"  Unsupported format '{fmt}'.", err=True)
        click.echo(f"  Supported: {', '.join(SUPPORTED_FORMATS)}", err=True)
        return

    # Resolve the session (prefix match via SQL LIKE, optionally scoped by source).
    session = storage.get_session(session_id, source=source)
    if session is None:
        session = storage.find_session_by_prefix(session_id, source=source)
        if session is None:
            click.echo(f"  No session found matching: {session_id}", err=True)
            return
    resolved_id = session["id"]

    events = storage.get_session_events(resolved_id, source=source)
    body = render_session(session, events, fmt=fmt)

    if out_dir:
        from pathlib import Path

        target = Path(out_dir) / f"{resolved_id}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        click.echo(click.style(f"  Exported {len(events)} events -> {target}", fg="green"))
    elif output:
        from pathlib import Path

        target = Path(output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        click.echo(click.style(f"  Exported {len(events)} events -> {target}", fg="green"))
    else:
        click.echo(body)


# ── rebuild-index ───────────────────────────────────────────


@cli.command()
@require_db()
@with_storage
def rebuild_index(storage):
    """Rebuild the FTS5 full-text search index from all events."""
    click.echo("  Rebuilding FTS5 index ...")
    count = storage.rebuild_fts_index()
    click.echo(click.style(f"  Index rebuilt: {count} events indexed", fg="green"))


# ── consolidate ─────────────────────────────────────────────


def _llm_configured() -> bool:
    """Whether an LLM API key is available (env var or config.toml)."""
    import os

    from bagger.config import settings

    return bool(os.environ.get("BAGGER_LLM_API_KEY") or settings.llm_api_key)


def _render_consolidation_report(report, dry_run: bool) -> None:
    """Render a ``ConsolidationReport`` to stdout (structured, human-readable)."""
    click.echo()

    if dry_run:
        click.echo(click.style("  Consolidation preview (dry-run)", bold=True))
        for preview in report.previews:
            click.echo(preview)
            click.echo("")
        click.echo(
            click.style(
                f"  [dry-run] {report.sessions_processed} session(s) previewed, "
                f"no records written.",
                fg="blue",
            )
        )
        return

    click.echo(click.style("  Consolidation complete", bold=True))
    click.echo("  " + "─" * 44)
    click.echo(
        f"  Sessions:  seen={report.sessions_seen}  processed={report.sessions_processed}  "
        f"skipped={report.sessions_skipped}  failed={report.sessions_failed}"
    )
    chunk_line = f"  Chunks:    {report.chunks_ok}/{report.chunks_total} ok"
    if report.chunks_failed:
        chunk_line += f", {report.chunks_failed} failed"
    click.echo(chunk_line)
    click.echo(
        f"  Records:   extracted={report.records_extracted}  inserted={report.records_inserted}  "
        f"merged={report.records_merged}  rejected={report.records_rejected}"
    )
    if report.by_type:
        parts = ", ".join(f"{k}={v}" for k, v in sorted(report.by_type.items()))
        click.echo(f"  By type:   {parts}")
    if report.elapsed_seconds:
        click.echo(f"  Elapsed:   {report.elapsed_seconds}s")
    if report.interrupted:
        click.echo(
            click.style(
                "  ⚠ Interrupted (Ctrl-C). Re-run to resume from the cursor.",
                fg="yellow",
            )
        )

    if report.rejects:
        click.echo()
        click.echo(
            click.style(
                f"  Rejected ({report.records_rejected} total, showing up to "
                f"{len(report.rejects)}):",
                fg="yellow",
            )
        )
        for r in report.rejects:
            excerpt = (r.excerpt or "")[:80]
            click.echo(f"    - {r.reason.value}: {excerpt}")

    if report.failures:
        click.echo()
        click.echo(
            click.style(f"  Chunk failures (showing up to {len(report.failures)}):", fg="red")
        )
        for f in report.failures:
            retry = " (retryable)" if f.retryable else ""
            click.echo(
                f"    - {f.source}/{f.session_id[:12]} chunk {f.chunk_index}: {f.error}{retry}"
            )
    click.echo()

    if report.sessions_processed == 0 and report.sessions_failed == 0:
        click.echo(
            click.style(
                "  Nothing new to consolidate (all sessions already processed). "
                "Use --full to re-process everything, or --limit N for a smoke test.",
                fg="yellow",
            )
        )


@cli.command()
@click.option("--source", default=None, help="Limit to one source (default: all)")
@click.option("--full", is_flag=True, help="Re-process all events (ignore incremental state)")
@click.option("--limit", default=None, type=int, help="Max sessions to process (smoke test)")
@click.option("--dry-run", is_flag=True, help="Print the prompt that would be sent, no LLM call")
@click.option("--mock", is_flag=True, help="Use a deterministic mock LLM (no network)")
@click.option(
    "--reset",
    is_flag=True,
    help="Clear all memory records + incremental state, then re-process everything",
)
@require_db()
@with_storage
def consolidate(storage, source, full, limit, dry_run, mock, reset):
    """Distill conversation events into structured memory records (phase 1)."""
    from bagger.consolidation.consolidator import Consolidator
    from bagger.consolidation.llm_client import create_llm_client

    if dry_run and mock:
        click.echo("  --dry-run and --mock are mutually exclusive.", err=True)
        return
    if not mock and not dry_run and not _llm_configured():
        click.echo(
            click.style(
                "  No LLM API key set. Set BAGGER_LLM_API_KEY (or llm_api_key in config.toml).",
                fg="yellow",
            )
        )
        click.echo(
            click.style(
                "  Tip: run with --dry-run to inspect prompts, or --mock to test offline.",
                fg="yellow",
            )
        )
        return

    import sqlite3

    llm = create_llm_client("mock" if mock else "openai")
    cons = Consolidator(storage, llm)

    def on_progress(ev):
        if ev.kind == "session_skip":
            return
        if ev.kind == "session_start":
            click.echo(f"  • {ev.source}/{ev.session_id[:12]} — {ev.events} new event(s)")
        elif ev.kind == "session_done":
            ins = ev.inserted or 0
            mg = ev.merged or 0
            tag = f"+{ins} new / {mg} merged" if (ins or mg) else "no records"
            click.echo(f"      ✓ done ({tag})")
        elif ev.kind == "chunk_error":
            click.echo(click.style(f"      ✗ {ev.message}", fg="red"))

    try:
        if reset and not dry_run and not mock:
            removed = cons.reset()
            click.echo(
                click.style(
                    f"  Cleared {removed} memory record(s) + incremental state.",
                    fg="yellow",
                )
            )
        report = cons.run(
            source=source,
            full=full or reset,
            limit=limit,
            dry_run=dry_run,
            on_progress=on_progress,
        )
    except sqlite3.OperationalError as e:
        msg = str(e).lower()
        if "readonly" in msg or "locked" in msg:
            click.echo(
                click.style(
                    "  Database is locked / read-only. Another bagger process "
                    "(e.g. the desktop app 'bagger.exe') is holding the SQLite "
                    "connection. Close the desktop app (tray -> Quit), then retry.",
                    fg="red",
                )
            )
            return
        raise

    _render_consolidation_report(report, dry_run)


# ── memories ────────────────────────────────────────────────


@cli.command()
@click.argument("topic", required=False, default=None)
@click.option("--source", default=None, help="Limit to one source")
@click.option("--limit", "-n", default=20, help="Max results")
@require_db()
@with_storage
def memories(storage, topic, source, limit):
    """List consolidated memory records, optionally filtered by TOPIC."""
    from bagger.consolidation.consolidator import Consolidator
    from bagger.consolidation.llm_client import create_llm_client

    cons = Consolidator(storage, create_llm_client("mock"))
    if topic:
        rows = cons.get_memories_by_topic(topic, source=source, limit=limit)
    else:
        rows = storage.conn.execute(
            "SELECT id, type, content, topics, confidence, source, session_id "
            "FROM memory_records WHERE archived=0 "
            "ORDER BY merge_count DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        rows = [dict(r) for r in rows]

    if not rows:
        click.echo("  No memory records yet. Run 'bagger consolidate' first.")
        return

    click.echo(click.style(f"\n  {len(rows)} memory record(s):\n", bold=True))
    for r in rows:
        click.echo(
            click.style(f"  [{r['id']}] ", fg="cyan")
            + click.style(f"{r['type']}", fg="yellow")
            + f"  (conf {r['confidence']:.2f})"
        )
        click.echo(f"      {r['content']}")
        if r.get("topics"):
            click.echo(click.style(f"      # {r['topics']}", fg="blue"))
        click.echo("")


# ── memories-dedup ──────────────────────────────────────────


@cli.command()
@click.option(
    "--threshold",
    default=None,
    type=float,
    help="Jaccard cutoff for near-duplicate detection (default: conservative 0.72)",
)
@click.option("--dry-run", is_flag=True, help="Preview clusters only — nothing is merged (default)")
@click.option(
    "--apply",
    "apply_",
    is_flag=True,
    help="Commit the merge (otherwise preview only)",
)
@click.option("--type", "record_type", default=None, help="Limit to one memory type")
@require_db()
@with_storage
def memories_dedup(storage, threshold, dry_run, apply_, record_type):
    """Find near-duplicate memory records and (optionally) merge them — L2 pass.

    This is the *lossy* dedup step: paraphrases that survive normalization get
    collapsed into one canonical record. It defaults to --dry-run so you see
    exactly which records would fold together before committing anything.
    Re-run with --apply to commit.
    """
    from bagger.consolidation.consolidator import Consolidator
    from bagger.consolidation.llm_client import create_llm_client
    from bagger.consolidation.normalize import DEFAULT_FUZZY_THRESHOLD

    if dry_run and apply_:
        click.echo("  --dry-run and --apply are mutually exclusive.", err=True)
        return

    llm = create_llm_client("mock")
    cons = Consolidator(storage, llm)
    thr = DEFAULT_FUZZY_THRESHOLD if threshold is None else threshold
    report = cons.dedup(threshold=thr, dry_run=not apply_, record_type=record_type)

    click.echo()
    click.echo(click.style(f"  Memory dedup (threshold={thr})", bold=True))
    click.echo("  " + "─" * 44)
    click.echo(f"  Scanned:   {report.scanned} live record(s)")
    click.echo(f"  Clusters:  {report.cluster_count} near-duplicate group(s)")
    if report.dry_run:
        click.echo(
            click.style(
                "  Mode:      PREVIEW — no records merged. Re-run with --apply to commit.",
                fg="blue",
            )
        )
    else:
        click.echo(
            click.style(
                f"  Mode:      APPLIED — {report.records_merged} duplicate record(s) merged away.",
                fg="green",
            )
        )

    if report.clusters:
        click.echo()
        for c in report.clusters:
            sim = f"{c.min_similarity:.2f}"
            click.echo(
                click.style(
                    f"  • keeper #{c.keeper_id} (sim≥{sim}): {c.keeper_content[:70]}",
                    fg="green",
                )
            )
            for did, content in zip(c.duplicate_ids, c.duplicate_contents, strict=True):
                click.echo(f"      └ merge #{did}: {content[:70]}")
            if c.merged_topics:
                click.echo(click.style(f"      # {', '.join(c.merged_topics)}", fg="blue"))
    click.echo()


# ── memories-stats ──────────────────────────────────────────


@cli.command()
@require_db()
@with_storage
def memories_stats(storage):
    """Show corpus-level statistics for consolidated memory records."""
    from bagger.consolidation.consolidator import Consolidator
    from bagger.consolidation.llm_client import create_llm_client

    llm = create_llm_client("mock")
    cons = Consolidator(storage, llm)
    s = cons.stats()

    click.echo()
    click.echo(click.style("  Memory corpus statistics", bold=True))
    click.echo("  " + "─" * 44)
    click.echo(f"  Records:               {s['records']}")
    click.echo(f"  Archived:              {s['archived']}")
    click.echo(f"  Sessions consolidated:  {s['sessions_consolidated']}")
    click.echo(f"  With merges:           {s['records_with_merges']} (merge_count > 1)")
    click.echo(f"  Total confirmations:   {s['total_confirmations']} (Σ merge_count)")
    if s["by_type"]:
        click.echo()
        click.echo("  By type:")
        for t, n in s["by_type"].items():
            click.echo(f"    {t:<10} {n}")
    click.echo()


# ── serve ───────────────────────────────────────────────────


@cli.command()
@click.option("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
@click.option("--port", default=8723, help="Listen port (default: 8723)")
@click.option("--reload", "do_reload", is_flag=True, help="Auto-reload on code changes (dev mode)")
@click.option("--no-open", is_flag=True, help="Do not open browser automatically")
@require_db()
def serve(host, port, do_reload, no_open):
    """Start the Bagger web API and visual memory browser."""
    try:
        import uvicorn
    except ImportError:
        click.echo("  uvicorn not installed. Run: pip install bagger[web]", err=True)
        return

    if not no_open:
        import webbrowser

        webbrowser.open(f"http://{host}:{port}/docs")

    click.echo(click.style(f"\n  Bagger API starting at http://{host}:{port}", bold=True))
    click.echo(f"  Swagger UI:    http://{host}:{port}/docs")
    click.echo(f"  API base:      http://{host}:{port}/api")
    if do_reload:
        click.echo(click.style("  Hot reload:    ON (code changes auto-restart)", fg="green"))
    click.echo(click.style("  Press Ctrl+C to stop\n", dim=True))

    uvicorn.run(
        "bagger.api.app:create_app",
        host=host,
        port=port,
        factory=True,
        log_level="info",
        reload=do_reload,
    )


if __name__ == "__main__":
    cli()
