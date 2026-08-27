"""bagger CLI — AI Coding Agent Data Collector.

MVP surface: scan local AI conversation transcripts, search them, and
replay/export a session.
"""

import ipaddress
import logging
import re
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
    """bagger — sync local AI coding transcripts into a searchable database."""
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
        # The backend highlights with <mark> for the web UI; strip the tags
        # so the terminal shows clean text.
        snippet = re.sub(r"</?mark>", "", snippet)

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


# ── serve ───────────────────────────────────────────────────


@cli.command()
@click.option("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
@click.option("--port", default=8723, help="Listen port (default: 8723)")
@click.option("--reload", "do_reload", is_flag=True, help="Auto-reload on code changes (dev mode)")
@click.option("--no-open", is_flag=True, help="Do not open browser automatically")
@click.option(
    "--allow-network",
    is_flag=True,
    help="Allow non-loopback binding (requires BAGGER_API_TOKEN or api_token)",
)
@require_db()
def serve(host, port, do_reload, no_open, allow_network):
    """Start the Bagger web API and dashboard UI."""
    try:
        import uvicorn
    except ImportError:
        click.echo("  uvicorn not installed. Run: pip install bagger[web]", err=True)
        return

    try:
        loopback = host.lower() == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback:
        if not allow_network:
            raise click.ClickException(
                "Refusing non-loopback binding. Pass --allow-network only when intentional."
            )
        if not settings.api_token:
            raise click.ClickException(
                "Non-loopback binding requires api_token or BAGGER_API_TOKEN."
            )

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
