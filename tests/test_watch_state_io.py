"""Tests for sharded WatchState persistence (watch_state_io)."""

import tempfile
from pathlib import Path

from bagger.models.event import WatchState
from bagger.services.watch_state_io import SHARDS, load_watch_state, save_watch_state


def _shard_dir(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".d")


def test_save_then_load_round_trips():
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "state.json"
        original = WatchState(sessions={"claude:a": 10, "chatgpt:b": 20, "claude:c": 30})

        save_watch_state(original, state_path)
        loaded = load_watch_state(state_path)

        assert loaded.sessions == original.sessions


def test_save_creates_shard_directory():
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "state.json"
        save_watch_state(WatchState(sessions={"s1": 1}), state_path)
        # Shards live in <name>.d/, not as a single file at state_path.
        assert _shard_dir(state_path).is_dir()
        assert not state_path.is_file()


def test_many_sessions_spread_across_shards():
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "state.json"
        sessions = {f"session-{i}": i for i in range(500)}
        save_watch_state(WatchState(sessions=sessions), state_path)

        shard_files = sorted(_shard_dir(state_path).glob("shard_*.json"))
        # 500 distinct ids should not all collapse into a single shard file.
        assert len(shard_files) > 1
        assert len(shard_files) <= SHARDS

        loaded = load_watch_state(state_path)
        assert loaded.sessions == sessions


def test_legacy_single_file_is_migrated_and_removed():
    """A pre-sharding single-file state.json must load, then be replaced by the
    sharded directory on first save (legacy file removed)."""
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "state.json"
        legacy = WatchState(sessions={"claude:old": 42})
        state_path.write_text(legacy.model_dump_json(indent=2), encoding="utf-8")

        # Load reads the legacy file transparently.
        assert load_watch_state(state_path).sessions == legacy.sessions

        # First save migrates to the sharded form and drops the legacy file.
        save_watch_state(WatchState(sessions={"claude:old": 42, "chatgpt:new": 7}), state_path)
        assert not state_path.is_file()  # legacy file gone
        assert _shard_dir(state_path).is_dir()

        # Reload sees the merged, migrated state.
        assert load_watch_state(state_path).sessions == {
            "claude:old": 42,
            "chatgpt:new": 7,
        }


def test_load_missing_state_returns_empty():
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "does_not_exist.json"
        assert load_watch_state(state_path).sessions == {}
