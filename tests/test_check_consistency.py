"""Tests for scripts/check_consistency.py — the docs/version drift guard."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "check_consistency.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("check_consistency", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_consistency"] = module
    spec.loader.exec_module(module)
    return module


check = _load_script()


# ── path normalization ───────────────────────────────────
def test_normalize_collapses_parameter_names():
    assert check._normalize("/api/sessions/{id}") == check._normalize("/api/sessions/{session_id}")


def test_normalize_leaves_static_paths_alone():
    assert check._normalize("/api/health") == "/api/health"


# ── diff reporting ───────────────────────────────────────
def test_diff_reports_match(capsys):
    assert check._diff("things", {"a", "b"}, {"a", "b"}) is True
    assert "ok" in capsys.readouterr().out


def test_diff_flags_documented_but_missing(capsys):
    assert check._diff("things", {"a", "ghost"}, {"a"}) is False
    out = capsys.readouterr().out
    assert "ghost" in out
    assert "documented but not in code" in out


def test_diff_flags_undocumented(capsys):
    assert check._diff("things", {"a"}, {"a", "secret"}) is False
    out = capsys.readouterr().out
    assert "secret" in out
    assert "in code but not documented" in out


# ── version reporting ────────────────────────────────────
def test_versions_agree(capsys):
    assert check._diff_versions({"a": "0.2.0", "b": "0.2.0"}) is True
    assert "0.2.0" in capsys.readouterr().out


def test_versions_drift(capsys):
    assert check._diff_versions({"a": "0.2.0", "b": "0.3.0"}) is False
    out = capsys.readouterr().out
    assert "0.3.0" in out
    assert "drift" in out


def test_versions_missing_is_failure(capsys):
    assert check._diff_versions({"a": "0.2.0", "b": None}) is False
    assert "NOT FOUND" in capsys.readouterr().out


# ── parsing must not silently return nothing ─────────────
def test_readme_parsing_finds_known_entries():
    assert {"init", "scan", "search", "serve"} <= check.readme_cli_commands()
    endpoints = check.readme_endpoints()
    assert "GET /api/health" in endpoints
    assert "POST /api/scan" in endpoints


def test_actual_endpoints_carry_the_api_prefix():
    endpoints = check.actual_endpoints()
    assert "GET /api/health" in endpoints
    assert "GET /api/sessions/{}" in endpoints
    # FastAPI's own /docs and /openapi.json are not part of the API surface.
    assert not any("/docs" in endpoint for endpoint in endpoints)


def test_actual_cli_commands_include_core():
    assert {"init", "scan", "search"} <= check.actual_cli_commands()


def test_current_repo_is_consistent():
    """The guard is only worth anything if it is green today.

    Failing here means either real drift crept in, or the parser stopped
    understanding the README/route layout — both need fixing before merge.
    """
    assert check.readme_cli_commands() == check.actual_cli_commands()
    assert check.readme_endpoints() == check.actual_endpoints()
    assert len(set(check.versions().values())) == 1
