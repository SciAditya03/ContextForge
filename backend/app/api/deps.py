"""FastAPI dependencies and shared helpers."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException, Request

from app.core.config import Settings
from app.db.database import Database
from app.services.pipeline.jobs import JobManager
from app.services.settings_service import SettingsService

_ID = re.compile(r"^[a-f0-9]{32}$")


def get_settings(request: Request) -> Settings:
    return request.app.state.settings  # type: ignore[no-any-return]


def get_db(request: Request) -> Database:
    return request.app.state.db  # type: ignore[no-any-return]


def get_jobs(request: Request) -> JobManager:
    return request.app.state.jobs  # type: ignore[no-any-return]


def get_settings_service(request: Request) -> SettingsService:
    return request.app.state.settings_service  # type: ignore[no-any-return]


def project_dir(settings: Settings, pid: str) -> Path:
    if not _ID.match(pid):
        raise HTTPException(status_code=404, detail="Project not found")
    return settings.projects_dir / pid


def require_project(db: Database, pid: str) -> dict:  # type: ignore[type-arg]
    if not _ID.match(pid):
        raise HTTPException(status_code=404, detail="Project not found")
    p = db.get_project(pid)
    if p is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return p
