"""Sharded persistence for :class:`~bagger.models.event.WatchState`.

On disk the state lives in a *directory* (``<state_path>.d``, e.g. ``state.json.d/``)
containing ``shard_XX.json`` files, each holding a slice of the ``sessions`` map
keyed by a stable hash of ``session_id`` (see :func:`_shard_for`). This keeps any
single file small even with hundreds of thousands of sessions and lets a save
rewrite only the buckets it touches, instead of re-serializing one growing JSON
blob (or all 64 shards) on every save.

A legacy single-file state (``state_path`` used to be a ``.json`` file) is read
transparently on load; the first save migrates it into the ``.d/`` directory form
(and removes the now-stale legacy file).
"""

import hashlib
import json
import logging
from pathlib import Path

from bagger.models.event import WatchState

logger = logging.getLogger(__name__)

SHARDS = 64


def _shard_dir(state_path: Path) -> Path:
    """Directory that holds the shard files for a given ``state_path``."""
    return Path(state_path).with_suffix(Path(state_path).suffix + ".d")


def load_watch_state(state_path: Path) -> WatchState:
    """Load watch state, preferring the sharded ``.d/`` store over a legacy file."""
    state_path = Path(state_path)
    shard_dir = _shard_dir(state_path)
    if shard_dir.is_dir():
        sessions: dict[str, int] = {}
        for shard in sorted(shard_dir.glob("shard_*.json")):
            try:
                sessions.update(json.loads(shard.read_text(encoding="utf-8")))
            except Exception:
                logger.warning(
                    "Could not read watch-state shard %s; skipping", shard, exc_info=True
                )
        return WatchState(sessions=sessions)
    if state_path.is_file():
        try:
            return WatchState(**json.loads(state_path.read_text(encoding="utf-8")))
        except Exception:
            logger.warning(
                "Could not read watch state %s; starting fresh", state_path, exc_info=True
            )
    return WatchState()


def _shard_for(session_id: str) -> int:
    """Deterministic shard index for a session id.

    Uses a stable ``hashlib`` digest rather than Python's builtin ``hash()``,
    which is salted per process and would make a session land in a different
    shard after a restart — leaving stale data behind and defeating the
    incremental-write optimization in :func:`save_watch_state`.
    """
    return int(hashlib.sha256(session_id.encode("utf-8")).digest()[0]) % SHARDS


def save_watch_state(state: WatchState, state_path: Path) -> None:
    """Persist watch state as sharded ``shard_XX.json`` files under ``<state_path>.d/``.

    Only shards whose contents actually changed are rewritten; buckets that become
    empty have their shard file removed. Combined with the stable
    :func:`_shard_for` hash, this means an update or deletion touches exactly the
    affected shard instead of all 64 of them.
    """
    state_path = Path(state_path)
    shard_dir = _shard_dir(state_path)
    shard_dir.mkdir(parents=True, exist_ok=True)

    # Group current sessions by their stable shard index.
    buckets: dict[int, dict[str, int]] = {}
    for sid, offset in state.sessions.items():
        buckets.setdefault(_shard_for(sid), {})[sid] = offset

    for bucket in range(SHARDS):
        data = buckets.get(bucket, {})
        path = shard_dir / f"shard_{bucket:02x}.json"
        serialized = json.dumps(data, ensure_ascii=False, indent=2)
        if path.exists():
            try:
                if path.read_text(encoding="utf-8") == serialized:
                    continue  # unchanged → skip the write entirely
            except OSError:
                pass  # fall through and (re)write
        if data:
            path.write_text(serialized, encoding="utf-8")
        elif path.exists():
            path.unlink()  # bucket emptied → drop the now-stale shard file

    # Drop a stale legacy single-file state now that the sharded form exists.
    if state_path.is_file():
        try:
            state_path.unlink()
        except OSError:
            logger.warning("Could not remove legacy watch state %s", state_path, exc_info=True)
