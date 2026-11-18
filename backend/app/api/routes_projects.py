"""Projects API: upload, progress (SSE), intelligence, documents, search, downloads."""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse

from app.api.deps import get_db, get_jobs, get_settings, get_settings_service, project_dir, require_project
from app.core.config import Settings
from app.db.database import Database
from app.services.context.compiler import LAYER_DOCS, MASTER, MODULAR_DOCS
from app.services.export.packager import package_name
from app.services.pipeline.jobs import TERMINAL, JobManager, sse_format, stage_snapshot
from app.services.pipeline.runner import AnalysisJob
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api/projects", tags=["projects"])

CHUNK = 1024 * 1024
ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06")


def _facts(settings: Settings, pid: str) -> dict[str, Any]:
    p = project_dir(settings, pid) / "output" / "data" / "PROJECT_FACTS.json"
    if not p.exists():
        raise HTTPException(status_code=409, detail="Analysis results are not available (analysis not completed)")
    return json.loads(p.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _doc_index(out_dir: Path) -> list[dict[str, Any]]:
    titles = {MASTER: ("Master Project Context", "master")}
    for fname, title, _p in MODULAR_DOCS:
        titles[fname] = (title, "modular")
    for fname, title, _p in LAYER_DOCS:
        titles[f"layers/{fname}"] = (title, "layer")
    docs = []
    for p in sorted(out_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(out_dir).as_posix()
        title, group = titles.get(rel, (p.name, "data"))
        docs.append({"path": rel, "title": title, "group": group, "size": p.stat().st_size, "kind": "markdown" if rel.endswith(".md") else "json"})
    order = {"master": 0, "modular": 1, "layer": 2, "data": 3}
    return sorted(docs, key=lambda d: (order[d["group"]], d["path"]))


def _safe_doc(settings: Settings, pid: str, rel: str) -> Path:
    out_dir = (project_dir(settings, pid) / "output").resolve()
    target = (out_dir / rel).resolve()
    if not str(target).startswith(str(out_dir) + "/") or not target.is_file():
        raise HTTPException(status_code=404, detail="Document not found")
    return target


@router.post("", status_code=202)
async def create_project(
    file: UploadFile = File(...),
    name: str | None = Form(default=None, max_length=120),
    description: str | None = Form(default=None, max_length=2000),
    depth: str | None = Form(default=None),
    provider: str | None = Form(default=None),
    model: str | None = Form(default=None, max_length=200),
    settings: Settings = Depends(get_settings),
    db: Database = Depends(get_db),
    jobs: JobManager = Depends(get_jobs),
    svc: SettingsService = Depends(get_settings_service),
) -> dict[str, Any]:
    filename = Path(file.filename or "upload.zip").name
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="Only .zip archives are accepted")
    prefs = svc.analysis_preferences()
    depth = depth or prefs.depth
    if depth not in ("quick", "standard", "deep"):
        raise HTTPException(status_code=400, detail="depth must be quick, standard or deep")
    pid = uuid.uuid4().hex
    workdir = settings.projects_dir / pid
    workdir.mkdir(parents=True, exist_ok=False)
    archive = workdir / "upload.zip"
    limit = settings.max_upload_mb * 1_048_576
    size = 0
    try:
        with open(archive, "wb") as out:
            first = True
            while chunk := await file.read(CHUNK):
                if first:
                    if not chunk.startswith(ZIP_MAGIC):
                        raise HTTPException(status_code=400, detail="File is not a ZIP archive")
                    first = False
                size += len(chunk)
                if size > limit:
                    raise HTTPException(status_code=413, detail=f"Archive exceeds the {settings.max_upload_mb} MB upload limit")
                out.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="Empty upload")
    except HTTPException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    archive.chmod(0o600)
    proj_name = (name or "").strip() or re.sub(r"\.zip$", "", filename, flags=re.I) or "project"
    override = {"provider": provider, "model": model} if provider else ({"model": model} if model else None)
    try:
        cfg = svc.provider_config(override, depth=depth)
    except ValueError as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    options = {"depth": depth, "provider": cfg.provider if cfg else "none", "model": cfg.model if cfg else None,
               "token_budget": prefs.token_budget, "send_source_to_ai": prefs.send_source_to_ai, "exclusions": prefs.exclusions}
    db.create_project(pid, proj_name, (description or "").strip() or None, filename, size, options)
    jobs.start(AnalysisJob(
        project_id=pid, name=proj_name, description=(description or "").strip() or None, archive=archive, workdir=workdir, depth=depth,
        exclusions=prefs.exclusions, token_budget=prefs.token_budget, max_file_kb=prefs.max_file_kb, max_concurrency=prefs.max_concurrency,
        send_source=prefs.send_source_to_ai, use_cache=prefs.cache_ai_responses, keep_archive=prefs.keep_uploaded_archive, provider_config=cfg,
    ))
    return {"id": pid, "name": proj_name, "status": "queued", "options": options}


@router.get("")
def list_projects(db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    return db.list_projects()


@router.get("/{pid}")
def get_project(pid: str, db: Database = Depends(get_db), jobs: JobManager = Depends(get_jobs)) -> dict[str, Any]:
    p = require_project(db, pid)
    p["stages"] = stage_snapshot(db.events(pid))
    p["running"] = jobs.is_running(pid)
    return p


@router.post("/{pid}/cancel")
def cancel_project(pid: str, db: Database = Depends(get_db), jobs: JobManager = Depends(get_jobs)) -> dict[str, Any]:
    p = require_project(db, pid)
    if p["status"] in TERMINAL:
        raise HTTPException(status_code=409, detail=f"Analysis already {p['status']}")
    return {"cancelled": jobs.cancel(pid)}


@router.delete("/{pid}")
def delete_project(pid: str, settings: Settings = Depends(get_settings), db: Database = Depends(get_db), jobs: JobManager = Depends(get_jobs)) -> dict[str, Any]:
    require_project(db, pid)
    if jobs.is_running(pid):
        raise HTTPException(status_code=409, detail="Cancel the running analysis first")
    shutil.rmtree(project_dir(settings, pid), ignore_errors=True)
    db.delete_project(pid)
    return {"deleted": pid}


@router.get("/{pid}/events")
async def project_events(pid: str, request: Request, after: int = Query(default=0, ge=0), db: Database = Depends(get_db),
                         jobs: JobManager = Depends(get_jobs)) -> StreamingResponse:
    require_project(db, pid)
    last_id = request.headers.get("last-event-id")
    if last_id and last_id.isdigit():
        after = max(after, int(last_id))

    async def gen():  # type: ignore[no-untyped-def]
        q = jobs.subscribe(pid)
        try:
            sent = after
            for eid, e in db.events(pid, after):
                sent = eid
                yield sse_format({**e, "id": eid})
                if e.get("type") == "status" and e.get("status") in TERMINAL:
                    return
            p = db.get_project(pid)
            if p and p["status"] in TERMINAL and not jobs.is_running(pid):
                yield sse_format({"type": "status", "status": p["status"], "error": p.get("error"), "id": sent})
                return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    e = await asyncio.wait_for(q.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if e.get("id", 0) <= sent:
                    continue
                sent = e["id"]
                yield sse_format(e)
                if e.get("type") == "status" and e.get("status") in TERMINAL:
                    return
        finally:
            jobs.unsubscribe(pid, q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{pid}/intelligence")
def intelligence(pid: str, settings: Settings = Depends(get_settings), db: Database = Depends(get_db)) -> dict[str, Any]:
    p = require_project(db, pid)
    f = _facts(settings, pid)
    syn = f.get("synthesis", {})
    return {
        "project": {k: p[k] for k in ("id", "name", "description", "status", "created_at", "updated_at", "archive_name", "archive_size", "options", "stats")},
        "generated_at": f.get("generated_at"), "fingerprint": f.get("fingerprint"), "analysis_version": f.get("analysis_version"), "depth": f.get("depth"),
        "overview": f["overview"], "readme_excerpt": f.get("readme_excerpt"),
        "technologies": f.get("technologies", []),
        "components": f.get("components", []),
        "routes": f.get("routes", []),
        "client_calls": f.get("client_calls", []),
        "db_models": f.get("db_models", []),
        "db_operations_count": len(f.get("db_operations", [])),
        "findings": f.get("findings", []),
        "secrets": f.get("secrets", []),
        "env_vars": f.get("env_vars", []),
        "dependencies": f.get("dependencies", []),
        "manifest_summary": _count([m["status"] for m in f.get("manifest", [])]),
        "ai": f.get("ai", {}),
        "synthesis": {"purpose": syn.get("purpose"), "executive_summary": syn.get("executive_summary", []), "architecture": syn.get("architecture", []),
                      "authentication": syn.get("authentication", []), "workflows": syn.get("workflows", []), "open_questions": syn.get("open_questions", [])},
        "module_summaries": f.get("module_summaries", []),
        "graph": {"files": len([n for n in f["graph"]["nodes"] if n["type"] == "file"]), "edges": len(f["graph"]["edges"]),
                  "modules": len(f["graph"]["module_nodes"]), "cycles": f["graph"].get("cycles", [])},
        "tree": f.get("tree"),
        "output_validation": f.get("output_validation", {}),
        "warnings": f.get("warnings", []),
        "test_info": f.get("test_info", {}),
    }


def _count(items: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out


@router.get("/{pid}/graph")
def graph(pid: str, view: str = Query(default="modules", pattern="^(modules|files|api|database)$"), limit: int = Query(default=300, ge=10, le=2000),
          settings: Settings = Depends(get_settings), db: Database = Depends(get_db)) -> dict[str, Any]:
    require_project(db, pid)
    f = _facts(settings, pid)
    g = f["graph"]
    if view == "modules":
        return {"nodes": g["module_nodes"], "edges": g["module_edges"], "truncated": False}
    if view == "files":
        nodes = [n for n in g["nodes"] if n["type"] == "file"]
        deg: dict[str, int] = {}
        for e in g["edges"]:
            if e["type"] == "imports":
                deg[e["source"]] = deg.get(e["source"], 0) + 1
                deg[e["target"]] = deg.get(e["target"], 0) + 1
        nodes.sort(key=lambda n: -deg.get(n["id"], 0))
        keep = {n["id"] for n in nodes[:limit]}
        edges = [e for e in g["edges"] if e["type"] == "imports" and e["source"] in keep and e["target"] in keep]
        return {"nodes": [n for n in nodes if n["id"] in keep], "edges": edges, "truncated": len(nodes) > limit, "total_nodes": len(nodes)}
    if view == "api":
        nodes, edges = [], []
        files = set()
        for r in f.get("routes", []):
            rid = f"route:{r['method']} {r['path']}"
            nodes.append({"id": rid, "label": f"{r['method']} {r['path']}", "type": "route", "data": {"handler": r.get("handler"), "file": r["file"], "line": r["line"], "auth": r.get("auth", [])}})
            files.add(r["file"])
            edges.append({"source": rid, "target": r["file"], "type": "handled_by", "weight": 1})
        for c in f.get("client_calls", []):
            files.add(c["file"])
            if c.get("matched_route"):
                edges.append({"source": c["file"], "target": f"route:{c['matched_route']}", "type": "calls_api", "weight": 1, "data": {"line": c["line"], "url": c["url"]}})
        nodes += [{"id": p, "label": p.rsplit("/", 1)[-1], "type": "file", "group": p.rsplit("/", 1)[0] if "/" in p else "(root)", "data": {"path": p}} for p in sorted(files)]
        return {"nodes": nodes[:limit * 2], "edges": edges, "truncated": False}
    # database: one edge per related pair (relationship declared on both sides collapses to one)
    nodes, edges = [], []
    pairs: set[tuple[str, str]] = set()
    names = {m["name"] for m in f.get("db_models", [])}
    tables = {m.get("table"): m["name"] for m in f.get("db_models", []) if m.get("table")}
    for m in f.get("db_models", []):
        nodes.append({"id": m["name"], "label": m["name"], "type": "model", "data": {"table": m.get("table"), "orm": m["orm"], "file": m["file"], "line": m["line"],
                                                                                    "fields": [{"name": x["name"], "type": x.get("type"), "pk": x.get("primary_key"), "fk": x.get("foreign_key")} for x in m.get("fields", [])][:30]}})
    # prefer the owning side (foreign key / many_to_one) as the edge direction
    for m in f.get("db_models", []):
        for x in m.get("fields", []):
            if x.get("foreign_key"):
                tgt = tables.get(x["foreign_key"].split(".")[0], x["foreign_key"].split(".")[0])
                pair = tuple(sorted((m["name"], tgt)))
                if tgt in names and tgt != m["name"] and pair not in pairs:
                    pairs.add(pair)  # type: ignore[arg-type]
                    edges.append({"source": m["name"], "target": tgt, "type": "foreign_key", "weight": 1, "data": {"field": x["name"]}})
    for m in f.get("db_models", []):
        for r in sorted(m.get("relationships", []), key=lambda r: 0 if r.get("kind") in ("many_to_one", "foreign_key") else 1):
            tgt = tables.get(r.get("target"), r.get("target"))
            pair = tuple(sorted((m["name"], str(tgt))))
            if tgt in names and tgt != m["name"] and pair not in pairs:
                pairs.add(pair)  # type: ignore[arg-type]
                edges.append({"source": m["name"], "target": tgt, "type": r.get("kind") or "relationship", "weight": 1, "data": {"field": r.get("name")}})
    return {"nodes": nodes, "edges": edges, "truncated": False}


@router.get("/{pid}/files")
def files(pid: str, settings: Settings = Depends(get_settings), db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    require_project(db, pid)
    f = _facts(settings, pid)
    manifest = {m["path"]: m for m in f.get("manifest", [])}
    return [{**{k: x.get(k) for k in ("path", "language", "category", "lines", "size", "status", "status_reason", "is_entry_point", "has_secrets")},
             "analysis": manifest.get(x["path"], {}).get("status"), "analysis_reason": manifest.get(x["path"], {}).get("reason")} for x in f["files"]]


@router.get("/{pid}/documents")
def documents(pid: str, settings: Settings = Depends(get_settings), db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    require_project(db, pid)
    out = project_dir(settings, pid) / "output"
    if not out.exists():
        raise HTTPException(status_code=409, detail="Documents are not available (analysis not completed)")
    return _doc_index(out)


@router.get("/{pid}/documents/{rel:path}")
def document(pid: str, rel: str, settings: Settings = Depends(get_settings), db: Database = Depends(get_db)) -> PlainTextResponse:
    require_project(db, pid)
    p = _safe_doc(settings, pid, rel)
    media = "text/markdown; charset=utf-8" if p.suffix == ".md" else "application/json"
    return PlainTextResponse(p.read_text(encoding="utf-8"), media_type=media)


@router.get("/{pid}/search")
def search(pid: str, q: str = Query(min_length=2, max_length=200), settings: Settings = Depends(get_settings), db: Database = Depends(get_db)) -> dict[str, Any]:
    require_project(db, pid)
    out = project_dir(settings, pid) / "output"
    if not out.exists():
        raise HTTPException(status_code=409, detail="Documents are not available")
    needle = q.lower()
    results = []
    for d in _doc_index(out):
        if d["kind"] != "markdown":
            continue
        text = (out / d["path"]).read_text(encoding="utf-8")
        heading = ""
        for i, line in enumerate(text.splitlines(), 1):
            if line.startswith("#"):
                heading = line.lstrip("#").strip()
            if needle in line.lower():
                results.append({"path": d["path"], "title": d["title"], "line": i, "heading": heading, "snippet": line.strip()[:240]})
                if len(results) >= 300:
                    return {"query": q, "results": results, "truncated": True}
    return {"query": q, "results": results, "truncated": False}


@router.get("/{pid}/download/master")
def download_master(pid: str, settings: Settings = Depends(get_settings), db: Database = Depends(get_db)) -> FileResponse:
    p = require_project(db, pid)
    path = _safe_doc(settings, pid, MASTER)
    return FileResponse(path, media_type="text/markdown", filename=f"{package_name(p['name'])}-{MASTER}")


@router.get("/{pid}/download/package")
def download_package(pid: str, settings: Settings = Depends(get_settings), db: Database = Depends(get_db)) -> FileResponse:
    p = require_project(db, pid)
    path = project_dir(settings, pid) / f"{package_name(p['name'])}.zip"
    if not path.exists():
        raise HTTPException(status_code=409, detail="Package not available (analysis not completed)")
    return FileResponse(path, media_type="application/zip", filename=path.name)


@router.get("/{pid}/download/doc/{rel:path}")
def download_doc(pid: str, rel: str, settings: Settings = Depends(get_settings), db: Database = Depends(get_db)) -> FileResponse:
    require_project(db, pid)
    path = _safe_doc(settings, pid, rel)
    return FileResponse(path, media_type="text/markdown" if path.suffix == ".md" else "application/json", filename=path.name)
