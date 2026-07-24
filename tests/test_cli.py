"""Integration tests for the bagger CLI."""

import shutil
from pathlib import Path

from click.testing import CliRunner

from bagger.cli.main import cli
from bagger.config import Settings
from bagger.parser import ParserRegistry
from bagger.parser.claude import ClaudeParser

FIXTURES = Path(__file__).parent / "fixtures"


# ── Helpers ────────────────────────────────────────────────


def _setup_env(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create isolated bagger + claude dirs under tmp_path and wire up settings.

    IMPORTANT: mutates ``bagger.config.settings`` (the source of truth) so
    ALL modules that imported it see the change.  Individual module-level
    reassignment is NOT sufficient because ``from bagger.config import
    settings`` creates per-module references.
    """
    bagger_dir = tmp_path / ".bagger"
    claude_projects = tmp_path / ".claude" / "projects"
    claude_projects.mkdir(parents=True, exist_ok=True)

    # Copy fixture JSONL into the mock Claude projects dir.
    # Naming matters: the file stem becomes the session_id in the DB,
    # and the events inside carry the same sessionId.
    fixture_file = FIXTURES / "sample_session.jsonl"
    dest = claude_projects / "abc-123-session.jsonl"
    shutil.copy2(fixture_file, dest)

    # Override the canonical settings at the source.
    # Every module that did ``from bagger.config import settings``
    # already holds a reference to the *old* object, so we need to
    # update them all.  We'll mutate the object in place where
    # possible and reassign where needed.
    import bagger.api.dependencies as deps_mod
    import bagger.cli.main as cli_mod
    import bagger.config as config_mod
    import bagger.services.scanner as scanner_mod
    import bagger.services.sync as sync_mod

    custom = Settings(bagger_dir=bagger_dir)
    config_mod.settings = custom
    cli_mod.settings = custom
    deps_mod.settings = custom
    scanner_mod.settings = custom
    sync_mod.settings = custom

    # Re-register ClaudeParser to discover from our tmp projects dir
    ParserRegistry._parsers.clear()
    ParserRegistry.register(ClaudeParser(projects_dir=claude_projects))

    return bagger_dir, claude_projects, dest


def _make_runner() -> CliRunner:
    return CliRunner()


# ── init ───────────────────────────────────────────────────


def test_init_creates_dir_and_db(tmp_path: Path):
    """``bagger init`` should create the data dir and an empty SQLite database."""
    bagger_dir = tmp_path / ".bagger"

    # Override at source so all modules see the temp path
    import bagger.cli.main as cli_mod
    import bagger.config as config_mod

    custom = Settings(bagger_dir=bagger_dir)
    config_mod.settings = custom
    cli_mod.settings = custom

    result = _make_runner().invoke(cli, ["init"])
    assert result.exit_code == 0
    assert bagger_dir.exists()
    assert (bagger_dir / "bagger.db").exists()


# ── doctor ─────────────────────────────────────────────────


def test_doctor_no_db():
    """``bagger doctor`` should report missing database gracefully."""
    import tempfile

    import bagger.cli.main as cli_mod
    import bagger.config as config_mod

    tmp = Path(tempfile.mkdtemp())
    custom = Settings(bagger_dir=tmp / ".bagger")
    config_mod.settings = custom
    cli_mod.settings = custom

    result = _make_runner().invoke(cli, ["doctor"])
    assert result.exit_code == 0
    assert "not found" in result.stdout.lower()


def test_doctor_healthy_db(tmp_path: Path):
    """``bagger doctor`` with a valid initialized db should pass all checks."""
    _setup_env(tmp_path)
    runner = _make_runner()

    # Init first, then doctor
    runner.invoke(cli, ["init"])
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 0
    assert "All checks passed" in result.stdout


# ── scan ───────────────────────────────────────────────────


def test_scan_imports_fixture_data(tmp_path: Path):
    """``bagger scan`` should import events from the fixture JSONL."""
    _setup_env(tmp_path)
    runner = _make_runner()

    runner.invoke(cli, ["init"])
    result = runner.invoke(cli, ["scan"])
    assert result.exit_code == 0
    assert "1 sessions" in result.stdout
    # The fixture has 6 user/assistant events + 2 additional lines (summary, snapshot)
    assert "events imported" in result.stdout


def test_scan_full_rescans(tmp_path: Path):
    """``bagger scan --full`` should re-scan already-imported sessions."""
    _setup_env(tmp_path)
    runner = _make_runner()

    runner.invoke(cli, ["init"])
    runner.invoke(cli, ["scan"])  # first pass
    result = runner.invoke(cli, ["scan", "--full"])  # full re-scan
    assert result.exit_code == 0


# ── stats ──────────────────────────────────────────────────


def test_stats_after_scan(tmp_path: Path):
    """``bagger stats`` should reflect imported events."""
    _setup_env(tmp_path)
    runner = _make_runner()

    runner.invoke(cli, ["init"])
    runner.invoke(cli, ["scan"])
    result = runner.invoke(cli, ["stats"])
    assert result.exit_code == 0
    assert "Sessions:" in result.stdout
    assert "Events:" in result.stdout


# ── search ─────────────────────────────────────────────────


def test_search_returns_results(tmp_path: Path):
    """``bagger search <query>`` should find text from imported events."""
    _setup_env(tmp_path)
    runner = _make_runner()

    runner.invoke(cli, ["init"])
    runner.invoke(cli, ["scan"])
    result = runner.invoke(cli, ["search", "token"])
    assert result.exit_code == 0
    assert "Found" in result.stdout


def test_search_no_results(tmp_path: Path):
    """``bagger search <gibberish>`` should say 'No results'."""
    _setup_env(tmp_path)
    runner = _make_runner()

    runner.invoke(cli, ["init"])
    runner.invoke(cli, ["scan"])
    result = runner.invoke(cli, ["search", "xyznonexistent123456"])
    assert result.exit_code == 0
    assert "No results" in result.stdout


# ── replay ─────────────────────────────────────────────────


def test_replay_session(tmp_path: Path):
    """``bagger replay <id>`` should display a conversation."""
    _setup_env(tmp_path)
    runner = _make_runner()

    runner.invoke(cli, ["init"])
    runner.invoke(cli, ["scan"])
    result = runner.invoke(cli, ["replay", "abc-123-session"])
    assert result.exit_code == 0
    assert "User:" in result.stdout


def test_replay_nonexistent_session(tmp_path: Path):
    """``bagger replay <bad-id>`` should report no match."""
    _setup_env(tmp_path)
    runner = _make_runner()

    runner.invoke(cli, ["init"])
    result = runner.invoke(cli, ["replay", "nonexistent"])
    assert result.exit_code == 0  # graceful exit, not crash
    assert "No session found" in result.stdout


# ── rebuild-index ──────────────────────────────────────────


def test_rebuild_index(tmp_path: Path):
    """``bagger rebuild-index`` should succeed after scan."""
    _setup_env(tmp_path)
    runner = _make_runner()

    runner.invoke(cli, ["init"])
    runner.invoke(cli, ["scan"])
    result = runner.invoke(cli, ["rebuild-index"])
    assert result.exit_code == 0
    assert "Index rebuilt" in result.stdout


# ── guard: require_db ──────────────────────────────────────


def test_commands_fail_before_init(tmp_path: Path):
    """Commands guarded by require_db should fail gracefully when no db exists."""
    _setup_env(tmp_path)
    runner = _make_runner()

    # Don't init — the db doesn't exist yet
    results = [
        runner.invoke(cli, ["scan"]),
        runner.invoke(cli, ["stats"]),
        runner.invoke(cli, ["search", "hello"]),
        runner.invoke(cli, ["replay", "abc"]),
        runner.invoke(cli, ["rebuild-index"]),
    ]
    for r in results:
        # require_db prints to stderr via click.echo(..., err=True)
        assert "bagger init" in r.stderr.lower()


# ── scan: parse errors are surfaced (P0-1) ───────────────────


def test_scan_reports_parse_errors(tmp_path: Path):
    """``bagger scan`` should surface a parse failure instead of swallowing it."""
    _setup_env(tmp_path)
    from bagger.parser import ParserRegistry

    parser = ParserRegistry.get("claude")
    orig_parse = parser.parse

    def _raise(_path):
        raise RuntimeError("boom")

    parser.parse = _raise  # type: ignore[method-assign]

    runner = _make_runner()
    runner.invoke(cli, ["init"])
    result = runner.invoke(cli, ["scan"])
    parser.parse = orig_parse  # restore for other tests

    assert result.exit_code == 0
    assert "failed to parse" in result.stdout


# ── doctor: event_edges reconciliation guard (P0-2) ──────────


def test_doctor_flags_inconsistent_event_edges(tmp_path: Path):
    """``bagger doctor`` should surface orphan event_edges via the ADR-0001 guard."""
    _setup_env(tmp_path)
    runner = _make_runner()
    runner.invoke(cli, ["init"])

    # Inject an orphan edge directly into the database.
    import sqlite3

    import bagger.cli.main as cli_mod

    db_path = cli_mod.settings.db_path
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO event_edges (event_id, parent_event_id, session_id, depth) "
        "VALUES ('ghost', 'real', 's1', 1)"
    )
    conn.commit()
    conn.close()

    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 0
    assert "INCONSISTENT" in result.stdout
    assert "ghost" in result.stdout
