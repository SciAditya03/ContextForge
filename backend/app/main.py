"""ContextForge FastAPI application."""

from __future__ import annotations

import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes_projects import router as projects_router
from app.api.routes_settings import router as settings_router
from app.core.config import ANALYSIS_VERSION, Settings, get_settings
from app.core.logging import setup_logging
from app.db.database import Database
from app.services.pipeline.jobs import JobManager
from app.services.settings_service import SettingsService

log = logging.getLogger("contextforge")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_dirs()
    setup_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = Database(settings.db_path)
        interrupted = db.mark_interrupted()
        if interrupted:
            log.warning("%d analyses were interrupted by a restart and marked failed", interrupted)
        app.state.settings = settings
        app.state.db = db
        app.state.settings_service = SettingsService(db, settings)
        app.state.jobs = JobManager(db, settings)
        try:
            yield
        finally:
            await app.state.jobs.shutdown()
            db.close()

    app = FastAPI(title="ContextForge API", version=ANALYSIS_VERSION, lifespan=lifespan,
                  description="Codebase intelligence and LLM context generation. Uploaded code is never executed.")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "Authorization", "Last-Event-ID"],
    )

    token = settings.api_token

    @app.middleware("http")
    async def auth_gate(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Optional shared-secret gate (CONTEXTFORGE_API_TOKEN). Health and OPTIONS stay open."""
        if token and request.url.path.startswith("/api/") and request.url.path != "/api/health" and request.method != "OPTIONS":
            supplied = request.headers.get("authorization", "").removeprefix("Bearer ").strip() or request.query_params.get("token", "")
            if not hmac.compare_digest(supplied, token):
                return JSONResponse({"detail": "Missing or invalid API token"}, status_code=401)
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.get("/api/health", tags=["health"])
    def health() -> dict[str, object]:
        return {"status": "ok", "version": ANALYSIS_VERSION, "auth_required": bool(token)}

    app.include_router(settings_router)
    app.include_router(projects_router)
    return app


app = create_app()
