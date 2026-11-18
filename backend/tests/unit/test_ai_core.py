import asyncio
import contextlib
from pathlib import Path

import pytest

from app.schemas.facts import AIRunInfo, ProjectFacts
from app.services.ai.evidence import EvidenceValidator
from app.services.ai.orchestrator import AIOptions, AIOrchestrator, AnalysisCancelled, _parse_json
from app.services.ai.tokens import TokenBudget, estimate_tokens, truncate_lines
from tests.conftest import FakeProvider


def test_token_estimation_and_budget():
    assert estimate_tokens("") == 0
    assert estimate_tokens("x" * 35) == 10
    b = TokenBudget(total=100)
    assert b.can_afford(60, keep_for_later=40) and not b.can_afford(61, keep_for_later=40)
    b.spend(80)
    assert b.remaining == 20


def test_truncate_lines_numbering_and_marker():
    text = "\n".join(f"line {i}" for i in range(1, 101))
    out, included, total = truncate_lines(text, 200)
    assert out.startswith("  1| line 1") and total == 100 and included < 100
    assert f"lines {included + 1}-100 omitted" in out


def test_parse_json_variants():
    assert _parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _parse_json('Sure! {"a": {"b": 2}} done') == {"a": {"b": 2}}
    assert _parse_json("not json") is None


def test_evidence_validation():
    v = EvidenceValidator({"app/main.py": 50, "app/api/items.py": 30, "web/src/api.ts": 10})
    refs = v.refs([{"file": "app/main.py", "line_start": 5, "line_end": 9}, {"file": "items.py", "line_start": 3}, {"file": "ghost.py", "line_start": 1},
                   "web/src/api.ts:2-4", {"file": "app/main.py", "line_start": 999}])
    assert [(r.file, r.line_start) for r in refs] == [("app/main.py", 5), ("app/api/items.py", 3), ("web/src/api.ts", 2), ("app/main.py", None)]
    assert v.stats["refs_dropped"] == 1 and v.stats["refs_repaired"] == 1
    good = v.claim({"text": "Main wires routers.", "sources": [{"file": "app/main.py", "line_start": 1, "line_end": 3}], "confidence": 0.9}, "E")
    assert good is not None and good.verified and good.confidence == 0.9
    bad = v.claim({"text": "Logic lives in `app/services/ghost.py`.", "sources": [{"file": "app/main.py", "line_start": 1}]}, "E")
    assert bad is not None and not bad.verified and "not found in repository" in bad.text and bad.confidence <= 0.3
    nosrc = v.claim("A claim without evidence", "E")
    assert nosrc is not None and not nosrc.verified and nosrc.confidence <= 0.4


async def _facts_for(sample_zip, tmp_path: Path, name: str):  # type: ignore[no-untyped-def]
    """Run the deterministic pipeline up to the AI stage and return (facts, src_dir)."""
    from app.services.pipeline import runner as R

    captured = {}

    class Stop(Exception):
        pass

    orig = R.AIOrchestrator.run

    async def capture(self, facts, root):  # type: ignore[no-untyped-def]
        captured["facts"], captured["root"] = facts, root
        raise Stop()

    R.AIOrchestrator.run = capture  # type: ignore[method-assign]
    try:
        from app.core.config import get_settings

        s = get_settings()
        s.keep_extracted_sources = True
        job = R.AnalysisJob(project_id="t" * 32, name=name, description=None, archive=sample_zip(name), workdir=tmp_path / "w", depth="standard",
                            exclusions=[], token_budget=10_000, max_file_kb=512, max_concurrency=2, send_source=True, use_cache=False,
                            keep_archive=True, provider_config=None)
        (tmp_path / "w").mkdir(parents=True)

        async def emit(e):  # type: ignore[no-untyped-def]
            pass

        with contextlib.suppress(Exception):
            await R.PipelineRunner(s, emit).run(job)
    finally:
        R.AIOrchestrator.run = orig  # type: ignore[method-assign]
    return captured["facts"], captured["root"]


@pytest.mark.asyncio
async def test_orchestrator_full_run_with_fake_provider(sample_zip, tmp_path: Path):
    facts, root = await _facts_for(sample_zip, tmp_path, "python-fastapi-shop")
    provider = FakeProvider()
    events = []
    orch = AIOrchestrator(provider, provider.config, AIOptions(depth="standard", token_budget=500_000, max_concurrency=3, use_cache=False), None,
                          lambda *a: events.append(a))
    await orch.run(facts, root)
    ai = facts.ai
    assert ai.enabled and ai.stages == {"B": "ok", "C": "ok", "D": "ok", "E": "ok", "F": "ok"}
    assert facts.file_summaries and facts.module_summaries and facts.synthesis.purpose is not None
    assert facts.synthesis.workflows and facts.synthesis.workflows[0].verified
    # bogus references were dropped by stage F and counted
    assert ai.validation["refs_dropped"] >= 1
    assert all("does/not/exist.py" not in n for fs in facts.file_summaries for n in fs.notes)
    # AI issue with an unverifiable location is discarded; located one kept as manual_verification
    ai_issues = [f for f in facts.findings if f.source == "ai"]
    assert [f.title for f in ai_issues] == ["AI-suspected issue"] and ai_issues[0].status == "manual_verification"
    # every analysed file is accounted for in the manifest
    statuses = {m.path: m.status for m in facts.manifest}
    assert statuses["app/services/orders.py"] == "analysed"
    assert all(m.reason or m.status == "analysed" for m in facts.manifest)
    # secrets are redacted before leaving the process
    sent = "\n".join(provider.prompts)
    assert "a8F3kL9qZ2xV7mN4pR6tY1wE5uI0oPq" not in sent and "[REDACTED_SECRET]" in sent
    assert any(e[0] == "architecture" for e in events)


@pytest.mark.asyncio
async def test_budget_exhaustion_is_reported_not_silent(sample_zip, tmp_path: Path):
    facts, root = await _facts_for(sample_zip, tmp_path, "fullstack-notes")
    provider = FakeProvider()
    orch = AIOrchestrator(provider, provider.config, AIOptions(token_budget=6_000, use_cache=False), None)
    await orch.run(facts, root)
    assert any("token budget exhausted" in e for e in facts.ai.errors)
    not_done = [m for m in facts.manifest if m.status in ("failed", "deterministic_only")]
    assert not_done and all(m.reason for m in not_done)


@pytest.mark.asyncio
async def test_retry_then_success_and_permanent_failure(sample_zip, tmp_path: Path):
    facts, root = await _facts_for(sample_zip, tmp_path, "nextjs-ts-dashboard")
    flaky = FakeProvider(fail_times=2, retryable=True)
    await AIOrchestrator(flaky, flaky.config, AIOptions(use_cache=False), None).run(facts, root)
    assert facts.ai.failed_requests == 2 and facts.ai.stages["E"] == "ok"

    facts2, root2 = await _facts_for(sample_zip, tmp_path / "b", "nextjs-ts-dashboard")
    broken = FakeProvider(fail_times=10_000, retryable=False)
    await AIOrchestrator(broken, broken.config, AIOptions(use_cache=False), None).run(facts2, root2)
    assert facts2.ai.stages["B"] == "failed" and facts2.file_summaries == []
    assert any(m.status == "failed" for m in facts2.manifest)


@pytest.mark.asyncio
async def test_cancellation(sample_zip, tmp_path: Path):
    facts, root = await _facts_for(sample_zip, tmp_path, "python-fastapi-shop")
    cancel = asyncio.Event()
    cancel.set()
    p = FakeProvider()
    with pytest.raises(AnalysisCancelled):
        await AIOrchestrator(p, p.config, AIOptions(use_cache=False), None, cancel_event=cancel).run(facts, root)
    assert p.prompts == []


@pytest.mark.asyncio
async def test_structure_only_privacy_mode(sample_zip, tmp_path: Path):
    facts, root = await _facts_for(sample_zip, tmp_path, "python-fastapi-shop")
    p = FakeProvider()
    await AIOrchestrator(p, p.config, AIOptions(send_source=False, use_cache=False), None).run(facts, root)
    file_prompts = [x for x in p.prompts if "TASK: File-level" in x]
    assert file_prompts and all("source not sent (privacy setting" in x and "| def place_order" not in x for x in file_prompts)


@pytest.mark.asyncio
async def test_ai_response_cache(sample_zip, tmp_path: Path):
    facts, root = await _facts_for(sample_zip, tmp_path, "nextjs-ts-dashboard")
    cache = tmp_path / "aicache"
    cache.mkdir()
    p1 = FakeProvider()
    await AIOrchestrator(p1, p1.config, AIOptions(), cache).run(facts, root)
    facts2, _ = await _facts_for(sample_zip, tmp_path / "again", "nextjs-ts-dashboard")
    p2 = FakeProvider()
    await AIOrchestrator(p2, p2.config, AIOptions(), cache).run(facts2, root)
    assert facts2.ai.cached_responses > 0 and len(p2.prompts) < len(p1.prompts)


@pytest.mark.asyncio
async def test_no_provider_marks_everything_deterministic():
    from app.schemas.facts import FileRecord, RepositoryOverview

    facts = ProjectFacts(project_id="x", project_name="x", overview=RepositoryOverview(root_name="x"), files=[FileRecord(path="a.py", size=1)],
                         ai=AIRunInfo(provider="none"))
    await AIOrchestrator(None, None, AIOptions(), None).run(facts, Path("."))
    assert not facts.ai.enabled and facts.manifest[0].status == "deterministic_only" and facts.manifest[0].reason
    assert set(facts.ai.stages.values()) == {"skipped"}
