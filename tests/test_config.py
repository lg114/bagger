"""Tests for bagger.config.Settings (path resolution + source_alias)."""

from pathlib import Path

from bagger.config import Settings


def test_defaults_use_home_bagger_dir():
    s = Settings()
    assert s.bagger_dir == Path.home() / ".bagger"
    assert s.db_path == s.bagger_dir / "bagger.db"
    assert s.state_path == s.bagger_dir / "state.json"
    assert s.jsonl_path == s.bagger_dir / "events.jsonl"
    assert s.config_path == s.bagger_dir / "config.toml"


def test_cors_origins_default_loopback_only():
    # Deliberately NOT a wildcard — the API can trigger real local file scans.
    s = Settings()
    assert s.cors_origins == ["http://127.0.0.1:8723", "http://localhost:8723"]


def test_source_alias_is_configurable():
    s = Settings(source_alias={"claude-foo-proxy": "anthropic"})
    assert s.source_alias == {"claude-foo-proxy": "anthropic"}


def test_derived_paths_follow_bagger_dir():
    s = Settings(bagger_dir="/tmp/custom-bagger")
    assert s.bagger_dir == Path("/tmp/custom-bagger")
    assert s.db_path == Path("/tmp/custom-bagger") / "bagger.db"
    assert s.state_path == Path("/tmp/custom-bagger") / "state.json"
