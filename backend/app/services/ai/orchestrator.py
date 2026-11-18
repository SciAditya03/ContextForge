"""Multi-stage, dependency-aware AI analysis orchestration (stages B-F).

Stage A (deterministic extraction) happens before this runs. The orchestrator:
- prioritises files (entry points, routes, models, services, config first)
- groups related files (same module + import neighbours) into token-bounded batches
- runs file → module → cross-module → system synthesis stages hierarchically
- enforces a global token budget, bounded concurrency, retries with backoff
- caches responses, survives partial failures, honours cancellation
- validates every reference in the output against the real inventory (stage F)
- records exactly which files were analysed, skipped and why (analysis manifest)
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import random
import re
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.schemas.facts import (
    EvidenceClass,
    FileCategory,
    FileRecord,
    FileSummary,
    Finding,
    ManifestEntry,
    ModuleInfo,
    ModuleSummary,
    ProjectFacts,
    Workflow,
)
from app.services.ai import prompts
from app.services.ai.evidence import EvidenceValidator
from app.services.ai.providers.base import LLMProvider, LLMRequest, ProviderConfig, ProviderError
from app.services.ai.tokens import DEPTHS, DepthProfile, TokenBudget, estimate_tokens, truncate_lines
from app.services.architecture.graph import module_of
from app.services.security.secrets import redact_text

log = logging.getLogger(__name__)

ProgressFn = Callable[[str, int, int, str], Awaitable[None] | None]


class AnalysisCancelled(Exception):
    pass


@dataclass
class AIOptions:
    depth: str = "standard"
    token_budget: int = 400_000
    max_concurrency: int = 4
    send_source: bool = True
    use_cache: bool = True


ROLE_WEIGHTS = {
    "api-routes": 40, "controller": 32, "service": 32, "data-model": 34, "data-access": 26, "auth": 36, "middleware": 26,
    "repository": 26, "worker": 24, "config": 18, "schema": 18, "api-client": 22, "state": 16, "page": 16, "hook": 10,
    "ui-component": 6, "utility": 6, "types": 4, "middleware-registration": 20,
}


def prioritise(facts: ProjectFacts, profile: DepthProfile) -> list[tuple[ModuleInfo, float, str]]:
    """Return (module, score, reason) sorted by importance."""
    in_degree: dict[str, int] = defaultdict(int)
    for e in facts.graph.edges:
        if e.type == "imports":
            in_degree[e.target] += 1
    recs = {f.path: f for f in facts.files}
    scored = []
    for m in facts.modules:
        rec = recs.get(m.path)
        if rec is None:
            continue
        score = 0.0
        reasons = []
        if rec.is_entry_point:
            score += 50
            reasons.append("entry point")
        for r in m.roles:
            score += ROLE_WEIGHTS.get(r, 0)
        if m.roles:
            reasons.append("roles: " + ", ".join(m.roles[:3]))
        if in_degree[m.path]:
            score += min(30, in_degree[m.path] * 3)
            reasons.append(f"imported by {in_degree[m.path]} files")
        score += min(15, len(m.symbols) * 0.5) + min(10, rec.code_lines / 80)
        if rec.category == FileCategory.TEST:
            score -= 60
        if rec.generated:
            score -= 45
            reasons.append("generated code")
        if rec.category in (FileCategory.MIGRATION,):
            score -= 30
        if rec.category in (FileCategory.CONFIG, FileCategory.BUILD) and not m.symbols:
            score -= 20
        if rec.code_lines < 3:
            score -= 25
        scored.append((m, score, "; ".join(reasons) or "source file"))
    scored.sort(key=lambda t: -t[1])
    return scored


class AIOrchestrator:
    def __init__(
        self,
        provider: LLMProvider | None,
        config: ProviderConfig | None,
        options: AIOptions,
        cache_dir: Path | None,
        progress: ProgressFn | None = None,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        self.provider = provider
        self.config = config
        self.options = options
        self.profile = DEPTHS.get(options.depth, DEPTHS["standard"])
        self.cache_dir = cache_dir
        self.progress = progress
        self.cancel = cancel_event or asyncio.Event()
        self.budget = TokenBudget(total=options.token_budget)
        self.sem = asyncio.Semaphore(max(1, options.max_concurrency))
        self.validator: EvidenceValidator | None = None
        self._raw_issues: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ infra
    async def _emit(self, stage: str, done: int, total: int, detail: str) -> None:
        if self.progress is None:
            return
        r = self.progress(stage, done, total, detail)
        if asyncio.iscoroutine(r):
            await r

    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise AnalysisCancelled()

    def _cache_key(self, req: LLMRequest) -> str:
        assert self.config is not None
        payload = json.dumps([self.config.provider, self.config.model, self.config.temperature, self.config.effort,
                              req.max_output_tokens or self.config.max_output_tokens, req.system, req.prompt])
        return hashlib.sha256(payload.encode()).hexdigest()

    async def _call(self, facts: ProjectFacts, req: LLMRequest, expected_out: int, keep_for_later: int = 0) -> dict[str, Any] | None:
        """Budget-checked, cached, retried call that returns parsed JSON (or None on failure)."""
        assert self.provider is not None and self.config is not None
        ai = facts.ai
        est_in = estimate_tokens(req.system) + estimate_tokens(req.prompt)
        if not self.budget.can_afford(est_in + expected_out, keep_for_later):
            ai.errors.append(f"{req.stage}: skipped request (~{est_in + expected_out} tokens) — token budget exhausted ({self.budget.used}/{self.budget.total} used)")
            return None
        key = self._cache_key(req)
        cache_file = self.cache_dir / f"{key}.json" if (self.cache_dir is not None and self.options.use_cache) else None
        if cache_file is not None and cache_file.exists():
            try:
                cached = json.loads(cache_file.read_text(encoding="utf-8"))
                ai.cached_responses += 1
                parsed = _parse_json(cached["text"])
                if parsed is not None:
                    return parsed
            except (OSError, ValueError, KeyError):
                pass
        text = await self._request_with_retry(facts, req, est_in)
        if text is None:
            return None
        parsed = _parse_json(text)
        if parsed is None:
            # one repair attempt
            repair = LLMRequest(system=req.system, prompt=prompts.REPAIR_PROMPT + text[:4000] + "\n\nOriginal task:\n" + req.prompt[:20000],
                                max_output_tokens=req.max_output_tokens, stage=req.stage + ":repair")
            text2 = await self._request_with_retry(facts, repair, estimate_tokens(repair.prompt))
            parsed = _parse_json(text2) if text2 else None
            if parsed is None:
                ai.errors.append(f"{req.stage}: model output was not valid JSON after one repair attempt")
                return None
            text = text2 or text
        if cache_file is not None:
            with contextlib.suppress(OSError):
                cache_file.write_text(json.dumps({"text": text, "model": self.config.model}), encoding="utf-8")
        return parsed

    async def _request_with_retry(self, facts: ProjectFacts, req: LLMRequest, est_in: int) -> str | None:
        assert self.provider is not None and self.config is not None
        ai = facts.ai
        # last line of defence: nothing that looks like a credential leaves the process
        req = LLMRequest(system=req.system, prompt=redact_text(req.prompt)[0], json_mode=req.json_mode,
                         max_output_tokens=req.max_output_tokens, stage=req.stage)
        attempts = max(1, self.config.retries + 1)
        delay = 2.0
        for attempt in range(1, attempts + 1):
            self._check_cancel()
            async with self.sem:
                self._check_cancel()
                ai.requests += 1
                try:
                    resp = await self.provider.complete(req)
                except ProviderError as exc:
                    ai.failed_requests += 1
                    retry = exc.retryable and attempt < attempts
                    log.warning("AI request failed (%s, attempt %d/%d): %s", req.stage, attempt, attempts, exc)
                    if not retry:
                        ai.errors.append(f"{req.stage}: {exc}")
                        if exc.status in (401, 403):
                            raise  # misconfiguration: stop all AI stages
                        return None
                    wait = exc.retry_after if exc.retry_after is not None else delay + random.uniform(0, delay / 2)
                    delay = min(delay * 2, 60)
                else:
                    in_tok = resp.input_tokens if resp.input_tokens is not None else est_in
                    out_tok = resp.output_tokens if resp.output_tokens is not None else estimate_tokens(resp.text)
                    ai.input_tokens_est += in_tok
                    ai.output_tokens_est += out_tok
                    self.budget.spend(in_tok + out_tok)
                    if resp.finish_reason in ("length", "max_tokens", "MAX_TOKENS"):
                        ai.errors.append(f"{req.stage}: response hit the output token limit; result may be partial")
                    return resp.text
            await asyncio.sleep(min(wait, 90))
        return None

    # ------------------------------------------------------------------ public
    async def run(self, facts: ProjectFacts, root: Path) -> None:
        ai = facts.ai
        file_lines = {f.path: f.lines for f in facts.files if f.status == "included"}
        self.validator = EvidenceValidator(file_lines)
        ranked = prioritise(facts, self.profile)
        manifest: dict[str, ManifestEntry] = {}
        for f in facts.files:
            if f.status != "included":
                manifest[f.path] = ManifestEntry(path=f.path, status=f.status if f.status in ("excluded", "skipped", "failed") else "skipped", reason=f.status_reason)
            else:
                manifest[f.path] = ManifestEntry(path=f.path, status="deterministic_only", reason="not a parseable source file" if f.path not in {m.path for m in facts.modules} else None, stages=["A"])
        facts.manifest = list(manifest.values())
        if self.provider is None or self.config is None:
            ai.enabled = False
            for e in facts.manifest:
                if e.status == "deterministic_only" and e.reason is None:
                    e.reason = "AI analysis disabled (no provider configured)"
            for s in ("B", "C", "D", "E", "F"):
                ai.stages[s] = "skipped"
            return
        ai.enabled = True
        ai.token_budget = self.budget.total

        try:
            await self._stage_b(facts, root, ranked, manifest)
            await self._stage_c(facts)
            await self._stage_d(facts)
            await self._stage_e(facts, root)
        except AnalysisCancelled:
            raise
        except ProviderError as exc:
            ai.errors.append(f"AI analysis stopped: {exc}")
            for s in ("B", "C", "D", "E"):
                ai.stages.setdefault(s, "failed")
        finally:
            for e in facts.manifest:
                if e.status == "deterministic_only" and e.reason is None:
                    e.reason = "lower priority than the AI file budget for this analysis depth"
            ai.validation = dict(self.validator.stats)
            ai.stages["F"] = "ok"

    # ------------------------------------------------------------------ stage B
    def _project_ctx(self, facts: ProjectFacts) -> dict[str, Any]:
        return {
            "name": facts.project_name,
            "description": facts.description,
            "languages": list(facts.overview.languages.keys())[:8],
            "frameworks": sorted({t.name for t in facts.technologies if t.category in ("framework", "orm", "database", "auth")})[:20],
            "entry_points": facts.overview.entry_points[:10],
        }

    def _file_block(self, facts: ProjectFacts, root: Path, m: ModuleInfo, rec: FileRecord) -> tuple[str, bool]:
        sym_lines = []
        for s in m.symbols[:60]:
            if s.kind in ("attribute", "variable") and s.parent:
                continue
            label = s.signature or s.name
            sym_lines.append(f"- {s.kind} {(s.parent + '.') if s.parent else ''}{label} [L{s.line_start}-{s.line_end}]")
        routes = [f"- {r.method} {r.path} -> {r.handler} [L{r.line}]" for r in facts.routes if r.file == m.path][:20]
        models = [f"- {d.name} ({d.orm}, table={d.table}) [L{d.line}]" for d in facts.db_models if d.file == m.path][:20]
        head = f"=== FILE: {m.path} ({m.language}, {rec.lines} lines, roles: {', '.join(m.roles) or 'none'}) ==="
        parts = [head, "Deterministic symbols:", *(sym_lines or ["- (none extracted)"])]
        if routes:
            parts += ["Routes:", *routes]
        if models:
            parts += ["Data models:", *models]
        truncated = False
        if self.options.send_source and rec.category != FileCategory.ENV_FILE:
            try:
                text = (root / m.path).read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            text, _n = redact_text(text)
            numbered, included, total = truncate_lines(text, self.profile.per_file_chars)
            truncated = included < total
            parts += ["--- source (line-numbered) ---", numbered]
        else:
            parts += ["--- source not sent (privacy setting: structure only) ---"]
        return "\n".join(parts), truncated

    async def _stage_b(self, facts: ProjectFacts, root: Path, ranked: list[tuple[ModuleInfo, float, str]], manifest: dict[str, ManifestEntry]) -> None:
        recs = {f.path: f for f in facts.files}
        candidates = []
        for m, score, reason in ranked:
            rec = recs[m.path]
            if rec.category == FileCategory.TEST and not self.profile.include_tests:
                manifest[m.path].reason = "test file (included only at 'deep' analysis depth)"
                continue
            if rec.code_lines == 0:
                manifest[m.path].reason = "no code lines"
                continue
            candidates.append((m, score, reason))
        selected = candidates[: self.profile.max_ai_files]
        for m, _s, _r in candidates[self.profile.max_ai_files :]:
            manifest[m.path].reason = f"outside the top {self.profile.max_ai_files} files selected for '{self.profile.name}' depth"

        # related-file grouping: seed with the highest-priority file, add same-module + import neighbours
        neighbours: dict[str, set[str]] = defaultdict(set)
        for e in facts.graph.edges:
            if e.type == "imports":
                neighbours[e.source].add(e.target)
                neighbours[e.target].add(e.source)
        blocks: dict[str, tuple[str, bool]] = {}
        for m, _s, _r in selected:
            blocks[m.path] = self._file_block(facts, root, m, recs[m.path])
        remaining = [m.path for m, _s, _r in selected]
        batches: list[list[str]] = []
        while remaining:
            seed = remaining.pop(0)
            batch = [seed]
            size = estimate_tokens(blocks[seed][0])
            related = [p for p in remaining if p in neighbours[seed] or module_of(p) == module_of(seed)]
            others = [p for p in remaining if p not in related]
            for p in related + others:
                t = estimate_tokens(blocks[p][0])
                if size + t > self.profile.batch_tokens or len(batch) >= 12:
                    if p in related:
                        continue
                    break
                batch.append(p)
                size += t
            for p in batch[1:]:
                remaining.remove(p)
            batches.append(batch)

        ctx = self._project_ctx(facts)
        total = len(batches)
        done = 0
        await self._emit("architecture", 0, total, f"File-level AI analysis: {len(selected)} files in {total} batches")
        # reserve ~35% of the budget for stages C-E
        reserve = int(self.budget.total * 0.35)
        summaries: dict[str, FileSummary] = {}
        failures = 0

        async def run_batch(batch: list[str]) -> None:
            nonlocal done, failures
            prompt = prompts.file_stage_prompt(ctx, [blocks[p][0] for p in batch])
            expected = min(self.config.max_output_tokens if self.config else 4000, 700 * len(batch) + 400)
            req = LLMRequest(system=prompts.SYSTEM_PROMPT, prompt=prompt, max_output_tokens=max(2000, expected * 2), stage="B:file")
            data = await self._call(facts, req, expected, keep_for_later=reserve)
            got = set()
            if data:
                for entry in data.get("files", []) or []:
                    if not isinstance(entry, dict):
                        continue
                    path = self.validator._resolve(str(entry.get("path", ""))) if self.validator else None
                    if path is None or path not in batch:
                        continue
                    claims = self.validator.claims(entry.get("claims", []), "B") if self.validator else []
                    notes = [str(n) for n in entry.get("notes", []) or []][:8]
                    notes += [c.text + " " + " ".join(s.label() for s in c.sources) for c in claims[:6]]
                    summaries[path] = FileSummary(path=path, purpose=str(entry.get("purpose", "")).strip()[:600],
                                                  responsibilities=[str(x) for x in entry.get("responsibilities", []) or []][:8],
                                                  key_symbols=[str(x) for x in entry.get("key_symbols", []) or []][:12], notes=notes)
                    got.add(path)
            for p in batch:
                me = manifest[p]
                me.tokens += estimate_tokens(blocks[p][0])
                if p in got:
                    me.status = "analysed"
                    me.stages = ["A", "B"]
                    me.reason = "analysed; source truncated to per-file budget" if blocks[p][1] else None
                else:
                    me.status = "failed" if data is None else "deterministic_only"
                    me.reason = "AI request failed or was skipped (see AI errors)" if data is None else "model returned no summary for this file"
            if data is None:
                failures += 1
            done += 1
            await self._emit("architecture", done, total, f"File-level AI analysis: batch {done}/{total}")

        await asyncio.gather(*(run_batch(b) for b in batches))
        facts.file_summaries = [summaries[p] for p in [m.path for m, _s, _r in selected] if p in summaries]
        facts.ai.stages["B"] = "ok" if failures == 0 else ("failed" if failures == total else "partial")

    # ------------------------------------------------------------------ stage C
    async def _stage_c(self, facts: ProjectFacts) -> None:
        self._check_cancel()
        summ = {s.path: s for s in facts.file_summaries}
        groups: dict[str, list[ModuleInfo]] = defaultdict(list)
        for m in facts.modules:
            groups[module_of(m.path)].append(m)
        mod_edges: dict[str, list[str]] = defaultdict(list)
        for e in facts.graph.module_edges:
            mod_edges[e.source].append(f"{e.target} (x{e.weight})")
        # only modules with at least one analysed file or important roles
        items = []
        for mod, ms in sorted(groups.items()):
            files = []
            for m in ms[:25]:
                s = summ.get(m.path)
                files.append({"path": m.path, "roles": m.roles, "purpose": s.purpose if s else None,
                              "key_symbols": (s.key_symbols if s else [x.name for x in m.symbols if x.parent is None][:10])})
            if not any(f["purpose"] for f in files) and not any(f["roles"] for f in files):
                continue
            items.append({"module": mod, "files": files, "imports_modules": mod_edges.get(mod, [])[:15]})
        if not items:
            facts.ai.stages["C"] = "skipped"
            return
        ctx = self._project_ctx(facts)
        chunks = [items[i : i + self.profile.module_batch] for i in range(0, len(items), self.profile.module_batch)]
        await self._emit("architecture", 0, len(chunks), f"Module-level AI analysis: {len(items)} modules")
        results: list[ModuleSummary] = []
        fails = 0
        done = 0
        reserve = int(self.budget.total * 0.2)

        async def run(chunk: list[dict[str, Any]]) -> None:
            nonlocal fails, done
            req = LLMRequest(system=prompts.SYSTEM_PROMPT, prompt=prompts.module_stage_prompt(ctx, chunk), max_output_tokens=6000, stage="C:module")
            data = await self._call(facts, req, 300 * len(chunk), keep_for_later=reserve)
            if data is None:
                fails += 1
            else:
                names = {c["module"] for c in chunk}
                for e in data.get("modules", []) or []:
                    if isinstance(e, dict) and e.get("module") in names:
                        results.append(ModuleSummary(module=e["module"], purpose=str(e.get("purpose", ""))[:600],
                                                     files=[f["path"] for c in chunk if c["module"] == e["module"] for f in c["files"]],
                                                     responsibilities=[str(x) for x in e.get("responsibilities", []) or []][:8],
                                                     interactions=[str(x) for x in e.get("interactions", []) or []][:8]))
            done += 1
            await self._emit("architecture", done, len(chunks), f"Module-level AI analysis: {done}/{len(chunks)}")

        await asyncio.gather(*(run(c) for c in chunks))
        facts.module_summaries = sorted(results, key=lambda m: m.module)
        for me in facts.manifest:
            if any(me.path in ms.files for ms in results) and "C" not in me.stages and me.status == "analysed":
                me.stages.append("C")
        facts.ai.stages["C"] = "ok" if fails == 0 else ("failed" if fails == len(chunks) else "partial")

    # ------------------------------------------------------------------ stage D
    async def _stage_d(self, facts: ProjectFacts) -> None:
        self._check_cancel()
        await self._emit("architecture", 0, 1, "Cross-module relationship analysis")
        payload = {
            "modules": [{"module": m.module, "purpose": m.purpose, "interactions": m.interactions} for m in facts.module_summaries][:80],
            "module_edges": [{"from": e.source, "to": e.target, "weight": e.weight} for e in sorted(facts.graph.module_edges, key=lambda e: -e.weight)][:150],
            "routes": [{"method": r.method, "path": r.path, "handler": r.handler, "file": r.file, "line": r.line, "auth": r.auth, "calls": r.calls[:10]} for r in facts.routes][:150],
            "client_calls": [{"file": c.file, "line": c.line, "method": c.method, "url": c.url, "matched_route": c.matched_route} for c in facts.client_calls][:100],
            "db_models": [{"name": d.name, "table": d.table, "orm": d.orm, "file": d.file, "line": d.line, "relationships": [r.get("target") for r in d.relationships]} for d in facts.db_models][:80],
            "external_technologies": [{"name": t.name, "category": t.category, "evidence": [e.label() for e in t.evidence[:2]]} for t in facts.technologies if t.category in ("integration", "cloud", "queue", "cache", "storage", "database", "auth", "http_client", "realtime", "ai")],
            "layers": [{"layer": c.layer, "files": c.files[:15]} for c in facts.components],
        }
        req = LLMRequest(system=prompts.SYSTEM_PROMPT, prompt=prompts.cross_module_prompt(payload), max_output_tokens=8000, stage="D:cross-module")
        data = await self._call(facts, req, 3000, keep_for_later=int(self.budget.total * 0.1))
        v = self.validator
        assert v is not None
        if data is None:
            facts.ai.stages["D"] = "failed"
            return
        syn = facts.synthesis
        syn.module_interactions = v.claims(data.get("module_interactions"), "D")
        syn.frontend_backend = v.claims(data.get("frontend_backend"), "D")
        syn.data_flow = v.claims(data.get("data_flow"), "D")
        syn.integrations = v.claims(data.get("integrations"), "D")
        facts.ai.stages["D"] = "ok"
        await self._emit("architecture", 1, 1, "Cross-module relationship analysis complete")

    # ------------------------------------------------------------------ stage E
    async def _stage_e(self, facts: ProjectFacts, root: Path) -> None:
        self._check_cancel()
        v = self.validator
        assert v is not None
        auth_files = sorted({r.file for r in facts.routes if r.auth} | {m.path for m in facts.modules if "auth" in m.roles})[:20]
        base = {
            "project": self._project_ctx(facts),
            "overview": {"files": facts.overview.included_files, "code_lines": facts.overview.code_lines, "languages": facts.overview.languages,
                         "entry_points": facts.overview.entry_points, "subprojects": facts.overview.subprojects},
            "technologies": [{"name": t.name, "category": t.category, "classification": t.classification.value} for t in facts.technologies][:80],
            "layers": [{"layer": c.layer, "files": c.files[:12], "classification": c.classification.value} for c in facts.components],
            "modules": [{"module": m.module, "purpose": m.purpose, "responsibilities": m.responsibilities[:5]} for m in facts.module_summaries][:80],
            "interactions": [c.text for c in facts.synthesis.module_interactions + facts.synthesis.data_flow][:30],
            "routes": [{"method": r.method, "path": r.path, "handler": r.handler, "file": f"{r.file}:{r.line}", "auth": r.auth} for r in facts.routes][:120],
            "db_models": [{"name": d.name, "table": d.table, "orm": d.orm, "file": f"{d.file}:{d.line}", "fields": [f.name for f in d.fields][:15]} for d in facts.db_models][:60],
            "env_vars": [e.name for e in facts.env_vars][:80],
            "auth_related_files": auth_files,
            "auth_symbols": [{"name": s.name, "file": f"{s.file}:{s.line_start}-{s.line_end}", "signature": s.signature} for m in facts.modules if m.path in auth_files for s in m.symbols if s.kind in ("function", "method", "class")][:60],
            "cycles": facts.graph.cycles[:10],
            "file_summaries": [{"path": s.path, "purpose": s.purpose} for s in facts.file_summaries][:120],
        }
        await self._emit("architecture", 0, 1, "System-level synthesis")
        req = LLMRequest(system=prompts.SYSTEM_PROMPT, prompt=prompts.synthesis_prompt(base), max_output_tokens=10000, stage="E1:synthesis")
        data = await self._call(facts, req, 4000, keep_for_later=int(self.budget.total * 0.04))
        syn = facts.synthesis
        e1_ok = data is not None
        if data:
            purpose = v.claims([data.get("purpose")], "E") if data.get("purpose") else []
            syn.purpose = purpose[0] if purpose else None
            syn.executive_summary = v.claims(data.get("executive_summary"), "E")
            syn.architecture = v.claims(data.get("architecture"), "E")
            syn.authentication = v.claims(data.get("authentication"), "E")
            syn.architectural_decisions = v.claims(data.get("architectural_decisions"), "E")
            syn.technical_debt = v.claims(data.get("technical_debt"), "E")
            syn.debugging_entry_points = v.claims(data.get("debugging_entry_points"), "E")
            syn.open_questions = [str(q) for q in data.get("open_questions", []) or []][:25]
        await self._emit("architecture", 1, 1, "System-level synthesis complete")

        # E2: business logic — include call graphs of route handlers and service functions
        self._check_cancel()
        await self._emit("business_logic", 0, 1, "Tracing workflows and business logic")
        sym_by_file: dict[str, list[dict[str, Any]]] = defaultdict(list)
        important = {m.path for m in facts.modules if {"service", "api-routes", "controller", "data-access", "worker", "auth", "repository"} & set(m.roles)}
        for m in facts.modules:
            if m.path not in important:
                continue
            for s in m.symbols:
                if s.kind in ("function", "method", "component", "hook") and (s.calls or s.raises):
                    sym_by_file[m.path].append({"name": f"{s.parent + '.' if s.parent else ''}{s.name}", "lines": f"{s.line_start}-{s.line_end}",
                                                "calls": s.calls[:15], "raises": s.raises[:5], "handles_exceptions": s.handles_exceptions})
        det_findings = [{"title": f.title, "file": f.file, "line": f.line_start} for f in facts.findings[:60]]
        payload = {
            "project": self._project_ctx(facts),
            "routes": base["routes"],
            "functions_by_file": {k: v_[:25] for k, v_ in list(sym_by_file.items())[:60]},
            "db_operations": [{"file": f"{o.file}:{o.line}", "op": o.operation, "target": o.target} for o in facts.db_operations][:150],
            "db_models": base["db_models"],
            "file_summaries": [{"path": s.path, "purpose": s.purpose, "notes": s.notes[:4]} for s in facts.file_summaries if s.path in important][:80],
            "module_summaries": base["modules"],
            "deterministic_findings_already_reported": det_findings,
        }
        req = LLMRequest(system=prompts.SYSTEM_PROMPT, prompt=prompts.business_prompt(payload), max_output_tokens=12000, stage="E2:business")
        data2 = await self._call(facts, req, 5000)
        if data2:
            syn.business_logic = v.claims(data2.get("business_logic"), "E")
            syn.core_functionality = v.claims(data2.get("core_functionality"), "E")
            for w in (data2.get("workflows") or [])[:12]:
                if not isinstance(w, dict) or not w.get("name"):
                    continue
                srcs = v.refs(w.get("sources") or [])
                steps_text = " ".join(str(s) for s in w.get("steps", []) or [])
                phantom = v.phantom_paths(steps_text + " " + str(w.get("handler", "")))
                syn.workflows.append(Workflow(
                    name=str(w.get("name"))[:120], trigger=str(w.get("trigger", ""))[:300], handler=str(w.get("handler", ""))[:200],
                    steps=[str(s)[:300] for s in w.get("steps", []) or []][:15], input_data=str(w.get("input_data", ""))[:400],
                    transformations=str(w.get("transformations", ""))[:500], output=str(w.get("output", ""))[:400],
                    dependencies=[str(d)[:120] for d in w.get("dependencies", []) or []][:10],
                    errors=[str(e)[:200] for e in w.get("errors", []) or []][:10], sources=srcs,
                    classification=EvidenceClass.AI_INTERPRETED, verified=bool(srcs) and not phantom,
                ))
            for i, iss in enumerate((data2.get("potential_issues") or [])[:25]):
                if not isinstance(iss, dict) or not iss.get("title"):
                    continue
                refs = v.refs([{"file": iss.get("file"), "line_start": iss.get("line_start"), "line_end": iss.get("line_end")}]) if iss.get("file") else []
                if not refs:
                    continue  # AI issues without a verifiable location are discarded
                sev = str(iss.get("severity", "low")).lower()
                facts.findings.append(Finding(
                    id=hashlib.sha1(f"ai|{refs[0].file}|{refs[0].line_start}|{iss.get('title')}|{i}".encode(), usedforsecurity=False).hexdigest()[:10],
                    title=str(iss.get("title"))[:160], severity=sev if sev in {"critical", "high", "medium", "low", "info"} else "low",
                    category=re.sub(r"[^a-z0-9\-]+", "-", str(iss.get("category", "logic")).lower())[:40] or "logic",
                    file=refs[0].file, line_start=refs[0].line_start, line_end=refs[0].line_end,
                    explanation=str(iss.get("explanation", ""))[:800], evidence=redact_text(str(iss.get("evidence", ""))[:400])[0],
                    impact=str(iss.get("impact", ""))[:400], suggestion=str(iss.get("suggestion", ""))[:400],
                    confidence=min(0.6, float(iss.get("confidence", 0.4) or 0.4)), status="manual_verification", source="ai", group="issue",
                ))
        facts.ai.stages["E"] = "ok" if (e1_ok and data2 is not None) else ("failed" if not e1_ok and data2 is None else "partial")
        await self._emit("business_logic", 1, 1, "Business logic analysis complete")


def _parse_json(text: str | None) -> dict[str, Any] | None:
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        val = json.loads(t)
        return val if isinstance(val, dict) else {"items": val}
    except ValueError:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start >= 0 and end > start:
        try:
            val = json.loads(t[start : end + 1])
            return val if isinstance(val, dict) else None
        except ValueError:
            return None
    return None
