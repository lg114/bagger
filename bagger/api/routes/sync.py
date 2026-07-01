"""POST /api/scan, POST /api/watch — trigger data sync from the web UI."""

from fastapi import APIRouter

from bagger.api.dependencies import get_storage
from bagger.services.scanner import scan_all

router = APIRouter()


@router.post("/scan")
def trigger_scan() -> dict:
    """Trigger a full scan of Claude Code JSONL sessions."""
    with get_storage() as storage:
        result = scan_all(storage)
    return {"status": "ok", **result}


@router.post("/scan/full")
def trigger_full_scan() -> dict:
    """Trigger a full re-scan (reprocess all files from scratch)."""
    with get_storage() as storage:
        result = scan_all(storage, full=True)
    return {"status": "ok", **result}
