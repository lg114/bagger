import hmac
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from bagger import __version__
from bagger.api.routes import export, health, memories, search, sessions, stats, sync


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan.

    The API opens a fresh SQLite connection per request (see
    :func:`bagger.api.dependencies.get_storage`), so no app-lifetime connection
    is required. This hook is kept for future startup/shutdown instrumentation.
    """
    yield


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from bagger.config import settings

    app = FastAPI(
        title="Bagger API",
        description=(
            "REST API for browsing, searching, and replaying Claude Code conversation history."
        ),
        version=__version__,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def security_boundary(request, call_next):
        """Enforce optional API auth and a cheap request-size guard."""
        if request.method != "OPTIONS" and request.url.path.startswith("/api/"):
            if settings.api_token:
                expected = f"Bearer {settings.api_token}"
                supplied = request.headers.get("authorization", "")
                if not hmac.compare_digest(supplied, expected):
                    return JSONResponse(
                        {"detail": "authentication required"},
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    too_large = int(content_length) > settings.max_request_bytes
                except ValueError:
                    too_large = True
                if too_large:
                    return JSONResponse(
                        {"detail": "request body too large"}, status_code=413
                    )
        return await call_next(request)

    # Lock CORS to configured (loopback) origins — never a wildcard.
    # The API can trigger real file scans (POST /api/scan), so an open policy
    # would let any website drive the user's local agent. allow_origins comes
    # from settings.cors_origins; override it in ~/.bagger/config.toml only
    # for origins you trust.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type", "Authorization"],
        allow_credentials=False,
    )

    # Register routes
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(sessions.router, prefix="/api", tags=["sessions"])
    app.include_router(search.router, prefix="/api", tags=["search"])
    app.include_router(stats.router, prefix="/api", tags=["stats"])
    app.include_router(sync.router, prefix="/api", tags=["sync"])
    app.include_router(export.router, prefix="/api", tags=["export"])
    app.include_router(memories.router, prefix="/api", tags=["memories"])

    return app
