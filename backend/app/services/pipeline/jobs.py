"""Background job management and progress fan-out (SSE subscribers)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from app.core.config import Settings
from app.db.database import Database
from app.services.extraction.safe_zip import ZipSecurityError
from app.services.pipeline.runner import STAGES, AnalysisJob, Cancelled, PipelineRunner

log = logging.getLogger(__name__)
TERMINAL = {"completed", "failed", "cancelled"}


class JobManager:
    def __init__(self, db: Database, settings: Settings, max_parallel: int = 2) -> None:
        self.db = db
        self.settings = settings
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.jobs: dict[str, AnalysisJob] = {}
        self.subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self.sem = asyncio.Semaphore(max_parallel)

    async def emit(self, pid: str, payload: dict[str, Any]) -> None:
        eid = await asyncio.to_thread(self.db.add_event, pid, payload)
        event = {**payload, "id": eid}
        for q in list(self.subscribers.get(pid, ())):
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(event)

    def subscribe(self, pid: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=2000)
        self.subscribers.setdefault(pid, set()).add(q)
        return q

    def unsubscribe(self, pid: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        self.subscribers.get(pid, set()).discard(q)

    def start(self, job: AnalysisJob) -> None:
        self.jobs[job.project_id] = job
        self.tasks[job.project_id] = asyncio.create_task(self._run(job), name=f"analysis-{job.project_id}")

    def cancel(self, pid: str) -> bool:
        job = self.jobs.get(pid)
        if job is None:
            return False
        job.cancel.set()
        return True

    def is_running(self, pid: str) -> bool:
        t = self.tasks.get(pid)
        return t is not None and not t.done()

    async def _run(self, job: AnalysisJob) -> None:
        pid = job.project_id
        await self.emit(pid, {"type": "status", "status": "queued"})
        async with self.sem:
            if job.cancel.is_set():
                await self._finish(pid, "cancelled", error="Cancelled before start")
                return
            self.db.update_project(pid, status="running")
            await self.emit(pid, {"type": "status", "status": "running"})
            runner = PipelineRunner(self.settings, lambda p: self.emit(pid, p))
            try:
                stats = await runner.run(job)
            except Cancelled:
                await self._finish(pid, "cancelled", error="Analysis cancelled by user")
            except ZipSecurityError as exc:
                await self.emit(pid, {"type": "stage", "stage": "extracting", "status": "failed", "detail": str(exc)})
                await self._finish(pid, "failed", error=f"Archive rejected: {exc}")
            except Exception as exc:
                log.exception("analysis %s failed", pid)
                await self._finish(pid, "failed", error=f"Analysis failed: {type(exc).__name__}: {str(exc)[:300]}")
            else:
                self.db.update_project(pid, stats=stats, fingerprint=stats.get("fingerprint"))
                await self._finish(pid, "completed", stats=stats)
            finally:
                self.jobs.pop(pid, None)

    async def _finish(self, pid: str, status: str, error: str | None = None, stats: dict[str, Any] | None = None) -> None:
        self.db.update_project(pid, status=status, error=error)
        await self.emit(pid, {"type": "status", "status": status, "error": error, "stats": stats})

    async def shutdown(self) -> None:
        for job in list(self.jobs.values()):
            job.cancel.set()
        for t in list(self.tasks.values()):
            if not t.done():
                t.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)


def stage_snapshot(events: list[tuple[int, dict[str, Any]]]) -> list[dict[str, Any]]:
    state: dict[str, dict[str, Any]] = {k: {"key": k, "label": label, "status": "pending", "done": None, "total": None, "detail": "", "elapsed_s": None}
                                        for k, label in STAGES}
    for _eid, e in events:
        if e.get("type") != "stage":
            continue
        st = state.get(e.get("stage", ""))
        if st is None:
            continue
        st.update({k: e.get(k) for k in ("status", "done", "total", "detail", "elapsed_s")})
    return list(state.values())


def sse_format(event: dict[str, Any]) -> str:
    return f"id: {event.get('id', '')}\nevent: {event.get('type', 'message')}\ndata: {json.dumps(event, default=str)}\n\n"
