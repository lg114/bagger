"""Shared helpers for concrete parsers.

Private to the ``bagger.parsers`` package — not part of the public Parser
contract. Home of the pieces every transcript parser needs: a cheap recursive
directory walk, tool-result truncation, and a byte-exact JSONL line reader.
"""

import logging
import os
from collections.abc import Iterator
from pathlib import Path

logger = logging.getLogger(__name__)

# Cap tool_result payloads so a single huge command/file dump can't bloat the
# SQLite row (and its FTS index). 32KB is generous for display/replay while
# keeping the DB bounded on large sessions. ASCII marker appended when cut.
TOOL_RESULT_MAX_CHARS = 32 * 1024


def truncate_tool_result(text: str) -> str:
    """Truncate a tool_result payload to ``TOOL_RESULT_MAX_CHARS`` with a marker."""
    if len(text) <= TOOL_RESULT_MAX_CHARS:
        return text
    return text[:TOOL_RESULT_MAX_CHARS] + "\n...[tool_result truncated]"


def truncate_text(text: str, max_len: int) -> str:
    """Truncate ``text`` to ``max_len`` chars, appending an ellipsis when cut."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def scandir_files(root: Path):
    """Recursively yield ``os.DirEntry`` for every file under ``root``.

    ``os.scandir`` gives one traversal (vs ``os.walk``'s per-directory yield)
    and exposes ``DirEntry.stat()`` without a second stat call.
    """
    stack = [root]
    while stack:
        base = stack.pop()
        try:
            with os.scandir(base) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        yield entry
        except (OSError, PermissionError):
            continue


def iter_complete_lines(path: Path, offset: int = 0) -> Iterator[tuple[int, str]]:
    """Yield ``(byte_start, line)`` for each complete JSONL line at/after ``offset``.

    Reads in binary mode so byte offsets stay exact for non-ASCII content
    (text-mode ``tell()`` cookies don't map to byte positions). A trailing line
    without a newline terminator may be a half-written append from a live
    session — it is dropped and will be picked up by a later full re-parse.
    """
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()
    if data and not data.endswith(b"\n"):
        last_nl = data.rfind(b"\n")
        data = data[:last_nl] if last_nl != -1 else b""

    pos = offset
    for raw_line in data.split(b"\n"):
        start = pos
        pos += len(raw_line) + 1  # +1 for the consumed newline
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            yield start, stripped.decode("utf-8")
        except UnicodeDecodeError:
            logger.warning("Skipping undecodable line at byte %d in %s", start, path)
