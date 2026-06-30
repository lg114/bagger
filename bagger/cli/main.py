"""bagger CLI — AI Coding Agent Data Collector."""

import os
from pathlib import Path

import click

from bagger.storage.sqlite import SqliteStorage
from bagger.services.scanner import scan_all
from bagger.services.watcher import Watcher
from bagger.services.search import search_events
from bagger.services.replay import replay_session


BAGGER_DIR = Path.home() / ".bagger"
DB_PATH = BAGGER_DIR / "bagger.db"


@click.group()
@click.version_option(version="0.1.0", prog_name="bagger")
def cli():
    """bagger — sync Claude Code transcripts to a searchable local database."""
    pass


# ---- init ----

@cli.command()
def init():
    """Initialize ~/.bagger directory and create SQLite database."""
    BAGGER_DIR.mkdir(parents=True, exist_ok=True)

    storage = SqliteStorage(DB_PATH)
    storage.connect()
    storage.close()

    click.echo(click.style(f"  {BAGGER_DIR} initialized", fg="green"))


# ---- scan ----

@cli.command()
@click.option("--full", is_flag=True, help="Full re-scan (ignore incremental state)")
def scan(full):
    """Scan ~/.claude/projects/ and import all sessions."""
    if not DB_PATH.exists():
        click.echo("  Run 'bagger init' first.", err=True)
        return

    storage = SqliteStorage(DB_PATH)
    storage.connect()

    try:
        click.echo("Scanning ~/.claude/projects/ ...")
        stats = scan_all(storage, full=full)
        click.echo(
            f"  {stats['sessions']} sessions, "
            f"{stats['events']} events imported"
        )
        if stats["skipped"]:
            click.echo(f"  {stats['skipped']} sessions skipped (already synced)")
    finally:
        storage.close()


# ---- watch ----

@cli.command()
@click.option("--interval", default=1.0, help="Polling interval in seconds")
def watch(interval):
    """Watch ~/.claude/projects/ and sync new events in real time."""
    if not DB_PATH.exists():
        click.echo("  Run 'bagger init' first.", err=True)
        return

    storage = SqliteStorage(DB_PATH)
    storage.connect()

    try:
        # First do a quick scan to catch up
        scan_all(storage, full=False)

        # Then watch
        w = Watcher(storage)
        w.watch(interval=interval)
    finally:
        storage.close()


# ---- search ----

@cli.command()
@click.argument("query")
@click.option("--session", "-s", default=None, help="Filter by session ID prefix")
@click.option("--limit", "-n", default=20, help="Max results")
def search(query, session, limit):
    """Search conversation history with full-text search."""
    if not DB_PATH.exists():
        click.echo("  Run 'bagger init' and 'bagger scan' first.", err=True)
        return

    storage = SqliteStorage(DB_PATH)
    storage.connect()

    try:
        results = search_events(storage, query, session_id=session, limit=limit)

        if not results:
            click.echo(f"  No results for: {query}")
            return

        click.echo(click.style(f"\n  Found {len(results)} result(s):\n", bold=True))

        for i, r in enumerate(results, 1):
            sid = r["session_id"][:8]
            summary = r.get("session_summary", "(no summary)")
            ts = r["timestamp"][:19].replace("T", " ")
            role = r["role"]
            # Use FTS5 snippet if available, otherwise fall back to raw text
            snippet = r.get("snippet", r["content_text"][:200])

            click.echo(
                click.style(f"  [{i}] ", fg="cyan")
                + click.style(f"session {sid}", fg="yellow")
                + f' "{summary}"'
            )
            click.echo(f"      {ts}  {role}: {snippet}")
            click.echo("")

    finally:
        storage.close()


# ---- replay ----

@cli.command()
@click.argument("session_id")
def replay(session_id):
    """Replay a full conversation session."""
    if not DB_PATH.exists():
        click.echo("  Run 'bagger init' and 'bagger scan' first.", err=True)
        return

    storage = SqliteStorage(DB_PATH)
    storage.connect()

    try:
        # Support partial session_id prefix matching
        sessions = storage.list_sessions(limit=200)
        matched = [s for s in sessions if s["id"].startswith(session_id)]

        if not matched:
            click.echo(f"  No session found matching: {session_id}")
            return

        if len(matched) > 1:
            click.echo(f"  Multiple sessions match '{session_id}':")
            for s in matched:
                click.echo(f"    {s['id'][:16]}... \"{s['summary']}\"")
            return

        actual_id = matched[0]["id"]
        output = replay_session(storage, actual_id)
        click.echo(output)

    finally:
        storage.close()


# ---- stats ----

@cli.command()
def stats():
    """Show aggregate statistics."""
    if not DB_PATH.exists():
        click.echo("  Run 'bagger init' and 'bagger scan' first.", err=True)
        return

    storage = SqliteStorage(DB_PATH)
    storage.connect()

    try:
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
            sessions = storage.list_sessions(limit=5)
            for sess in sessions:
                ts = (sess.get("last_message_at") or "")[:10]
                click.echo(
                    f"    {ts}  {sess['id'][:12]}  "
                    f"({sess['message_count']} msgs)  "
                    f'"{sess["summary"]}"'
                )
            click.echo()

    finally:
        storage.close()


# ---- doctor ----

@cli.command()
def doctor():
    """Run self-diagnostics."""
    issues_found = False

    click.echo()
    click.echo(click.style("  bagger Doctor", bold=True))
    click.echo("  " + "─" * 30)

    # Check Claude projects dir
    claude_dir = Path.home() / ".claude" / "projects"
    if claude_dir.exists():
        jsonl_count = sum(
            1
            for root, _, files in os.walk(claude_dir)
            for f in files
            if f.endswith(".jsonl")
            and not f.startswith("agent-")
            and "warmup" not in f.lower()
        )
        click.echo(click.style(f"  {jsonl_count} Claude sessions found", fg="green"))
    else:
        click.echo(click.style(f"  Claude projects dir not found", fg="yellow"))
        issues_found = True

    # Check database
    if DB_PATH.exists():
        storage = SqliteStorage(DB_PATH)
        storage.connect()
        try:
            issues = storage.check_integrity()
            s = storage.get_stats()

            click.echo(click.style(f"  {s['total_sessions']} sessions in DB", fg="green"))
            click.echo(click.style(f"  {s['total_events']} events in DB", fg="green"))

            # Check FTS
            fts_ok = storage._fts_enabled()
            click.echo(
                click.style(
                    f"  FTS5 {'enabled' if fts_ok else 'not enabled'}",
                    fg="green" if fts_ok else "yellow",
                )
            )
            if not fts_ok:
                click.echo(
                    click.style(
                        "    Run 'bagger rebuild-index' to create FTS5 index",
                        fg="yellow",
                    )
                )
                issues_found = True

            click.echo(
                click.style(
                    f"  SQLite {'OK' if not any(i['level']=='error' for i in issues) else 'ISSUES'}",
                    fg="green" if not any(i["level"] == "error" for i in issues) else "red",
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
        click.echo(click.style(f"  Database not found. Run 'bagger init'.", fg="yellow"))
        issues_found = True

    # Check bagger dir
    if BAGGER_DIR.exists():
        click.echo(click.style(f"  ~/.bagger exists", fg="green"))
    else:
        click.echo(click.style(f"  ~/.bagger not found", fg="yellow"))
        issues_found = True

    click.echo()
    if not issues_found:
        click.echo(click.style("  All checks passed.", fg="green", bold=True))
    click.echo()


# ---- rebuild-index ----

@cli.command()
def rebuild_index():
    """Rebuild the FTS5 full-text search index from all events."""
    if not DB_PATH.exists():
        click.echo("  Run 'bagger init' and 'bagger scan' first.", err=True)
        return

    storage = SqliteStorage(DB_PATH)
    storage.connect()

    try:
        click.echo("  Rebuilding FTS5 index ...")
        count = storage.rebuild_fts_index()
        click.echo(
            click.style(
                f"  Index rebuilt: {count} events indexed", fg="green"
            )
        )
    finally:
        storage.close()


# ---- serve ----

@cli.command()
@click.option("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
@click.option("--port", default=8723, help="Listen port (default: 8723)")
@click.option("--no-open", is_flag=True, help="Do not open browser automatically")
def serve(host, port, no_open):
    """Start the Bagger web API and visual memory browser.

    Launches a FastAPI server on the given host/port, then opens
    the interactive API docs in your browser.
    """
    try:
        import uvicorn
    except ImportError:
        click.echo("  uvicorn not installed. Run: pip install bagger[web]", err=True)
        return

    if not DB_PATH.exists():
        click.echo("  Run 'bagger init' and 'bagger scan' first.", err=True)
        return

    if not no_open:
        import webbrowser
        url = f"http://{host}:{port}/docs"
        webbrowser.open(url)

    click.echo(click.style(f"\n  Bagger API starting at http://{host}:{port}", bold=True))
    click.echo(f"  Swagger UI:    http://{host}:{port}/docs")
    click.echo(f"  API base:      http://{host}:{port}/api")
    click.echo(click.style("  Press Ctrl+C to stop\n", dim=True))

    uvicorn.run(
        "bagger.api.app:create_app",
        host=host,
        port=port,
        factory=True,
        log_level="info",
    )
