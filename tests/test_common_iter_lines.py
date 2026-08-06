"""Streaming ``iter_complete_lines`` behaviour.

The streaming rewrite must preserve the exact contract of the old in-memory
implementation: ``(byte_start, decoded_stripped_line)`` pairs with byte-exact
offsets, plus dropping a trailing newline-less (half-written) line. We lock
that contract by comparing against a reference computed the old way.
"""

from pathlib import Path

from bagger.parsers import _common as cm


def _reference(path, offset=0):
    """Replicate the pre-streaming logic as an oracle."""
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read()
    if data and not data.endswith(b"\n"):
        last_nl = data.rfind(b"\n")
        data = data[:last_nl] if last_nl != -1 else b""
    out = []
    pos = offset
    for raw in data.split(b"\n"):
        start = pos
        pos += len(raw) + 1
        s = raw.strip()
        if s:
            out.append((start, s.decode("utf-8")))
    return out


def _write(tmp_path, data: bytes) -> Path:
    p = tmp_path / "t.jsonl"
    p.write_bytes(data)
    return p


def test_matches_reference_on_ascii(tmp_path):
    data = b'{"a":1}\n{"b":2}\n{"c":3}\n'
    p = _write(tmp_path, data)
    assert list(cm.iter_complete_lines(p)) == _reference(p)


def test_matches_reference_on_cjk_byte_offsets(tmp_path):
    # Non-ASCII content: byte offsets must not drift (binary read).
    data = '{"text":"你好世界"}\n{"x":2}\n'.encode()
    p = _write(tmp_path, data)
    got = list(cm.iter_complete_lines(p))
    assert got == _reference(p)
    # the CJK line start must equal the byte length of the prefix
    assert got[0][0] == 0
    assert got[1][0] == len('{"text":"你好世界"}\n'.encode())


def test_trailing_incomplete_line_dropped(tmp_path):
    data = b'{"a":1}\n{"b":2}\n{"c":3'  # last line has no newline
    p = _write(tmp_path, data)
    assert list(cm.iter_complete_lines(p)) == _reference(p)
    assert len(list(cm.iter_complete_lines(p))) == 2


def test_offset_resumes_with_absolute_offsets(tmp_path):
    data = b'{"a":1}\n{"b":2}\n{"c":3}\n'
    p = _write(tmp_path, data)
    off = len(b'{"a":1}\n')
    got = list(cm.iter_complete_lines(p, off))
    assert got == _reference(p, off)
    # offsets remain absolute (file positions), not relative to offset
    assert got[0][0] == off


def test_empty_file_yields_nothing(tmp_path):
    p = _write(tmp_path, b"")
    assert list(cm.iter_complete_lines(p)) == []


def test_offset_at_eof_yields_nothing(tmp_path):
    data = b'{"a":1}\n'
    p = _write(tmp_path, data)
    assert list(cm.iter_complete_lines(p, len(data))) == []


def test_cross_chunk_boundary_with_tiny_chunk(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "_READ_CHUNK", 16)
    # Lines longer than the chunk size, forcing buffering across reads.
    data = b"x" * 50 + b"\n" + b"y" * 40 + b"\n" + b"z\n"
    p = _write(tmp_path, data)
    assert list(cm.iter_complete_lines(p)) == _reference(p)


def test_single_line_longer_than_chunk_is_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "_READ_CHUNK", 16)
    long_line = b"a" * 200  # > 12 chunks
    data = long_line + b"\n" + b"short\n"
    p = _write(tmp_path, data)
    got = list(cm.iter_complete_lines(p))
    assert got[0] == (0, "a" * 200)
    assert got[1] == (201, "short")
