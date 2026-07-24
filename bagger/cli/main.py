"""bagger CLI — AI Coding Agent Data Collector."""

import logging
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


# ── scan ────────────────────────────────────────────────────


@cli.command()
@click.option("--full", is_flag=True, help="Full re-scan (ignore incremental state)")
@require_db()
@with_storage
def scan(storage, full):
    """Scan ~/.claude/projects/ and import all sessions."""
    from bagger.services.scanner import scan_all

    click.echo("Scanning ~/.claude/projects/ ...")
    stats = scan_all(storage, full=full)
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
@click.option("--interval", default=1.0, help="Polling interval in seconds")
@require_db()
@with_storage
def watch(storage, interval):
    """Watch ~/.claude/projects/ and sync new events in real time."""
    from bagger.services.scanner import scan_all
    from bagger.services.watcher import Watcher

    # Quick scan to catch up, then watch
    scan_all(storage, full=False)
    with Watcher(storage, source="claude") as watcher:
        watcher.watch(interval=interval)


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
    from bagger.parser import ParserRegistry

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

            # ADR-0001 reconciliation guard — was dead code before; doctor now
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


# ── rebuild-index ───────────────────────────────────────────


@cli.command()
@require_db()
@with_storage
def rebuild_index(storage):
    """Rebuild the FTS5 full-text search index from all events."""
    click.echo("  Rebuilding FTS5 index ...")
    count = storage.rebuild_fts_index()
    click.echo(click.style(f"  Index rebuilt: {count} events indexed", fg="green"))


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
