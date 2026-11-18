"""End-to-end analysis pipeline with real progress events, cancellation and cleanup."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import shutil
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from app.core.config import ANALYSIS_VERSION, Settings
from app.schemas.facts import AIRunInfo, FileCategory, FileRecord, Finding, ProjectFacts
from app.services.ai.orchestrator import AIOptions, AIOrchestrator, AnalysisCancelled
from app.services.ai.providers.base import ProviderConfig, ProviderError
from app.services.ai.providers.registry import build_provider
from app.services.architecture.analyzer import (
    aggregate_env,
    detect_components,
    mark_dependency_usage,
    match_client_calls,
    merge_db_models,
    project_constants,
    resolve_routes,
    test_summary,
)
from app.services.architecture.graph import ImportResolver, build_graph
from app.services.context.compiler import compile_context, validate_outputs
from app.services.dependency.manifests import parse_manifests
from app.services.dependency.techstack import detect_stack
from app.services.export.packager import build_zip, package_name
from app.services.extraction.safe_zip import ZipLimits, safe_extract
from app.services.issues.detector import detect_issues
from app.services.parsing.base import ParseResult
from app.services.parsing.registry import parser_for, safe_parse
from app.services.scanning.scanner import scan_repository
from app.services.security.scanner import ScanContext, scan_security
from app.services.security.secrets import redact_text

log = logging.getLogger(__name__)

STAGES: list[tuple[str, str]] = [
    ("uploading", "Uploading"),
    ("extracting", "Extracting archive"),
    ("scanning", "Scanning repository"),
    ("stack", "Detecting technology stack"),
    ("parsing", "Parsing source code"),
    ("mapping", "Mapping dependencies"),
    ("architecture", "Analysing architecture"),
    ("business_logic", "Analysing business logic"),
    ("issues", "Reviewing potential issues"),
    ("markdown", "Generating Markdown"),
    ("validating", "Validating output"),
    ("complete", "Completing analysis"),
]

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class AnalysisJob:
    project_id: str
    name: str
    description: str | None
    archive: Path
    workdir: Path
    depth: str
    exclusions: list[str]
    token_budget: int
    max_file_kb: int
    max_concurrency: int
    send_source: bool
    use_cache: bool
    keep_archive: bool
    provider_config: ProviderConfig | None
    cancel: asyncio.Event = field(default_factory=asyncio.Event)


class Cancelled(Exception):
    pass


def compute_fingerprint(facts: ProjectFacts) -> str:
    h = hashlib.sha256()
    for f in sorted(facts.files, key=lambda x: x.path):
        if f.status == "included":
            h.update(f.path.encode())
            h.update(f.sha256.encode())
    return h.hexdigest()


def readme_excerpt(root: Path, paths: list[str]) -> str | None:
    cands = sorted([p for p in paths if PurePosixPath(p).name.lower().startswith("readme")], key=lambda p: (p.count("/"), len(p)))
    if not cands:
        return None
    try:
        text = (root / cands[0]).read_text(encoding="utf-8", errors="replace")[:6000]
    except OSError:
        return None
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[!\[.*?\]\(.*?\)\]\(.*?\)", "", text)
    lines = [ln.rstrip() for ln in text.splitlines()]
    body: list[str] = []
    for ln in lines:
        if ln.startswith("```"):
            break
        if ln.strip() or body:
            body.append(ln)
        if sum(len(x) for x in body) > 1200:
            break
    # demote Markdown headings so the excerpt cannot break the generated document's heading hierarchy
    body = [re.sub(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*\s*$", r"**\1**", ln) for ln in body]
    out = "\n".join(body).strip()
    out, _ = redact_text(out)
    return out[:1400] or None


class PipelineRunner:
    def __init__(self, settings: Settings, emit: EmitFn) -> None:
        self.settings = settings
        self.emit = emit
        self._stage_started: dict[str, float] = {}

    async def stage(self, key: str, status: str, done: int | None = None, total: int | None = None, detail: str = "") -> None:
        now = time.monotonic()
        if status == "running" and key not in self._stage_started:
            self._stage_started[key] = now
        elapsed = round(now - self._stage_started.get(key, now), 2)
        await self.emit({"type": "stage", "stage": key, "status": status, "done": done, "total": total, "detail": detail, "elapsed_s": elapsed})

    def _check(self, job: AnalysisJob) -> None:
        if job.cancel.is_set():
            raise Cancelled()

    async def run(self, job: AnalysisJob) -> dict[str, Any]:
        s = self.settings
        src = job.workdir / "src"
        out_dir = job.workdir / "output"
        started = time.monotonic()
        try:
            await self.stage("uploading", "done", 1, 1, f"Received {job.archive.stat().st_size / 1_048_576:.2f} MB archive")

            # ---------------------------------------------------------------- extract
            self._check(job)
            await self.stage("extracting", "running", detail="Validating and extracting archive safely")
            limits = ZipLimits(max_archive_bytes=s.max_upload_mb * 1_048_576, max_total_bytes=s.max_extracted_mb * 1_048_576,
                               max_files=s.max_file_count, max_file_bytes=s.max_single_file_mb * 1_048_576,
                               max_ratio=s.max_compression_ratio, timeout_s=s.extraction_timeout_s)
            if src.exists():
                shutil.rmtree(src)
            ext = await asyncio.to_thread(safe_extract, job.archive, src, limits, job.exclusions)
            await self.stage("extracting", "done", len(ext.extracted), len(ext.extracted) + len(ext.excluded) + len(ext.skipped),
                             f"{len(ext.extracted)} files extracted, {len(ext.excluded)} excluded, {len(ext.skipped)} skipped"
                             + (f" (stripped top-level folder '{ext.stripped_prefix}')" if ext.stripped_prefix else ""))

            # ---------------------------------------------------------------- scan
            self._check(job)
            await self.stage("scanning", "running", 0, len(ext.extracted), "Classifying files")
            root_name = ext.stripped_prefix or job.name
            overview, files, tree = await asyncio.to_thread(scan_repository, src, root_name, job.exclusions, ext.excluded, ext.skipped)
            facts = ProjectFacts(project_id=job.project_id, project_name=job.name, description=job.description, overview=overview, files=files,
                                 tree=tree, analysis_version=ANALYSIS_VERSION, depth=job.depth,
                                 generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
                                 ai=AIRunInfo(provider=job.provider_config.provider if job.provider_config else "none",
                                              model=job.provider_config.model if job.provider_config else None))
            facts.fingerprint = compute_fingerprint(facts)
            await self.stage("scanning", "done", overview.included_files, overview.total_files,
                             f"{overview.included_files} files classified, {len(overview.languages)} languages, {overview.code_lines:,} code lines")

            # ---------------------------------------------------------------- stack
            self._check(job)
            await self.stage("stack", "running", detail="Reading dependency manifests and configuration")
            all_paths = {f.path for f in files if f.status == "included"}
            manifests, warns = await asyncio.to_thread(parse_manifests, src, overview.manifests, all_paths)
            facts.warnings.extend(warns)
            techs, deps, configs, env_defs, build_cmds, warns2 = await asyncio.to_thread(detect_stack, src, overview, files, manifests)
            facts.warnings.extend(warns2)
            facts.technologies, facts.dependencies, facts.config_files, facts.build_commands = techs, deps, configs, build_cmds
            await self.stage("stack", "done", len(manifests), len(overview.manifests),
                             f"{len(techs)} technologies, {len(deps)} dependencies from {len(manifests)} manifests")

            # ---------------------------------------------------------------- parse
            self._check(job)
            parseable = [f for f in files if parser_for(f) is not None]
            await self.stage("parsing", "running", 0, len(parseable), "AST / tree-sitter / heuristic extraction")
            results: list[ParseResult] = []
            cache_dir = s.cache_dir / "parse"
            cache_dir.mkdir(parents=True, exist_ok=True)
            max_bytes = job.max_file_kb * 1024

            def parse_chunk(chunk: list[FileRecord]) -> list[tuple[FileRecord, ParseResult | None, str | None]]:
                out: list[tuple[FileRecord, ParseResult | None, str | None]] = []
                for rec in chunk:
                    if rec.size > max_bytes:
                        out.append((rec, None, f"larger than the {job.max_file_kb} KB parse limit"))
                        continue
                    res, err = safe_parse(src, rec, cache_dir, max_bytes)
                    out.append((rec, res, err))
                return out

            for i in range(0, len(parseable), 40):
                self._check(job)
                chunk = parseable[i : i + 40]
                for rec, res, err in await asyncio.to_thread(parse_chunk, chunk):
                    if res is not None:
                        results.append(res)
                    elif err:
                        rec.status, rec.status_reason = ("skipped" if "limit" in err else "failed"), f"parser: {err}"
                await self.stage("parsing", "running", min(i + 40, len(parseable)), len(parseable), f"Parsed {min(i + 40, len(parseable))}/{len(parseable)} files")
            facts.modules = [r.module for r in results]
            syms = sum(len(m.symbols) for m in facts.modules)
            await self.stage("parsing", "done", len(results), len(parseable), f"{len(results)} files parsed, {syms} symbols extracted")

            # ---------------------------------------------------------------- mapping
            self._check(job)
            await self.stage("mapping", "running", detail="Resolving imports, routes and data models")
            go_modules = {m.name: (str(PurePosixPath(m.path).parent) if "/" in m.path else "") for m in manifests if m.ecosystem == "go" and m.name}
            resolver = ImportResolver(files, configs, go_modules)
            for m in facts.modules:
                for imp in m.imports:
                    resolver.resolve(imp, m.language)
            facts.graph = build_graph(facts.modules, files)
            facts.routes = resolve_routes(results, resolver)
            facts.client_calls = match_client_calls([c for r in results for c in r.client_calls], facts.routes, project_constants(results))
            facts.db_models = merge_db_models([d for r in results for d in r.db_models])
            facts.db_operations = [o for r in results for o in r.db_operations]
            facts.migrations = [f.path for f in files if f.category == FileCategory.MIGRATION and f.status == "included"]
            mark_dependency_usage(facts.dependencies, facts.modules, files)
            facts.env_vars = aggregate_env(env_defs, facts.modules)
            facts.components = detect_components(facts.modules, files, facts.technologies)
            facts.test_info = test_summary(files, facts.technologies, facts.build_commands)
            facts.readme_excerpt = readme_excerpt(src, sorted(all_paths))
            # intermediate result storage: deterministic facts survive any AI failure
            (job.workdir / "deterministic_facts.json").write_text(facts.model_dump_json(), encoding="utf-8")
            await self.stage("mapping", "done", len(facts.graph.edges), None,
                             f"{len([e for e in facts.graph.edges if e.type == 'imports'])} internal imports, {len(facts.routes)} routes, "
                             f"{len(facts.db_models)} data models, {len(facts.graph.cycles)} cycles")

            # ---------------------------------------------------------------- AI (stages B-E)
            self._check(job)
            await self.stage("architecture", "running", detail="Preparing AI analysis" if job.provider_config else "AI disabled — deterministic analysis only")
            provider = None
            if job.provider_config is not None:
                try:
                    provider = build_provider(job.provider_config)
                except ProviderError as exc:
                    facts.ai.errors.append(f"Provider could not be initialised: {exc}")
                    facts.warnings.append(f"AI analysis skipped: {exc}")

            async def ai_progress(stage: str, done: int, total: int, detail: str) -> None:
                await self.stage(stage, "running", done, total, detail)

            orch = AIOrchestrator(provider, job.provider_config if provider else None,
                                  AIOptions(depth=job.depth, token_budget=job.token_budget, max_concurrency=job.max_concurrency,
                                            send_source=job.send_source, use_cache=job.use_cache),
                                  (s.cache_dir / "ai") if job.use_cache else None, ai_progress, job.cancel)
            if job.use_cache:
                (s.cache_dir / "ai").mkdir(parents=True, exist_ok=True)
            try:
                await orch.run(facts, src)
            except AnalysisCancelled as exc:
                raise Cancelled() from exc
            except Exception as exc:  # AI must never break the deterministic package
                log.exception("AI orchestration failed")
                facts.ai.errors.append(f"AI orchestration failed: {type(exc).__name__}: {exc}")
            finally:
                if provider is not None:
                    await provider.aclose()
            ai_on = facts.ai.enabled
            arch_detail = (f"{len(facts.file_summaries)} files and {len(facts.module_summaries)} modules interpreted; stages "
                           + ", ".join(f"{k}={v}" for k, v in sorted(facts.ai.stages.items()))) if ai_on else "Skipped: no AI provider configured"
            await self.stage("architecture", "done" if ai_on else "skipped", detail=arch_detail)
            await self.stage("business_logic", "done" if ai_on and facts.ai.stages.get("E") in ("ok", "partial") else "skipped",
                             detail=f"{len(facts.synthesis.workflows)} workflows traced" if ai_on else "Skipped: no AI provider configured")

            # ---------------------------------------------------------------- issues
            self._check(job)
            await self.stage("issues", "running", detail="Security, reliability and bug detectors")
            ctx = ScanContext(root=src, files=files, modules=facts.modules, routes=facts.routes, dependencies=facts.dependencies,
                              env_vars=facts.env_vars, technologies=facts.technologies)
            sec, secrets = await asyncio.to_thread(scan_security, ctx)
            issues = await asyncio.to_thread(detect_issues, ctx, facts.graph, facts.client_calls)
            ai_findings = [x for x in facts.findings if x.source == "ai"]
            det = _dedupe(sec + issues)
            facts.findings = det + _drop_overlapping(ai_findings, det)
            facts.secrets = secrets
            await self.stage("issues", "done", len(facts.findings), None,
                             f"{len(facts.findings)} findings ({sum(1 for x in facts.findings if x.severity in ('critical', 'high'))} critical/high), {len(secrets)} secrets redacted")

            # ---------------------------------------------------------------- markdown
            self._check(job)
            await self.stage("markdown", "running", detail="Compiling context documents")
            if out_dir.exists():
                shutil.rmtree(out_dir)
            docs = await asyncio.to_thread(compile_context, facts, out_dir)
            await self.stage("markdown", "done", len([d for d in docs if d.path.endswith(".md")]), None,
                             f"{len([d for d in docs if d.path.endswith('.md')])} Markdown documents, {sum(d.size for d in docs) / 1024:.0f} KB")

            # ---------------------------------------------------------------- validate
            self._check(job)
            await self.stage("validating", "running", detail="Checking completeness and source references")
            val: dict[str, Any] = await asyncio.to_thread(validate_outputs, facts, out_dir, docs)
            zip_path = job.workdir / f"{package_name(job.name)}.zip"
            await asyncio.to_thread(build_zip, out_dir, zip_path, job.name)
            await self.stage("validating", "done" if val["ok"] else "warning", val["source_references_checked"], None,
                             f"{val['source_references_checked']} source references checked, {len(val['invalid_source_references'])} invalid; "
                             f"{len(val['documents_missing'])} documents missing")

            # ---------------------------------------------------------------- complete
            stats = build_stats(facts, docs, time.monotonic() - started)
            await self.stage("complete", "done", detail=f"Finished in {stats['duration_s']:.1f}s")
            return stats
        finally:
            if not self.settings.keep_extracted_sources:
                shutil.rmtree(src, ignore_errors=True)
            if not job.keep_archive:
                job.archive.unlink(missing_ok=True)


def _dedupe(items: list[Finding]) -> list[Finding]:
    seen: set[str] = set()
    out = []
    for x in items:
        if x.id in seen:
            continue
        seen.add(x.id)
        out.append(x)
    return out


def _drop_overlapping(ai: list[Finding], det: list[Finding]) -> list[Finding]:
    out = []
    for a in ai:
        if any(d.file == a.file and d.line_start and a.line_start and abs(d.line_start - a.line_start) <= 2 for d in det):
            continue
        out.append(a)
    return out


def build_stats(facts: ProjectFacts, docs: list, duration: float) -> dict[str, Any]:  # type: ignore[type-arg]
    sev: dict[str, int] = {}
    for x in facts.findings:
        sev[x.severity] = sev.get(x.severity, 0) + 1
    status: dict[str, int] = {}
    for m in facts.manifest:
        status[m.status] = status.get(m.status, 0) + 1
    return {
        "duration_s": round(duration, 2),
        "fingerprint": facts.fingerprint,
        "files": facts.overview.total_files,
        "included_files": facts.overview.included_files,
        "source_files": facts.overview.source_files,
        "code_lines": facts.overview.code_lines,
        "languages": {k: v["code_lines"] for k, v in facts.overview.languages.items()},
        "frameworks": [t.name for t in facts.technologies if t.category == "framework"][:10],
        "routes": len(facts.routes),
        "db_models": len(facts.db_models),
        "dependencies": len(facts.dependencies),
        "symbols": sum(len(m.symbols) for m in facts.modules),
        "findings": len(facts.findings),
        "severity": sev,
        "secrets": len(facts.secrets),
        "coverage": status,
        "ai": {"enabled": facts.ai.enabled, "provider": facts.ai.provider, "model": facts.ai.model, "requests": facts.ai.requests,
               "failed_requests": facts.ai.failed_requests, "cached": facts.ai.cached_responses, "input_tokens": facts.ai.input_tokens_est,
               "output_tokens": facts.ai.output_tokens_est, "stages": facts.ai.stages, "errors": facts.ai.errors[:20]},
        "documents": len(docs),
        "output_valid": facts.output_validation.get("ok"),
    }
