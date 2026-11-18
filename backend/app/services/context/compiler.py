"""Context compiler: renders the master knowledge document, modular documents and JSON artifacts."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.schemas.facts import ProjectFacts
from app.services.context import sections as S
from app.services.context.md import BADGE
from app.services.security.secrets import redact_text

MASTER = "CONTEXTFORGE_PROJECT_CONTEXT.md"

Renderer = Callable[[S.Ctx], str]

# The 32 master sections, in order.
MASTER_SECTIONS: list[tuple[str, Renderer]] = [
    ("Project Overview", S.overview),
    ("Project Purpose", S.purpose),
    ("Executive Technical Summary", S.executive_summary),
    ("Technology Stack", S.tech_stack),
    ("Repository Structure", S.structure),
    ("Architectural Overview", S.architecture),
    ("Module Descriptions", S.module_reference),
    ("File-Level Reference Index", S.file_reference),
    ("Important Functions and Classes", S.important_symbols),
    ("Application Entry Points", S.entry_points),
    ("API Documentation", S.api_reference),
    ("Database Architecture", S.database_schema),
    ("Database Relationships", S.database_relationships),
    ("Data Flow", S.data_flow),
    ("Authentication and Authorization", S.authentication),
    ("External Integrations", S.integration_map),
    ("Business Logic", S.business_logic),
    ("Core Application Workflows", S.workflows),
    ("Environment Configuration", S.configuration),
    ("Build and Execution Instructions", S.build_and_run),
    ("Testing Architecture", S.testing),
    ("Security Observations", S.security_review),
    ("Reliability Observations", S.reliability_review),
    ("Dependency Information", S.dependencies),
    ("Potential Bugs and Suspicious Code Patterns", S.potential_issues),
    ("Technical Debt", S.technical_debt),
    ("Known Limitations", S.limitations),
    ("Missing Information", S.missing_information),
    ("Important Architectural Decisions", S.decisions),
    ("Suggested Debugging Entry Points", S.debugging_entry_points),
    ("Comprehensive File Index", S.file_index),
    ("Open Questions Requiring Developer Investigation", S.open_questions),
]

# Modular numbered documents: (filename, title, [(subheading|None, renderer)])
MODULAR_DOCS: list[tuple[str, str, list[tuple[str | None, Renderer]]]] = [
    ("00_PROJECT_OVERVIEW.md", "Project Overview", [("Overview", S.overview), ("Purpose", S.purpose), ("Executive Summary", S.executive_summary)]),
    ("01_PROJECT_STRUCTURE.md", "Project Structure", [(None, S.structure)]),
    ("02_TECH_STACK.md", "Technology Stack", [(None, S.tech_stack)]),
    ("03_ARCHITECTURE.md", "Architecture", [(None, S.architecture), ("Important Architectural Decisions", S.decisions)]),
    ("04_SYSTEM_DESIGN.md", "System Design", [(None, S.system_design)]),
    ("05_MODULE_REFERENCE.md", "Module Reference", [(None, S.module_reference), ("File-Level Reference", S.file_reference)]),
    ("06_CODEBASE_MAP.md", "Codebase Map", [(None, S.codebase_map), ("Important Functions and Classes", S.important_symbols)]),
    ("07_API_REFERENCE.md", "API Reference", [(None, S.api_reference), ("Client Calls", S.client_calls)]),
    ("08_DATABASE_SCHEMA.md", "Database Schema", [(None, S.database_schema), ("Relationships", S.database_relationships), ("Database Operations", S.database_operations)]),
    ("09_DATA_FLOW.md", "Data Flow", [(None, S.data_flow), ("Integrations", S.integration_map)]),
    ("10_BUSINESS_LOGIC.md", "Business Logic", [(None, S.business_logic), ("Core Functionality", S.core_functionality), ("Application Workflows", S.workflows)]),
    ("11_DEPENDENCIES.md", "Dependencies", [(None, S.dependencies)]),
    ("12_CONFIGURATION.md", "Configuration", [(None, S.configuration)]),
    ("13_SECURITY_REVIEW.md", "Security Review", [("Authentication and Authorization", S.authentication), ("Findings", S.security_review)]),
    ("14_RELIABILITY_REVIEW.md", "Reliability Review", [(None, S.reliability_review)]),
    ("15_POTENTIAL_ISSUES.md", "Potential Issues", [(None, S.potential_issues), ("Bug Analysis", S.bug_analysis)]),
    ("16_TESTING_AND_BUILD.md", "Testing and Build", [("Testing", S.testing), ("Build and Execution", S.build_and_run)]),
    ("17_DEVELOPMENT_GUIDE.md", "Development Guide", [("Entry Points", S.entry_points), ("Build and Execution", S.build_and_run), ("Debugging Entry Points", S.debugging_entry_points), ("Technical Debt", S.technical_debt), ("Known Limitations", S.limitations)]),
    ("18_OPEN_QUESTIONS.md", "Open Questions", [(None, S.open_questions), ("Missing Information", S.missing_information)]),
    ("19_FILE_INDEX.md", "File Index", [(None, S.file_index)]),
]

# Layer documents (per analysis layer), stored under layers/
LAYER_DOCS: list[tuple[str, str, list[tuple[str | None, Renderer]]]] = [
    ("PROJECT_STRUCTURE.md", "Project Structure (Layer 0)", [(None, S.structure)]),
    ("TECH_STACK.md", "Technology Stack (Layer 1)", [(None, S.tech_stack)]),
    ("DEPENDENCIES.md", "Dependencies (Layer 1)", [(None, S.dependencies)]),
    ("CONFIGURATION.md", "Configuration (Layer 1)", [(None, S.configuration)]),
    ("CODEBASE_MAP.md", "Codebase Map (Layer 2)", [(None, S.codebase_map)]),
    ("MODULE_REFERENCE.md", "Module Reference (Layer 2)", [(None, S.module_reference)]),
    ("FUNCTION_REFERENCE.md", "Function Reference (Layer 2)", [(None, S.function_reference)]),
    ("ARCHITECTURE.md", "Architecture (Layer 3)", [(None, S.architecture)]),
    ("SYSTEM_DESIGN.md", "System Design (Layer 3)", [(None, S.system_design)]),
    ("COMPONENT_RELATIONSHIPS.md", "Component Relationships (Layer 3)", [(None, S.codebase_map), ("Module interactions", S.system_design)]),
    ("API_REFERENCE.md", "API Reference (Layer 4)", [(None, S.api_reference)]),
    ("DATA_FLOW.md", "Data Flow (Layer 4)", [(None, S.data_flow)]),
    ("INTEGRATION_MAP.md", "Integration Map (Layer 4)", [(None, S.integration_map)]),
    ("DATABASE_SCHEMA.md", "Database Schema (Layer 5)", [(None, S.database_schema)]),
    ("DATABASE_RELATIONSHIPS.md", "Database Relationships (Layer 5)", [(None, S.database_relationships)]),
    ("DATABASE_OPERATIONS.md", "Database Operations (Layer 5)", [(None, S.database_operations)]),
    ("BUSINESS_LOGIC.md", "Business Logic (Layer 6)", [(None, S.business_logic)]),
    ("APPLICATION_WORKFLOWS.md", "Application Workflows (Layer 6)", [(None, S.workflows)]),
    ("CORE_FUNCTIONALITY.md", "Core Functionality (Layer 6)", [(None, S.core_functionality)]),
    ("SECURITY_REVIEW.md", "Security Review (Layer 7)", [(None, S.security_review)]),
    ("RELIABILITY_REVIEW.md", "Reliability Review (Layer 7)", [(None, S.reliability_review)]),
    ("POTENTIAL_ISSUES.md", "Potential Issues", [(None, S.potential_issues)]),
    ("BUG_ANALYSIS.md", "Bug Analysis", [(None, S.bug_analysis)]),
]


@dataclass
class GeneratedDoc:
    path: str  # relative to output dir
    title: str
    group: str  # master | modular | layer | data
    size: int


def _header(f: ProjectFacts, title: str) -> str:
    model = f"{f.ai.provider}/{f.ai.model}" if f.ai.enabled else "none (deterministic only)"
    return (
        f"# {title}\n\n"
        f"> **Project:** {f.project_name} · **Generated:** {f.generated_at} · **Fingerprint:** `{f.fingerprint[:16]}` · "
        f"**ContextForge analysis version:** {f.analysis_version} · **AI provider/model:** {model} · **Depth:** {f.depth}\n>\n"
        f"> Evidence labels: {BADGE[S.EvidenceClass.DETECTED]} extracted directly from source · {BADGE[S.EvidenceClass.INFERRED]} derived from code relationships or conventions · "
        f"{BADGE[S.EvidenceClass.AI_INTERPRETED]} explanation generated by a model (with validated source references) · {BADGE[S.EvidenceClass.UNKNOWN]} insufficient evidence.\n"
        f"> Source references use `path:line` or `path:start-end` relative to the repository root.\n\n"
    )


def _shift_headings(md: str, levels: int) -> str:
    if levels <= 0:
        return md
    out = []
    in_code = False
    for line in md.split("\n"):
        if line.startswith("```"):
            in_code = not in_code
        if not in_code and re.match(r"^#{1,5} ", line):
            line = "#" * levels + line
        out.append(line)
    return "\n".join(out)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9\- ]", "", s.lower()).strip().replace(" ", "-")


def _safe(renderer: Renderer, ctx: S.Ctx) -> str:
    try:
        return renderer(ctx)
    except Exception as exc:  # never lose the whole document because one section failed
        return f"{BADGE[S.EvidenceClass.UNKNOWN]} This section could not be rendered: `{type(exc).__name__}: {exc}`"


def render_master(f: ProjectFacts, ctx: S.Ctx) -> str:
    parts = [_header(f, f"{f.project_name} — Project Context"),
             "This document is a self-contained knowledge base about the repository, generated by ContextForge for use by humans and LLMs. "
             "It is structured technical knowledge (not a code dump): every important claim points to the source file and line it came from.\n",
             "## Contents\n"]
    for i, (title, _r) in enumerate(MASTER_SECTIONS, 1):
        parts.append(f"{i}. [{title}](#{i}-{_slug(title)})")
    parts.append("")
    for i, (title, r) in enumerate(MASTER_SECTIONS, 1):
        body = _shift_headings(_safe(r, ctx), 1)  # section bodies use ###; shift so they nest under ##
        parts.append(f"## {i}. {title}\n\n{body}\n")
    return "\n".join(parts)


def render_doc(f: ProjectFacts, ctx: S.Ctx, title: str, parts: list[tuple[str | None, Renderer]]) -> str:
    out = [_header(f, title)]
    for sub, r in parts:
        body = _safe(r, ctx)
        if sub:
            out.append(f"## {sub}\n\n{_shift_headings(body, 1)}\n")
        else:
            out.append(body + "\n")
    return "\n".join(out)


def compile_context(f: ProjectFacts, out_dir: Path) -> list[GeneratedDoc]:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "layers").mkdir(exist_ok=True)
    (out_dir / "data").mkdir(exist_ok=True)
    ctx = S.Ctx(f)
    docs: list[GeneratedDoc] = []

    def write(rel: str, content: str, title: str, group: str) -> None:
        content, _n = redact_text(content)  # safety net: credentials never reach generated files
        p = out_dir / rel
        p.write_text(content, encoding="utf-8")
        docs.append(GeneratedDoc(path=rel, title=title, group=group, size=len(content.encode())))

    write(MASTER, render_master(f, ctx), "Master Project Context", "master")
    for fname, title, parts in MODULAR_DOCS:
        write(fname, render_doc(f, ctx, title, parts), title, "modular")
    for fname, title, parts in LAYER_DOCS:
        write(f"layers/{fname}", render_doc(f, ctx, title, parts), title, "layer")

    write_json = lambda rel, obj, title: write(rel, json.dumps(obj, indent=2, ensure_ascii=False, default=str), title, "data")  # noqa: E731
    write_json("data/PROJECT_METADATA.json", project_metadata(f), "Project Metadata")
    write_json("data/ANALYSIS_MANIFEST.json", {"project_id": f.project_id, "fingerprint": f.fingerprint, "generated_at": f.generated_at,
                                                "summary": _manifest_summary(f), "files": [m.model_dump(mode="json") for m in f.manifest]}, "Analysis Manifest")
    write_json("data/DEPENDENCY_GRAPH.json", f.graph.model_dump(mode="json"), "Dependency Graph")
    write_json("data/repository_overview.json", f.overview.model_dump(mode="json"), "Repository Overview")
    write_json("data/file_inventory.json", [x.model_dump(mode="json") for x in f.files], "File Inventory")
    write_json("data/PROJECT_FACTS.json", f.model_dump(mode="json"), "All Extracted Facts")
    write("README.md", _package_readme(f), "How to use this context package", "data")
    return docs


def _manifest_summary(f: ProjectFacts) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in f.manifest:
        out[m.status] = out.get(m.status, 0) + 1
    return out


def project_metadata(f: ProjectFacts) -> dict[str, object]:
    return {
        "project_id": f.project_id, "project_name": f.project_name, "description": f.description, "fingerprint": f.fingerprint,
        "generated_at": f.generated_at, "analysis_version": f.analysis_version, "depth": f.depth,
        "ai": f.ai.model_dump(mode="json"),
        "counts": {"files": f.overview.total_files, "included": f.overview.included_files, "source_files": f.overview.source_files,
                   "code_lines": f.overview.code_lines, "routes": len(f.routes), "db_models": len(f.db_models), "dependencies": len(f.dependencies),
                   "technologies": len(f.technologies), "findings": len(f.findings), "secrets": len(f.secrets), "modules": len(f.modules)},
        "languages": f.overview.languages,
        "output_validation": f.output_validation,
        "warnings": f.warnings,
    }


def _package_readme(f: ProjectFacts) -> str:
    return f"""# ContextForge context package — {f.project_name}

Generated {f.generated_at} (fingerprint `{f.fingerprint[:16]}`, analysis version {f.analysis_version}).

## How to use

- Give **`{MASTER}`** to any LLM (paste or attach) before asking it to debug, review, extend or refactor this project. It is self-contained.
- For focused questions, attach only the relevant numbered document (e.g. `07_API_REFERENCE.md` for API work, `08_DATABASE_SCHEMA.md` for data work).
- `layers/` holds one document per analysis layer; `data/` holds machine-readable JSON (full facts, dependency graph, manifest).

## Trust model

Statements are labelled `DETECTED` (extracted from code), `INFERRED` (derived from relationships/conventions), `AI_INTERPRETED`
(model explanation, with source references validated against the repository) or `UNKNOWN`. Verify `AI_INTERPRETED` and
`manual_verification` items against the code before acting on them. Secrets were redacted and never sent to an AI provider.
"""


_REF = re.compile(r"`([^`\s]+\.[A-Za-z0-9]{1,8}):(\d+)(?:-(\d+))?`")


def validate_outputs(f: ProjectFacts, out_dir: Path, docs: list[GeneratedDoc]) -> dict[str, object]:
    """Completeness and reference-integrity checks on the generated package."""
    expected = [MASTER] + [d[0] for d in MODULAR_DOCS] + [f"layers/{d[0]}" for d in LAYER_DOCS] + \
        ["data/PROJECT_METADATA.json", "data/ANALYSIS_MANIFEST.json", "data/DEPENDENCY_GRAPH.json"]
    present = {d.path for d in docs}
    missing = [e for e in expected if e not in present or (out_dir / e).stat().st_size == 0]
    master = (out_dir / MASTER).read_text(encoding="utf-8")
    missing_sections = [t for i, (t, _r) in enumerate(MASTER_SECTIONS, 1) if f"## {i}. {t}" not in master]
    lines = {x.path: x.lines for x in f.files}
    bad_refs: list[str] = []
    total_refs = 0
    for d in docs:
        if not d.path.endswith(".md"):
            continue
        text = (out_dir / d.path).read_text(encoding="utf-8")
        for m in _REF.finditer(text):
            total_refs += 1
            p, ls = m.group(1), int(m.group(2))
            if (p not in lines or ls > max(lines[p], 1)) and len(bad_refs) < 50:
                bad_refs.append(f"{d.path}: {m.group(0)}")
    unrendered = [d.path for d in docs if d.path.endswith(".md") and "could not be rendered" in (out_dir / d.path).read_text(encoding="utf-8")]
    result = {
        "documents_expected": len(expected), "documents_missing": missing, "master_sections": len(MASTER_SECTIONS),
        "master_sections_missing": missing_sections, "source_references_checked": total_refs, "invalid_source_references": bad_refs,
        "sections_failed_to_render": unrendered,
        "ok": not missing and not missing_sections and not bad_refs and not unrendered,
    }
    f.output_validation = result
    # refresh metadata and facts with the validation result
    (out_dir / "data/PROJECT_METADATA.json").write_text(redact_text(json.dumps(project_metadata(f), indent=2, default=str))[0], encoding="utf-8")
    (out_dir / "data/PROJECT_FACTS.json").write_text(redact_text(json.dumps(f.model_dump(mode="json"), indent=2, ensure_ascii=False, default=str))[0], encoding="utf-8")
    return result
