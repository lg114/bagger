"""Session API routes — list, detail, events (for conversation replay)."""

import json

from fastapi import APIRouter, HTTPException, Query

from bagger.api.dependencies import get_storage

router = APIRouter()


@router.get("/sessions")
def list_sessions(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=200, description="Items per page"),
) -> dict:
    """Paginated list of all sessions, sorted by last activity."""
    with get_storage() as storage:
        result = storage.list_sessions_paginated(page=page, per_page=per_page)
    return result


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    """Get metadata for a single session."""
    with get_storage() as storage:
        session = storage.get_session(session_id)
        if session is None:
            # Try prefix match
            sessions = storage.list_sessions(limit=100)
            prefix = session_id.lower()
            matches = [s for s in sessions if s["id"].lower().startswith(prefix)]
            if len(matches) == 1:
                return matches[0]
            raise HTTPException(status_code=404, detail="Session not found")
        return session


@router.get("/sessions/{session_id}/events")
def get_session_events(session_id: str) -> dict:
    """Get all events for a session, ordered by timestamp ascending.

    Returns content_blocks parsed from JSON for direct rendering.
    """
    with get_storage() as storage:
        # Resolve session ID (support prefix matching)
        session = storage.get_session(session_id)
        if session is None:
            sessions = storage.list_sessions(limit=100)
            prefix = session_id.lower()
            matches = [s for s in sessions if s["id"].lower().startswith(prefix)]
            if len(matches) == 1:
                session_id = matches[0]["id"]
            else:
                raise HTTPException(status_code=404, detail="Session not found")

        events = storage.get_session_events(session_id)

    # Parse content_json into content_blocks for the frontend
    parsed_events = []
    for evt in events:
        evt = dict(evt)
        try:
            evt["content_blocks"] = json.loads(evt.pop("content_json", "[]"))
        except (json.JSONDecodeError, TypeError):
            evt["content_blocks"] = []
        parsed_events.append(evt)

    return {"data": parsed_events, "meta": {"total": len(parsed_events)}}
