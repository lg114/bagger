"""Tests for the REST API endpoints."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

from bagger.api.app import create_app
from bagger.api.dependencies import get_storage, DB_PATH
from bagger.models.event import BlockType, ContentBlock, MemoryEvent, Role, Session
from bagger.storage.sqlite import SqliteStorage

# ---- Helpers ----

_original_db_path = DB_PATH


def _make_event(
    event_id="evt-001",
    session_id="sess-1",
    role=Role.USER,
    text="Hello world",
    parent_event_id=None,
) -> MemoryEvent:
    return MemoryEvent(
        event_id=event_id,
        session_id=session_id,
        parent_event_id=parent_event_id,
        timestamp=datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc),
        role=role,
        content_blocks=[ContentBlock(block_type=BlockType.TEXT, text=text)],
        token_input=10,
        token_output=20,
    )


def _override_db(tmpdir: Path) -> SqliteStorage:
    """Set up a test database and override the default DB_PATH."""
    import bagger.api.dependencies as deps

    db_path = tmpdir / "test_api.db"
    deps.DB_PATH = db_path

    storage = SqliteStorage(db_path)
    storage.connect()
    return storage


# ---- Tests ----

def test_health_check():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        # Insert some data so health check has something to report
        storage.insert_event(_make_event())
        storage.upsert_session(Session(session_id="sess-1", summary="Test"))
        storage.close()

        from fastapi.testclient import TestClient
        app = create_app()
        client = TestClient(app)

        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["sessions_count"] == 1
        assert data["events_count"] == 1
        assert data["fts_enabled"] is True


def test_list_sessions_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)
        storage.close()

        from fastapi.testclient import TestClient
        app = create_app()
        client = TestClient(app)

        response = client.get("/api/sessions")
        assert response.status_code == 200
        data = response.json()
        assert data["meta"]["total"] == 0
        assert data["data"] == []


def test_list_sessions_paginated():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        for i in range(5):
            storage.upsert_session(
                Session(session_id=f"sess-p-{i}", summary=f"Session {i}",
                        message_count=i + 1)
            )
        storage.close()

        from fastapi.testclient import TestClient
        app = create_app()
        client = TestClient(app)

        response = client.get("/api/sessions?page=1&per_page=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data["data"]) == 3
        assert data["meta"]["total"] == 5
        assert data["meta"]["pages"] == 2


def test_get_session_not_found():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)
        storage.close()

        from fastapi.testclient import TestClient
        app = create_app()
        client = TestClient(app)

        response = client.get("/api/sessions/nonexistent")
        assert response.status_code == 404


def test_get_session_found():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)
        storage.upsert_session(Session(
            session_id="abc-def-123",
            summary="Found session",
            project_path="/tmp/test",
            message_count=3,
        ))
        storage.close()

        from fastapi.testclient import TestClient
        app = create_app()
        client = TestClient(app)

        response = client.get("/api/sessions/abc-def-123")
        assert response.status_code == 200
        data = response.json()
        assert data["summary"] == "Found session"
        assert data["message_count"] == 3


def test_get_session_events():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        storage.upsert_session(Session(session_id="sess-e", summary="Event test"))
        storage.insert_events([
            _make_event(event_id="e1", session_id="sess-e", role=Role.USER,
                       text="First message"),
            _make_event(event_id="e2", session_id="sess-e", role=Role.ASSISTANT,
                       text="Assistant reply"),
        ])
        storage.close()

        from fastapi.testclient import TestClient
        app = create_app()
        client = TestClient(app)

        response = client.get("/api/sessions/sess-e/events")
        assert response.status_code == 200
        data = response.json()
        assert data["meta"]["total"] == 2
        assert len(data["data"]) == 2
        # Events should have content_blocks parsed from JSON
        assert "content_blocks" in data["data"][0]
        assert len(data["data"][0]["content_blocks"]) == 1
        assert data["data"][0]["content_blocks"][0]["text"] == "First message"


def test_get_session_events_not_found():
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)
        storage.close()

        from fastapi.testclient import TestClient
        app = create_app()
        client = TestClient(app)

        response = client.get("/api/sessions/nonexistent/events")
        assert response.status_code == 404


def test_search_english():
    """English query returns FTS5 results with snippets."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        e1 = _make_event(event_id="e-s1", session_id="s-s", role=Role.USER,
                         text="Fix the authentication token expiration bug")
        e2 = _make_event(event_id="e-s2", session_id="s-s", role=Role.ASSISTANT,
                         text="The token refresh flow needs to handle edge cases")
        storage.insert_events([e1, e2])
        storage.close()

        from fastapi.testclient import TestClient
        app = create_app()
        client = TestClient(app)

        response = client.get("/api/search?q=token")
        assert response.status_code == 200
        data = response.json()
        assert data["meta"]["total"] >= 1
        # FTS5 should return snippets with <mark> tags
        assert "snippet" in data["data"][0]


def test_search_chinese():
    """CJK query uses LIKE fallback (no snippet)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        e1 = _make_event(event_id="e-cn-s1", session_id="s-cn", role=Role.USER,
                         text="实现用户登录功能和密码重置流程")
        storage.insert_event(e1)
        storage.close()

        from fastapi.testclient import TestClient
        app = create_app()
        client = TestClient(app)

        response = client.get("/api/search?q=登录")
        assert response.status_code == 200
        data = response.json()
        assert data["meta"]["total"] >= 1
        assert "登录" in data["data"][0]["content_text"]


def test_search_pagination():
    """Search respects pagination parameters."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        for i in range(5):
            storage.insert_event(_make_event(
                event_id=f"e-sp-{i}", session_id="s-sp",
                text=f"Pagination test event number {i}"
            ))
        storage.close()

        from fastapi.testclient import TestClient
        app = create_app()
        client = TestClient(app)

        r1 = client.get("/api/search?q=Pagination&page=1&per_page=3")
        assert r1.status_code == 200
        d1 = r1.json()
        assert len(d1["data"]) == 3
        assert d1["meta"]["pages"] == 2

        r2 = client.get("/api/search?q=Pagination&page=2&per_page=3")
        assert r2.status_code == 200
        d2 = r2.json()
        assert len(d2["data"]) == 2


def test_stats():
    """GET /api/stats returns aggregate counts."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        storage.upsert_session(Session(session_id="s-st", summary="Stats test"))
        storage.insert_events([
            _make_event(event_id="e-st-1", session_id="s-st", role=Role.USER),
            _make_event(event_id="e-st-2", session_id="s-st", role=Role.ASSISTANT),
            _make_event(event_id="e-st-3", session_id="s-st", role=Role.ASSISTANT),
        ])
        storage.close()

        from fastapi.testclient import TestClient
        app = create_app()
        client = TestClient(app)

        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_sessions"] == 1
        assert data["total_events"] == 3
        assert data["user_events"] == 1
        assert data["assistant_events"] == 2


def test_stats_daily():
    """GET /api/stats/daily returns time-series data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        td = Path(tmpdir)
        storage = _override_db(td)

        storage.insert_event(_make_event(
            event_id="e-daily-1", session_id="s-d",
            text="Daily stats test message"
        ))
        storage.close()

        from fastapi.testclient import TestClient
        app = create_app()
        client = TestClient(app)

        response = client.get("/api/stats/daily?days=7")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert "meta" in data
        assert data["meta"]["days"] == 7
