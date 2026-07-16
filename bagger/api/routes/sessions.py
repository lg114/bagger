"""Session API routes — list, detail, events (for conversation replay)."""

import json

from fastapi import APIRouter, HTTPException, Query

from bagger.api.dependencies import get_storage

router = APIRouter()


@router.get("/sessions")
def list_sessions(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=200, description="Items per page"),
    sort: str = Query("last_message_at", description="Sort field"),
    order: str = Query("desc", description="Sort order (asc/desc)"),
    project: str | None = Query(None, description="Filter by exact project_path"),
) -> dict:
    """Paginated list of all sessions with configurable sorting.

    When ``project`` is provided (e.g. from the Projects page "View all"
    link), the result and its total count are scoped to that project so the
    Conversations page header matches the project's session count.
    """
    with get_storage() as storage:
        result = storage.list_sessions_paginated(
            page=page, per_page=per_page, sort=sort, order=order, project=project
        )
    return result


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    """Get metadata for a single session."""
    with get_storage() as storage:
        session = storage.get_session(session_id)
        if session is None:
            # Try prefix match via SQL LIKE
            session = storage.find_session_by_prefix(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")
        return session


@router.get("/sessions/{session_id}/events")
def get_session_events(session_id: str) -> dict:
    """Get all events for a session, ordered by timestamp ascending.

    Returns content_blocks parsed from JSON for direct rendering.
    """
    with get_storage() as storage:
        # Resolve session ID (support prefix matching via SQL LIKE)
        session = storage.get_session(session_id)
        if session is None:
            session = storage.find_session_by_prefix(session_id)
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")
            session_id = session["id"]

        total = storage.get_event_count(session_id)
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

    return {"data": parsed_events, "meta": {"total": total}}
