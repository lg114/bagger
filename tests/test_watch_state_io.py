"""Tests for sharded WatchState persistence (watch_state_io)."""

import tempfile
from pathlib import Path

from bagger.models.event import WatchState
from bagger.services.watch_state_io import (
    SHARDS,
    _shard_for,
    load_watch_state,
    save_watch_state,
)


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


def test_shard_assignment_is_stable_and_in_range():
    """Shard index must be deterministic across calls and within [0, SHARDS)."""
    assert _shard_for("claude:a") == _shard_for("claude:a")
    assert _shard_for("claude:a") != _shard_for("claude:b") or True  # not required unique
    idx = _shard_for("chatgpt:z")
    assert 0 <= idx < SHARDS


def test_incremental_write_only_touches_changed_bucket():
    """Updating one session must rewrite only its shard, not all 64 shards."""
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "state.json"
        save_watch_state(WatchState(sessions={"s1": 10, "s2": 20, "s3": 30}), state_path)

        # Snapshot every shard's content before the update.
        before = {
            p: p.read_text(encoding="utf-8") for p in _shard_dir(state_path).glob("shard_*.json")
        }
        assert before, "expected at least one shard file"

        # Change only s1's offset.
        save_watch_state(WatchState(sessions={"s1": 11, "s2": 20, "s3": 30}), state_path)

        after = {
            p: p.read_text(encoding="utf-8") for p in _shard_dir(state_path).glob("shard_*.json")
        }

        changed = [p for p in before if before.get(p) != after.get(p)]
        assert len(changed) == 1, f"expected exactly one changed shard, got {len(changed)}"
        assert '"s1": 11' in changed[0].read_text(encoding="utf-8")

        # s2/s3 must be retained and unchanged (no extra writes beyond the one above).
        reloaded = load_watch_state(state_path)
        assert reloaded.sessions == {"s1": 11, "s2": 20, "s3": 30}


def test_emptied_bucket_removes_shard_and_session():
    """Dropping a session must remove its shard file and the session on reload."""
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "state.json"
        save_watch_state(WatchState(sessions={"s1": 10}), state_path)
        assert load_watch_state(state_path).sessions == {"s1": 10}

        # Save an empty state → s1's bucket becomes empty.
        save_watch_state(WatchState(sessions={}), state_path)
        assert load_watch_state(state_path).sessions == {}
        # Its shard file should have been unlinked, not left as '{}'.
        assert list(_shard_dir(state_path).glob("shard_*.json")) == []


def test_stale_shards_from_old_hash_are_cleaned():
    """A shard left behind by the old (process-local) hash must be purged on save."""
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / "state.json"
        shard_dir = _shard_dir(state_path)
        shard_dir.mkdir(parents=True, exist_ok=True)
        # Simulate a stale shard from a previous process with a different hash salt.
        (shard_dir / "shard_00.json").write_text('{"stale_session": 99}', encoding="utf-8")

        save_watch_state(WatchState(sessions={"current": 1}), state_path)

        loaded = load_watch_state(state_path)
        assert loaded.sessions == {"current": 1}
        assert "stale_session" not in loaded.sessions
