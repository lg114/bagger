"""GET /api/memories/search — semantic / hybrid retrieval over memory_records.

This is the HTTP counterpart to the ``bagger recall`` CLI: it queries the
structured memory produced by consolidation (``memory_records``), not raw
conversation events. Three modes:

- ``hybrid`` — vector (semantic) ∪ FTS (BM25) fused via Reciprocal Rank Fusion.
- ``vector`` — semantic only (nearest embedding neighbours).
- ``fts``    — BM25 keyword only (offline, no embedder call).

``fts`` works with zero embedding configuration; ``vector``/``hybrid`` need a
reachable embedding provider (``settings.embedding_*`` / ``BAGGER_EMBEDDING_*``).
A missing or failing provider surfaces as ``503`` with the underlying reason.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from bagger.api.dependencies import get_storage

router = APIRouter()

SearchMode = Literal["hybrid", "vector", "fts"]


@router.get("/memories/search")
def search_memories(
    q: str = Query(..., min_length=1, description="Natural-language query"),
    mode: SearchMode = Query("hybrid", description="hybrid, vector, or fts"),
    limit: int = Query(10, ge=1, le=100, description="Max results"),
    source: str = Query(None, description="Filter by originating tool (e.g. claude, codex)"),
) -> dict:
    """Recall structured memories by meaning, not just keywords.

    The embedding backend is built inside the request (not at import) so the
    app starts cleanly even when no embedding provider is configured; only
    ``vector``/``hybrid`` modes actually call it. A provider failure raises
    ``RuntimeError`` from the embedder, which we translate into ``503`` so the
    caller gets an actionable message instead of a bare 500.
    """
    # Imported lazily so `create_app()` doesn't pull in the embedding stack
    # unless this endpoint is actually hit.
    from bagger.embedding import create_embedder
    from bagger.services.hybrid_search import HybridSearch

    with get_storage() as storage:
        try:
            # create_embedder() raises RuntimeError when no embedding provider is
            # configured/reachable (e.g. missing API key); that is a 503, not a 500.
            hs = HybridSearch(storage, create_embedder())
            results = hs.search(q, mode=mode, limit=limit, source=source)
        except RuntimeError as e:
            raise HTTPException(status_code=503, detail=str(e)) from e

    # Normalize the storage shape for the UI: topics is a comma-joined string in
    # the DB row, but the API contract exposes it as a list.
    for r in results:
        topics = r.get("topics")
        if isinstance(topics, str):
            r["topics"] = [t.strip() for t in topics.split(",") if t.strip()]

    return {"query": q, "mode": mode, "count": len(results), "results": results}
