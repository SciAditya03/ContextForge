import json
from pathlib import Path

from app.schemas.facts import (
    AIRunInfo,
    Claim,
    DbField,
    DbModel,
    EvidenceClass,
    FileRecord,
    Finding,
    ProjectFacts,
    RepositoryOverview,
    Route,
    SourceRef,
    SystemSynthesis,
)
from app.services.context.compiler import (
    LAYER_DOCS,
    MASTER,
    MASTER_SECTIONS,
    MODULAR_DOCS,
    compile_context,
    validate_outputs,
)
from app.services.export.packager import build_zip


def _facts() -> ProjectFacts:
    files = [FileRecord(path="app/main.py", size=100, language="Python", lines=40, code_lines=30), FileRecord(path="node_modules/x.js", size=1, status="excluded", status_reason="excluded by pattern 'node_modules/'")]
    return ProjectFacts(
        project_id="p", project_name="Demo", fingerprint="f" * 64, generated_at="2026-01-01T00:00:00+00:00", analysis_version="1.0.0",
        overview=RepositoryOverview(root_name="demo", total_files=2, included_files=1, languages={"Python": {"files": 1, "lines": 40, "code_lines": 30, "bytes": 100}}),
        files=files,
        routes=[Route(method="GET", path="/items", handler="list_items", file="app/main.py", line=10, framework="FastAPI")],
        db_models=[DbModel(name="Item", table="items", orm="SQLAlchemy", file="app/main.py", line=5, fields=[DbField(name="id", type="Integer", primary_key=True, line=6)])],
        findings=[Finding(id="1", title="Hardcoded thing", severity="high", category="hardcoded-secret", file="app/main.py", line_start=3,
                          explanation="password = \"Zx81kQp0vLmN3rT9aa\" found", group="security")],
        synthesis=SystemSynthesis(purpose=Claim(text="Serves items.", sources=[SourceRef(file="app/main.py", line_start=1, line_end=4)], classification=EvidenceClass.AI_INTERPRETED, confidence=0.8)),
        ai=AIRunInfo(provider="anthropic", model="claude-opus-5-5", enabled=True, stages={"B": "ok"}),
    )


def test_compile_all_documents_and_validate(tmp_path: Path):
    f = _facts()
    docs = compile_context(f, tmp_path)
    paths = {d.path for d in docs}
    assert MASTER in paths and all(d[0] in paths for d in MODULAR_DOCS) and all(f"layers/{d[0]}" in paths for d in LAYER_DOCS)
    master = (tmp_path / MASTER).read_text()
    assert master.startswith("# Demo — Project Context")
    assert "**Fingerprint:** `ffffffffffffffff`" in master and "anthropic/claude-opus-5-5" in master
    for i, (title, _r) in enumerate(MASTER_SECTIONS, 1):
        assert f"## {i}. {title}" in master
    assert "`AI_INTERPRETED` Serves items. — sources: `app/main.py:1-4`" in master
    assert "erDiagram" in master and "Item" in master
    assert "Zx81kQp0vLmN3rT9aa" not in master  # redaction safety net on all generated text
    val = validate_outputs(f, tmp_path, docs)
    assert val["ok"], val
    meta = json.loads((tmp_path / "data/PROJECT_METADATA.json").read_text())
    assert meta["output_validation"]["ok"] and meta["counts"]["routes"] == 1
    manifest = json.loads((tmp_path / "data/ANALYSIS_MANIFEST.json").read_text())
    assert manifest["fingerprint"] == f.fingerprint
    z = build_zip(tmp_path, tmp_path.parent / "pkg.zip", "Demo")
    assert z.exists() and z.stat().st_size > 1000


def test_not_applicable_sections_explain_why(tmp_path: Path):
    f = _facts()
    f.routes, f.db_models, f.ai = [], [], AIRunInfo(provider="none")
    f.synthesis = SystemSynthesis()
    compile_context(f, tmp_path)
    master = (tmp_path / MASTER).read_text()
    assert "No HTTP/GraphQL/WebSocket route definitions were detected" in master
    assert "No ORM models, Prisma models or SQL `CREATE TABLE` statements were found" in master
    assert "requires AI interpretation, which was not run" in master


def test_validation_flags_bad_references(tmp_path: Path):
    f = _facts()
    docs = compile_context(f, tmp_path)
    (tmp_path / "03_ARCHITECTURE.md").write_text("see `app/ghost.py:10` and `app/main.py:999`")
    val = validate_outputs(f, tmp_path, docs)
    assert not val["ok"] and len(val["invalid_source_references"]) == 2
