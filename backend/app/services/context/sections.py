"""Section renderers. Each returns Markdown built only from ProjectFacts.

Deterministic data is labelled DETECTED/INFERRED, model output AI_INTERPRETED,
and gaps UNKNOWN. When a section does not apply, it says why.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import PurePosixPath

from app.schemas.facts import EvidenceClass, FileCategory, Finding, ProjectFacts
from app.services.architecture.graph import module_of
from app.services.architecture.traces import CallResolver, count_callers, render_trace
from app.services.context.md import BADGE, bullet, claims_block, esc, loc, table, tree_text

D, I, A, U = (  # noqa: E741 - short evidence badge names
    BADGE[EvidenceClass.DETECTED], BADGE[EvidenceClass.INFERRED], BADGE[EvidenceClass.AI_INTERPRETED], BADGE[EvidenceClass.UNKNOWN])
SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _entry_reason(f: ProjectFacts, path: str) -> str:
    rec = f.file(path)
    return (rec.entry_point_reason or "") if rec else ""


class Ctx:
    """Pre-computed indexes shared by section renderers."""

    def __init__(self, f: ProjectFacts) -> None:
        self.f = f
        self.included = [x for x in f.files if x.status == "included"]
        self.files_by_dir: dict[str, list[str]] = defaultdict(list)
        for x in f.files:
            if x.status == "excluded":
                continue
            parent = str(PurePosixPath(x.path).parent)
            self.files_by_dir["" if parent == "." else parent].append(PurePosixPath(x.path).name)
        self.mod_by_path = {m.path: m for m in f.modules}
        self.summary_by_path = {s.path: s for s in f.file_summaries}
        self.manifest_by_path = {m.path: m for m in f.manifest}
        self.resolver = CallResolver(f.modules, f.db_operations)
        self.callers = count_callers(f.modules)
        self.ai_on = f.ai.enabled
        self.heuristic_langs = sorted({m.language for m in f.modules if m.parser.startswith("heuristic")})

    def ai_missing(self, what: str) -> str:
        if not self.ai_on:
            return f"{U} {what} requires AI interpretation, which was not run for this analysis (provider: `none`). Deterministic facts above remain valid."
        return f"{U} The AI stage did not return {what} (see Known Limitations / AI errors)."


# ----------------------------------------------------------------------------- 1-3
def overview(c: Ctx) -> str:
    f = c.f
    o = f.overview
    langs = table(["Language", "Files", "Code lines", "Total lines"],
                  [(k, v["files"], v["code_lines"], v["lines"]) for k, v in list(o.languages.items())[:20]])
    parts = [
        f"{D} **{f.project_name}** — {o.included_files} analysable files out of {o.total_files} in the archive "
        f"({o.excluded_files} excluded), {o.source_files} source files, {o.test_files} test files, ~{o.code_lines:,} lines of code.",
    ]
    if f.description:
        parts.append(f"_Description provided at upload:_ {f.description}")
    parts += ["", "**Languages**", "", langs, ""]
    if o.subprojects and o.subprojects != ["."]:
        parts += [f"{D} **Sub-projects** (directories with their own dependency manifest): " + ", ".join(f"`{s}`" for s in o.subprojects), ""]
    parts += ["**Entry points**", "", bullet([f"{loc(p)} — {_entry_reason(f, p)}" for p in o.entry_points], "_No entry points detected._")]
    return "\n".join(parts)


def purpose(c: Ctx) -> str:
    f = c.f
    out = []
    if f.synthesis.purpose:
        out.append(claims_block([f.synthesis.purpose], ""))
    if f.readme_excerpt:
        out.append(f"{D} README excerpt:\n\n> " + f.readme_excerpt.replace("\n", "\n> "))
    if f.description:
        out.append(f"{D} Upload description: {f.description}")
    if not out:
        out.append(f"{U} No README, description or AI interpretation is available to state the project's purpose. Infer it from the API and module sections below.")
    return "\n\n".join(out)


def executive_summary(c: Ctx) -> str:
    f = c.f
    sev = Counter(x.severity for x in f.findings)
    frameworks = [t.name for t in f.technologies if t.category == "framework"]
    dbs = sorted({t.name for t in f.technologies if t.category == "database"})
    det = [
        f"{D} Primary languages: {', '.join(list(f.overview.languages)[:4]) or 'unknown'}.",
        f"{D} Frameworks: {', '.join(frameworks[:8]) or 'none detected'}.",
        f"{D} Databases: {', '.join(dbs) or 'none detected'}; {len(f.db_models)} data models/tables extracted.",
        f"{D} {len(f.routes)} API endpoints/handlers extracted across {len({r.file for r in f.routes})} files; {len(f.client_calls)} client-side HTTP calls.",
        f"{D} Internal import graph: {len([e for e in f.graph.edges if e.type == 'imports'])} file-to-file edges, {len(f.graph.cycles)} import cycles.",
        f"{D} Findings: " + ", ".join(f"{sev.get(s, 0)} {s}" for s in ("critical", "high", "medium", "low", "info")) + ".",
    ]
    ai = claims_block(f.synthesis.executive_summary, c.ai_missing("an executive summary"))
    return "**Deterministic facts**\n\n" + "\n".join(f"- {x}" for x in det) + "\n\n**Interpretation**\n\n" + ai


# ----------------------------------------------------------------------------- 4-5
def tech_stack(c: Ctx) -> str:
    f = c.f
    by_cat: dict[str, list] = defaultdict(list)
    for t in f.technologies:
        by_cat[t.category].append(t)
    out = [f"Legend: {D} = found in a manifest/config/source file, {I} = implied by conventions or other evidence.", ""]
    for cat, items in by_cat.items():
        out.append(f"### {cat.replace('_', ' ').title()}")
        out.append("")
        out.append(table(["Technology", "Version", "Evidence class", "Evidence", "Note"],
                         [(t.name, t.version or "", t.classification.value, ", ".join(e.label() for e in t.evidence[:3]), t.note or "") for t in items]))
        out.append("")
    if not f.technologies:
        out.append(f"{U} No technologies could be detected.")
    return "\n".join(out)


def structure(c: Ctx) -> str:
    f = c.f
    out = [tree_text(f.tree, c.files_by_dir, max_depth=5, max_entries=500) if f.tree else "_No tree._", "", "**Directory summary**", ""]
    rows = []
    dir_files: dict[str, list[str]] = defaultdict(list)
    for x in c.included:
        dir_files[module_of(x.path)].append(x.path)
    for d, paths in sorted(dir_files.items()):
        roles = Counter(r for p in paths for r in (c.mod_by_path[p].roles if p in c.mod_by_path else []))
        cats = Counter(next((x.category.value for x in c.included if x.path == p), "") for p in paths)
        rows.append((d, len(paths), ", ".join(f"{k}×{v}" for k, v in cats.most_common(3)), ", ".join(k for k, _ in roles.most_common(4))))
    out.append(table(["Directory", "Files", "Categories", "Detected roles"], rows[:300]))
    cat_rows: list[tuple[str, int]] = sorted(f.overview.categories.items(), key=lambda kv: kv[1], reverse=True)
    out += ["", "**File categories**", "", table(["Category", "Files"], cat_rows)]
    return "\n".join(out)


# ----------------------------------------------------------------------------- 6-9
def architecture(c: Ctx) -> str:
    f = c.f
    out = ["### Detected layers", "", table(["Layer", "Evidence class", "Files", "Examples / evidence"],
           [(x.layer, x.classification.value, len(x.files), "; ".join(x.evidence[:3]) or ", ".join(x.files[:3])) for x in f.components]), ""]
    out += ["### Interpretation", "", claims_block(f.synthesis.architecture, c.ai_missing("an architecture narrative")), ""]
    edges = sorted(f.graph.module_edges, key=lambda e: -e.weight)[:40]
    out += ["### Module dependency graph (strongest edges)", "", f"{D} Edges are aggregated `import` statements between directories.", ""]
    out.append(table(["From module", "To module", "Imports"], [(e.source, e.target, e.weight) for e in edges]))
    if edges:
        out += ["", "```mermaid", "graph LR"]
        ids: dict[str, str] = {}

        def nid(x: str) -> str:
            if x not in ids:
                ids[x] = f"m{len(ids)}"
            return ids[x]

        for e in edges[:30]:
            out.append(f'  {nid(e.source)}["{e.source}"] --> {nid(e.target)}["{e.target}"]')
        out.append("```")
    out += ["", "### Import cycles", "", bullet([" ⇄ ".join(f"`{p}`" for p in cyc) for cyc in f.graph.cycles[:20]], f"{D} No import cycles detected.")]
    return "\n".join(out)


def system_design(c: Ctx) -> str:
    f = c.f
    out = ["### Runtime topology", ""]
    compose = [cf for cf in f.config_files if cf.kind == "docker-compose"]
    if compose:
        for cf in compose:
            out.append(f"{D} Services defined in {loc(cf.path)}:")
            out.append("")
            svcs = cf.summary.get("services", {})
            out.append(table(["Service", "Image", "Build", "Ports", "Depends on"],
                             [(k, v.get("image"), v.get("build"), v.get("ports"), v.get("depends_on")) for k, v in svcs.items()]))
            out.append("")
    else:
        out.append(f"{U} No docker-compose/orchestration file found; runtime topology is inferred from entry points only.")
        out.append("")
    out += ["### Entry points", "", entry_points(c), "", "### Cross-cutting concerns", ""]
    comps = {x.layer: x for x in f.components}
    for layer in ("auth", "middleware", "cache", "worker", "logging", "storage", "state", "config"):
        x = comps.get(layer)
        if x:
            out.append(f"- **{layer}** {BADGE[x.classification]}: " + ("; ".join(x.evidence[:3]) or ", ".join(f"`{p}`" for p in x.files[:4])))
        else:
            out.append(f"- **{layer}** {U}: not detected")
    out += ["", "### Module interactions", "", claims_block(f.synthesis.module_interactions, c.ai_missing("module interaction analysis"))]
    return "\n".join(out)


def module_reference(c: Ctx) -> str:
    f = c.f
    groups: dict[str, list[str]] = defaultdict(list)
    for m in f.modules:
        groups[module_of(m.path)].append(m.path)
    ms_by = {m.module: m for m in f.module_summaries}
    out_edges: dict[str, list[str]] = defaultdict(list)
    in_edges: dict[str, list[str]] = defaultdict(list)
    for e in f.graph.module_edges:
        out_edges[e.source].append(e.target)
        in_edges[e.target].append(e.source)
    out = []
    for mod, paths in sorted(groups.items()):
        roles = Counter(r for p in paths for r in c.mod_by_path[p].roles)
        out.append(f"### `{mod}`")
        out.append("")
        out.append(f"{D} {len(paths)} parsed files; roles: {', '.join(k for k, _ in roles.most_common(6)) or 'none'}.")
        if out_edges.get(mod):
            out.append(f"{D} Imports from: " + ", ".join(f"`{x}`" for x in sorted(out_edges[mod])[:12]))
        if in_edges.get(mod):
            out.append(f"{D} Imported by: " + ", ".join(f"`{x}`" for x in sorted(in_edges[mod])[:12]))
        s = ms_by.get(mod)
        if s:
            out.append(f"{A} **Purpose:** {s.purpose}")
            if s.responsibilities:
                out.append("Responsibilities:\n" + bullet(s.responsibilities))
            if s.interactions:
                out.append("Interactions:\n" + bullet(s.interactions))
        out.append("")
        out.append(table(["File", "Language", "Roles", "Symbols", "Summary"],
                         [(p, c.mod_by_path[p].language, ", ".join(c.mod_by_path[p].roles), len(c.mod_by_path[p].symbols),
                           (c.summary_by_path[p].purpose if p in c.summary_by_path else "")) for p in sorted(paths)]))
        out.append("")
    return "\n".join(out) or "_No parseable source modules._"


def file_reference(c: Ctx) -> str:
    out = []
    for m in sorted(c.f.modules, key=lambda m: m.path):
        rec = c.f.file(m.path)
        if rec is None or rec.category not in (FileCategory.SOURCE, FileCategory.SCHEMA, FileCategory.CONFIG, FileCategory.BUILD):
            continue
        s = c.summary_by_path.get(m.path)
        top = [x for x in m.symbols if x.parent is None and x.kind not in ("variable",)][:12]
        out.append(f"#### `{m.path}`")
        line = f"{D} {m.language}, {rec.lines} lines, parser `{m.parser}`" + (f", roles: {', '.join(m.roles)}" if m.roles else "")
        if not m.parse_ok or m.parse_error:
            line += f" — ⚠ {m.parse_error}"
        out.append(line)
        if m.docstring:
            out.append(f"{D} Module docstring: {esc(m.docstring)[:300]}")
        if s:
            out.append(f"{A} {s.purpose}")
            for n in s.notes[:5]:
                out.append(f"  - {n}")
        if top:
            out.append("Symbols: " + ", ".join(f"`{x.name}` ({x.kind}, L{x.line_start})" for x in top))
        out.append("")
    return "\n".join(out) or "_No source files._"


def important_symbols(c: Ctx) -> str:
    f = c.f
    handlers = {(r.file, (r.handler or "").split(".")[-1]) for r in f.routes}
    models = {(d.file, d.name) for d in f.db_models}
    scored = []
    for m in f.modules:
        rec = f.file(m.path)
        if rec is not None and rec.category == FileCategory.TEST:
            continue
        for s in m.symbols:
            if s.kind not in ("function", "method", "class", "component", "hook", "interface"):
                continue
            score: float = c.callers.get(s.name, 0) * 2
            tags = []
            if (s.file, s.name) in handlers:
                score += 25
                tags.append("route handler")
            if (s.file, s.name) in models:
                score += 20
                tags.append("data model")
            if s.exported:
                score += 2
            if s.kind == "class":
                score += 4
            size = s.line_end - s.line_start
            score += min(10, size / 20)
            if score >= 6:
                scored.append((score, s, tags))
    scored.sort(key=lambda t: -t[0])
    rows = [(f"{s.parent + '.' if s.parent else ''}{s.name}", s.kind, f"{s.file}:{s.line_start}-{s.line_end}", ", ".join(tags),
             c.callers.get(s.name, 0), (s.signature or "")[:120]) for _sc, s, tags in scored[:120]]
    return f"{D} Ranked by static references (call sites by name), role (route handler / data model), visibility and size.\n\n" + \
        table(["Symbol", "Kind", "Location", "Role", "Call sites", "Signature"], rows)


def function_reference(c: Ctx) -> str:
    out = [f"{D} Every function/method/class extracted by the parsers, grouped by file. Heuristic parsers are marked; their line ranges are approximate.", ""]
    for m in sorted(c.f.modules, key=lambda m: m.path):
        syms = [s for s in m.symbols if s.kind in ("function", "method", "class", "component", "hook", "interface", "type", "enum")]
        if not syms:
            continue
        out.append(f"### `{m.path}`" + (" _(heuristic parser)_" if m.parser.startswith("heuristic") else ""))
        out.append("")
        out.append(table(["Symbol", "Kind", "Lines", "Signature", "Decorators", "Raises", "Calls (first 6)"],
                         [(f"{s.parent + '.' if s.parent else ''}{s.name}", s.kind + (" async" if s.is_async else ""), f"{s.line_start}-{s.line_end}",
                           (s.signature or "")[:140], ", ".join(s.decorators[:3]), ", ".join(s.raises[:3]), ", ".join(s.calls[:6])) for s in syms[:150]]))
        out.append("")
    return "\n".join(out)


def codebase_map(c: Ctx) -> str:
    f = c.f
    out = [f"{D} Map of parsed source modules with their imports and exports. External packages are listed separately.", ""]
    rows = []
    for m in sorted(f.modules, key=lambda m: m.path):
        internal = sorted({p for i in m.imports for p in ([i.resolved] if i.resolved else []) + i.also_resolved})
        ext = sorted({i.package for i in m.imports if i.package})
        rows.append((m.path, m.language, ", ".join(m.roles), len(m.symbols), ", ".join(internal[:6]) + (" …" if len(internal) > 6 else ""),
                     ", ".join(ext[:6]), ", ".join(m.exports[:6])))
    out.append(table(["File", "Lang", "Roles", "Symbols", "Imports (internal)", "Imports (external)", "Exports"], rows))
    ext_nodes = [n for n in f.graph.nodes if n.type == "external"]
    out += ["", "**Most used external packages**", "", table(["Package", "Importing files"], [(n.label, n.data.get("importers")) for n in ext_nodes[:40]])]
    return "\n".join(out)


def entry_points(c: Ctx) -> str:
    f = c.f
    rows = [(p, _entry_reason(f, p)) for p in f.overview.entry_points]
    out = [table(["File", "Why it is an entry point"], rows, "_No entry points detected by convention._")]
    starts = [b for b in f.build_commands if b["name"] in ("start", "dev", "serve", "cmd", "entrypoint", "run", "main")]
    if starts:
        out += ["", f"{D} Start commands:", "", table(["Source", "Name", "Command"], [(b["source"], b["name"], b["command"]) for b in starts])]
    return "\n".join(out)


# ----------------------------------------------------------------------------- 11
def api_reference(c: Ctx) -> str:
    f = c.f
    if not f.routes:
        return f"{D} No HTTP/GraphQL/WebSocket route definitions were detected. Supported: FastAPI, Flask, Django urls, Express/Koa/Hono-style routers, NestJS, Next.js route handlers & API routes, Spring, ASP.NET, Gin/Echo/chi/net-http, Laravel, Rails/Sinatra, Actix/Rocket/Axum, GraphQL type defs, Socket.IO events."
    out = [f"{D} {len(f.routes)} endpoints. Paths include router/blueprint prefixes and mount prefixes where they could be resolved statically.", ""]
    out.append(table(["Method", "Path", "Handler", "Location", "Framework", "Auth / guards"],
                     [(r.method, r.path, r.handler or "", f"{r.file}:{r.line}", r.framework, ", ".join(r.auth) or "—") for r in f.routes]))
    out += ["", "### Endpoint details", ""]
    for r in f.routes[:200]:
        out.append(f"#### `{r.method} {r.path}`")
        out.append(f"- Handler: `{r.handler or '?'}` at {loc(r.file, r.line)} ({r.framework}, {r.kind})")
        if r.params:
            out.append(f"- Parameters: {', '.join(f'`{p}`' for p in r.params)}")
        if r.body_model:
            out.append(f"- Request body model: `{r.body_model}`")
        if r.response_model:
            out.append(f"- Response model: `{r.response_model}`")
        out.append(f"- Authentication: {', '.join(f'`{a}`' for a in r.auth) if r.auth else 'none detected'}")
        if r.middleware:
            out.append(f"- Middleware: {', '.join(f'`{m}`' for m in r.middleware)}")
        if r.status_codes:
            out.append(f"- Status codes referenced: {', '.join(str(s) for s in r.status_codes)}")
        if r.errors:
            out.append(f"- Raises: {', '.join(f'`{e}`' for e in r.errors)}")
        tr = c.resolver.trace_route(r)
        if tr is not None and (tr.children or tr.db_ops):
            out.append(f"- Static call trace {I}:")
            out.extend("  " + ln for ln in render_trace(tr, 0)[1:])
        elif r.calls:
            out.append(f"- Calls: {', '.join(f'`{x}`' for x in r.calls[:12])}")
        callers = [cc for cc in f.client_calls if cc.matched_route == f"{r.method} {r.path}"]
        if callers:
            out.append(f"- Called from client code: {', '.join(loc(cc.file, cc.line) for cc in callers[:6])}")
        out.append("")
    return "\n".join(out)


def client_calls(c: Ctx) -> str:
    f = c.f
    if not f.client_calls:
        return f"{D} No client-side HTTP calls with literal URLs were detected (fetch/axios/requests/httpx and similar)."
    return table(["Method", "URL (as written)", "Location", "Matched backend route"],
                 [(x.method, x.url, f"{x.file}:{x.line}", x.matched_route or "— no match") for x in f.client_calls])


def integration_map(c: Ctx) -> str:
    f = c.f
    cats = ("integration", "cloud", "queue", "cache", "storage", "http_client", "realtime", "ai", "logging")
    techs = [t for t in f.technologies if t.category in cats]
    out = ["### External technologies", "", table(["Technology", "Category", "Class", "Evidence"], [(t.name, t.category, t.classification.value, ", ".join(e.label() for e in t.evidence[:3])) for t in techs]), ""]
    ext_calls = [x for x in f.client_calls if x.url.startswith(("http://", "https://")) and not re.search(r"localhost|127\.0\.0\.1", x.url)]
    out += ["### Outbound calls to absolute URLs", "", table(["Method", "URL", "Location"], [(x.method, x.url, f"{x.file}:{x.line}") for x in ext_calls]), ""]
    cfg_calls = [x for x in f.client_calls if not x.matched_route and x.url.startswith(("{", "${"))]
    out += [f"### Calls through a configurable base URL (no matching route in this repository) {I}", "",
            table(["Method", "URL template", "Location"], [(x.method, x.url, f"{x.file}:{x.line}") for x in cfg_calls], "_None._"), ""]
    keyish = [e for e in f.env_vars if re.search(r"(API|KEY|TOKEN|SECRET|URL|HOST|DSN|BUCKET|QUEUE|WEBHOOK)", e.name)]
    out += ["### Integration-related environment variables", "", table(["Variable", "Read in"], [(e.name, ", ".join(r.label() for r in e.used_in[:3])) for e in keyish]), ""]
    out += ["### Frontend ↔ backend", "", client_calls(c), "", "### Interpretation", "",
            claims_block(f.synthesis.frontend_backend + f.synthesis.integrations, c.ai_missing("integration analysis"))]
    return "\n".join(out)


# ----------------------------------------------------------------------------- 12-14
def database_schema(c: Ctx) -> str:
    f = c.f
    techs = [t for t in f.technologies if t.category in ("database", "orm", "migration")]
    out = ["### Database technologies", "", table(["Technology", "Category", "Class", "Evidence"], [(t.name, t.category, t.classification.value, ", ".join(e.label() for e in t.evidence[:3])) for t in techs], f"{U} No database technology detected."), ""]
    if not f.db_models:
        out.append(f"{U} No ORM models, Prisma models or SQL `CREATE TABLE` statements were found. If the project uses a database, its schema lives outside this repository or in a format not yet supported (e.g. migrations generated at runtime).")
        return "\n".join(out)
    out += [f"### Models / tables ({len(f.db_models)})", ""]
    for d in f.db_models:
        out.append(f"#### `{d.name}`" + (f" → table `{d.table}`" if d.table else ""))
        out.append(f"{D} {d.orm}, defined at {loc(d.file, d.line)}" + (f"; also described by {', '.join(f'`{x}`' for x in d.also_defined_in)}" if d.also_defined_in else ""))
        out.append("")
        if d.fields:
            out.append(table(["Column", "Type", "PK", "FK", "Nullable", "Unique", "Index", "Default", "Line"],
                             [(x.name, x.type, "✓" if x.primary_key else "", x.foreign_key or "", "" if x.nullable is None else ("yes" if x.nullable else "no"),
                               "✓" if x.unique else "", "✓" if x.index else "", x.default or "", x.line) for x in d.fields]))
        else:
            out.append(f"{U} Field list could not be extracted for this model.")
        if d.indexes:
            out.append(f"\nIndexes: {', '.join(f'`{x}`' for x in d.indexes)}")
        out.append("")
    if f.migrations:
        out += ["### Migrations", "", bullet([loc(p) for p in f.migrations[:60]])]
    return "\n".join(out)


def _mid(x: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", x) or "_"


def er_diagram(c: Ctx) -> str:
    f = c.f
    if not f.db_models:
        return ""
    names = {d.name for d in f.db_models}
    table_to_model = {d.table: d.name for d in f.db_models if d.table}
    out = ["```mermaid", "erDiagram"]
    for d in f.db_models[:60]:
        cols = [x for x in d.fields[:12] if re.match(r"^\w+$", x.name)]
        if cols:
            out.append(f"  {_mid(d.name)} {{")
            for x in cols:
                typ = _mid((x.type or "unknown").split("(")[0])[:20]
                out.append(f"    {typ} {x.name}{' PK' if x.primary_key else (' FK' if x.foreign_key else '')}")
            out.append("  }")
        else:
            out += [f"  {_mid(d.name)} {{", "    unknown fields_not_extracted", "  }"]
    seen: set[tuple[str, str]] = set()
    for d in f.db_models[:60]:
        for r in d.relationships:
            tgt = table_to_model.get(str(r.get("target") or ""), str(r.get("target") or ""))
            key = tuple(sorted((d.name, tgt)))
            if tgt in names and key not in seen:
                seen.add(key)  # type: ignore[arg-type]
                card = {"one_to_many": "||--o{", "many_to_one": "}o--||", "one_to_one": "||--||", "many_to_many": "}o--o{"}.get(str(r.get("kind")), "}o--||")
                out.append(f"  {_mid(d.name)} {card} {_mid(tgt)} : {_mid(str(r.get('name')))}")
        for x in d.fields:
            if x.foreign_key:
                tgt = table_to_model.get(x.foreign_key.split(".")[0], x.foreign_key.split(".")[0])
                key = tuple(sorted((d.name, tgt)))
                if tgt in names and key not in seen:
                    seen.add(key)  # type: ignore[arg-type]
                    out.append(f"  {_mid(d.name)} }}o--|| {_mid(tgt)} : {x.name}")
    out.append("```")
    return "\n".join(out)


def database_relationships(c: Ctx) -> str:
    f = c.f
    if not f.db_models:
        return f"{U} Not applicable — no data models found."
    rows = []
    for d in f.db_models:
        for r in d.relationships:
            rows.append((d.name, r.get("name"), r.get("kind"), r.get("target"), loc(d.file, r.get("line"))))
        for x in d.fields:
            if x.foreign_key:
                rows.append((d.name, x.name, "foreign_key", x.foreign_key, loc(d.file, x.line)))
    head = (f"{D} Relationships declared in models/DDL.\n\n" + table(["Model", "Field", "Kind", "Target", "Location"], rows)) if rows else \
        f"{U} No relationships or foreign keys were extracted from the models."
    return head + "\n\n" + er_diagram(c)


def database_operations(c: Ctx) -> str:
    f = c.f
    if not f.db_operations:
        return f"{D} No database access calls were detected (ORM sessions, Prisma, Mongoose, raw `query/execute`)."
    by_file: dict[str, list] = defaultdict(list)
    for o in f.db_operations:
        by_file[o.file].append(o)
    out = [f"{D} {len(f.db_operations)} database operations in {len(by_file)} files.", "", "### Files performing database access", "",
           table(["File", "Operations", "Kinds", "Raw SQL"], [(p, len(ops), ", ".join(sorted({o.operation for o in ops})), sum(1 for o in ops if o.raw_sql))
                                                       for p, ops in sorted(by_file.items(), key=lambda kv: -len(kv[1]))]), "", "### Operation list", ""]
    out.append(table(["Location", "Operation", "Target", "SQL / note"], [(f"{o.file}:{o.line}", o.operation, o.target or "", o.snippet or "") for o in f.db_operations[:400]]))
    return "\n".join(out)


# ----------------------------------------------------------------------------- 14-18
def data_flow(c: Ctx) -> str:
    f = c.f
    out = ["### Interpretation", "", claims_block(f.synthesis.data_flow, c.ai_missing("data-flow analysis")), "", f"### Static request traces {I}", "",
           "Each trace follows the route handler's calls to functions resolved by name within the repository (preferring imported modules) and lists database operations found inside those functions. Dynamic dispatch, dependency injection containers and callbacks are not followed.", ""]
    n = 0
    for r in f.routes:
        tr = c.resolver.trace_route(r)
        if tr is None or not (tr.children or tr.db_ops):
            continue
        out.append(f"**`{r.method} {r.path}`**")
        out.extend(render_trace(tr))
        out.append("")
        n += 1
        if n >= 40:
            break
    if n == 0:
        out.append(f"{U} No route could be traced to internal functions or database operations.")
    return "\n".join(out)


def authentication(c: Ctx) -> str:
    f = c.f
    auth_t = [t for t in f.technologies if t.category == "auth"]
    protected = [r for r in f.routes if r.auth]
    unprotected = [r for r in f.routes if not r.auth and r.kind == "http"]
    auth_files = [m for m in f.modules if "auth" in m.roles]
    out = ["### Detected authentication technologies", "", table(["Technology", "Class", "Evidence"], [(t.name, t.classification.value, ", ".join(e.label() for e in t.evidence[:3])) for t in auth_t], f"{U} No authentication library detected."), ""]
    out += ["### Route protection", "", f"{D} {len(protected)} of {len([r for r in f.routes if r.kind == 'http'])} HTTP routes declare an auth dependency/guard/middleware.", ""]
    out.append(table(["Route", "Guards", "Location"], [(f"{r.method} {r.path}", ", ".join(r.auth), f"{r.file}:{r.line}") for r in protected[:80]]))
    if unprotected and protected:
        out += ["", "Routes **without** a detected guard (verify whether a global middleware protects them):", "",
                bullet([f"`{r.method} {r.path}` {loc(r.file, r.line)}" for r in unprotected[:60]])]
    out += ["", "### Auth-related code", "", table(["File", "Key symbols"], [(m.path, ", ".join(s.name for s in m.symbols if s.parent is None and s.kind in ("function", "class", "method"))[:160]) for m in auth_files]), ""]
    out += ["### Interpretation", "", claims_block(f.synthesis.authentication, c.ai_missing("an authentication analysis"))]
    return "\n".join(out)


def business_logic(c: Ctx) -> str:
    f = c.f
    svc = [m for m in f.modules if {"service", "repository", "worker"} & set(m.roles)]
    out = ["### Interpretation", "", claims_block(f.synthesis.business_logic, c.ai_missing("business-logic analysis")), "",
           f"### Service-layer code {D}", "", table(["File", "Functions / classes"], [(m.path, ", ".join(s.name for s in m.symbols if s.kind in ("function", "method", "class"))[:200]) for m in svc], "_No files with a service/repository/worker role were detected._")]
    return "\n".join(out)


def core_functionality(c: Ctx) -> str:
    f = c.f
    groups: dict[str, list[str]] = defaultdict(list)
    for r in f.routes:
        seg = [s for s in r.path.split("/") if s and not s.startswith((":", "{", "<", "*")) and s not in ("api", "v1", "v2")]
        groups[seg[0] if seg else "/"].append(f"{r.method} {r.path}")
    det = table(["Resource / area", "Endpoints"], [(k, ", ".join(v[:8]) + (" …" if len(v) > 8 else "")) for k, v in sorted(groups.items())], "_No routes to group._")
    return "### Interpretation\n\n" + claims_block(f.synthesis.core_functionality, c.ai_missing("a feature inventory")) + f"\n\n### Endpoint groups {D}\n\n" + det


def workflows(c: Ctx) -> str:
    f = c.f
    out = []
    for w in f.synthesis.workflows:
        flag = "" if w.verified else " ⚠ _unverified_"
        out.append(f"### {w.name} {A}{flag}")
        out.append("")
        out.append(f"1. **Trigger:** {w.trigger or 'unknown'}")
        out.append(f"2. **Handler:** {w.handler or 'unknown'}")
        out.append("3. **Functions executed:**")
        out.extend(f"   {i}. {s}" for i, s in enumerate(w.steps, 1))
        out.append(f"4. **Input data:** {w.input_data or 'unknown'}")
        out.append(f"5. **Transformations:** {w.transformations or 'unknown'}")
        out.append(f"6. **Output:** {w.output or 'unknown'}")
        out.append(f"7. **Dependencies:** {', '.join(w.dependencies) or 'none listed'}")
        out.append(f"8. **Errors:** {'; '.join(w.errors) or 'none listed'}")
        out.append(f"\nSources: {', '.join(s.label() for s in w.sources) or '_none_'}")
        out.append("")
    if not out:
        out.append(c.ai_missing("workflow tracing"))
        out.append("")
        out.append(f"Static traces of route handlers are available in the Data Flow section {I}.")
    return "\n".join(out)


# ----------------------------------------------------------------------------- 19-21
def configuration(c: Ctx) -> str:
    f = c.f
    out = ["### Environment variables", "", f"{D} Read sites come from `os.getenv`/`os.environ`, `process.env`, `import.meta.env`, `System.getenv`, `os.Getenv`, pydantic `BaseSettings` fields and similar. Definitions come from `.env.example`-style templates. Values are never reproduced.", ""]
    out.append(table(["Variable", "Defined in", "Read in", "Template has value"],
                     [(e.name, ", ".join(r.label() for r in e.defined_in[:3]) or "— (undocumented)", ", ".join(r.label() for r in e.used_in[:4]) or "— (not read in code)", "yes" if e.has_default else "") for e in f.env_vars]))
    out += ["", "### Configuration files", "", table(["File", "Kind", "Summary"], [(x.path, x.kind, esc(str(x.summary))[:220] if x.summary else "") for x in f.config_files[:200]])]
    return "\n".join(out)


def build_and_run(c: Ctx) -> str:
    f = c.f
    out = ["### Runtimes and package managers", "", table(["Technology", "Category", "Version", "Evidence"],
           [(t.name, t.category, t.version or "", ", ".join(e.label() for e in t.evidence[:2])) for t in f.technologies if t.category in ("runtime", "package_manager", "build")]), ""]
    out += ["### Commands found in the repository", "", table(["Source", "Name", "Command"], [(b["source"], b["name"], b["command"]) for b in f.build_commands[:120]], "_No scripts, Makefile targets or container commands found._"), ""]
    steps = []
    pms = {t.name for t in f.technologies if t.category == "package_manager"}
    for m in f.overview.manifests:
        d = str(PurePosixPath(m).parent)
        d = "." if d == "." else d
        name = PurePosixPath(m).name
        if name == "package.json":
            pm = "pnpm" if "pnpm" in pms else ("yarn" if "yarn" in pms else "npm")
            scripts = {b["name"] for b in f.build_commands if b["source"] == m}
            run = "dev" if "dev" in scripts else ("start" if "start" in scripts else None)
            steps.append(f"`cd {d} && {pm} install`" + (f" then `{pm} run {run}`" if run else ""))
        elif name in ("requirements.txt",) or name.startswith("requirements"):
            steps.append(f"`cd {d} && python -m venv .venv && . .venv/bin/activate && pip install -r {name}`")
        elif name == "pyproject.toml":
            steps.append(f"`cd {d} && pip install -e .` (or the project's poetry/uv workflow)")
        elif name == "go.mod":
            steps.append(f"`cd {d} && go build ./...`")
        elif name == "Cargo.toml":
            steps.append(f"`cd {d} && cargo build`")
        elif name in ("pom.xml",):
            steps.append(f"`cd {d} && mvn package`")
        elif name.startswith("build.gradle"):
            steps.append(f"`cd {d} && ./gradlew build`")
    if any(cf.kind == "docker-compose" for cf in f.config_files):
        steps.append("`docker compose up --build` (compose file present)")
    out += [f"### Likely setup steps {I}", "", "Derived from manifests; ContextForge never executes project code, so these are unverified.", "", bullet(dict.fromkeys(steps), "_Could not infer setup steps._")]
    return "\n".join(out)


def testing(c: Ctx) -> str:
    f = c.f
    t = f.test_info
    if not t or not t.get("test_files"):
        return f"{D} No test files were detected (looked for `tests/`, `__tests__/`, `*.test.*`, `*.spec.*`, `test_*.py`, `*_test.go`, `*Test.java`)." + \
            ("\n\nTesting frameworks declared: " + ", ".join(t.get("frameworks", [])) if t and t.get("frameworks") else "")
    ratio = (t.get("test_lines", 0) / max(1, f.overview.code_lines)) * 100
    out = [f"{D} {t['test_files']} test files (~{t.get('test_lines', 0):,} lines, {ratio:.0f}% of total lines of code).", "",
           f"Frameworks: {', '.join(t.get('frameworks', [])) or 'unknown'}", "", table(["Directory", "Test files"], list(t.get("directories", {}).items())[:60]), "",
           "Test-related commands:", "", table(["Source", "Name", "Command"], [(x["source"], x["name"], x["command"]) for x in t.get("commands", [])], "_None declared._")]
    return "\n".join(out)


# ----------------------------------------------------------------------------- 22-28
def _finding_table(items: list[Finding]) -> str:
    return table(["Severity", "Status", "Title", "Location", "Category", "Confidence", "Source"],
                 [(x.severity, x.status, x.title, f"{x.file}:{x.line_start}" if x.file else "", x.category, f"{x.confidence:.2f}", x.source) for x in items])


def _finding_details(items: list[Finding], limit: int = 120) -> str:
    out = []
    for x in items[:limit]:
        out.append(f"#### [{x.severity.upper()}] {x.title}")
        out.append(f"- **Status:** {x.status} · **Category:** {x.category} · **Confidence:** {x.confidence:.2f} · **Detected by:** {'AI review (verify!)' if x.source == 'ai' else 'static analysis'}")
        if x.file:
            out.append(f"- **Location:** {loc(x.file, x.line_start, x.line_end)}")
        out.append(f"- **Explanation:** {x.explanation}")
        if x.evidence:
            out.append(f"- **Evidence:** `{esc(x.evidence)[:300]}`")
        if x.impact:
            out.append(f"- **Potential impact:** {x.impact}")
        if x.suggestion:
            out.append(f"- **Suggested investigation / fix:** {x.suggestion}")
        out.append("")
    if len(items) > limit:
        out.append(f"_… {len(items) - limit} more findings in ANALYSIS data (`data/PROJECT_FACTS.json`)._")
    return "\n".join(out)


def _sorted(items: list[Finding]) -> list[Finding]:
    return sorted(items, key=lambda x: (SEV_ORDER.get(x.severity, 9), -x.confidence, x.file or ""))


STATUS_LEGEND = "Status legend: **confirmed** = directly evidenced in code/config; **suspicious** = pattern match that needs context; **manual_verification** = cannot be decided statically (or proposed by AI)."


def security_review(c: Ctx) -> str:
    items = _sorted([x for x in c.f.findings if x.group == "security"])
    secrets = c.f.secrets
    out = [STATUS_LEGEND, "", "Secret values are never included: detected secrets are shown as redacted placeholders and were never sent to the AI provider.", ""]
    out += ["### Summary", "", _finding_table(items) if items else f"{D} No security findings from the static rules.", ""]
    out += [f"### Secret scan ({len(secrets)} hits)", "", table(["File", "Line", "Kind", "Redacted value"], [(s.file, s.line, s.kind, s.redacted) for s in secrets[:100]], f"{D} No hardcoded secrets detected."), ""]
    out += ["### Details", "", _finding_details(items)]
    return "\n".join(out)


def reliability_review(c: Ctx) -> str:
    items = _sorted([x for x in c.f.findings if x.group == "reliability" or x.category in ("unhandled-exception", "null-reference", "error-handling", "missing-timeout", "blocking-io")])
    seen = set()
    uniq = []
    for x in items:
        if x.id not in seen:
            seen.add(x.id)
            uniq.append(x)
    return "\n".join([STATUS_LEGEND, "", "### Summary", "", _finding_table(uniq) if uniq else f"{D} No reliability findings.", "", "### Details", "", _finding_details(uniq)])


def potential_issues(c: Ctx) -> str:
    items = _sorted([x for x in c.f.findings if x.group == "issue" and x.category != "technical-debt"])
    by_cat = Counter(x.category for x in items)
    out = [STATUS_LEGEND, "", "### By category", "", table(["Category", "Count"], by_cat.most_common()), "", "### Findings", "", _finding_table(items) if items else f"{D} No issues detected.", "", "### Details", "", _finding_details(items)]
    return "\n".join(out)


def bug_analysis(c: Ctx) -> str:
    bugs = _sorted([x for x in c.f.findings if x.category in ("undefined-reference", "syntax", "null-reference", "api-contract", "suspicious-import", "circular-dependency",
                                                           "unhandled-exception", "suspicious-code", "type-inconsistency", "database") or x.source == "ai"])
    out = ["Findings most likely to manifest as runtime bugs, ordered by severity and confidence.", "", _finding_table(bugs) if bugs else f"{D} No bug-class findings.", "", _finding_details(bugs, 80)]
    return "\n".join(out)


def dependencies(c: Ctx) -> str:
    f = c.f
    by_manifest: dict[str, list] = defaultdict(list)
    for d in f.dependencies:
        by_manifest[d.manifest].append(d)
    out = [f"{D} Direct dependencies declared in manifests. `used` compares declared packages with imports found in parsed source (✓ imported, ✗ never imported, blank = not applicable/unknown, e.g. CLI tools, plugins, DB drivers).", ""]
    for m, deps in sorted(by_manifest.items()):
        out.append(f"### `{m}` ({len(deps)})")
        out.append("")
        out.append(table(["Package", "Version", "Scope", "Category", "Used", "Line"],
                         [(d.name, d.version or "", "dev" if d.dev else "runtime", d.category or "", "" if d.used is None else ("✓" if d.used else "✗"), d.line or "") for d in deps]))
        out.append("")
    if not f.dependencies:
        out.append(f"{U} No dependency manifests were found or parsed.")
    lock = [x.path for x in c.included if x.category == FileCategory.LOCKFILE]
    out.append(f"Lockfiles present: {', '.join(f'`{x}`' for x in lock) or 'none'} (lockfiles are inventoried but resolved versions are not analysed).")
    return "\n".join(out)


def technical_debt(c: Ctx) -> str:
    f = c.f
    todos = [x for x in f.findings if x.category == "technical-debt"]
    dup = [x for x in f.findings if x.category == "duplicated-logic"]
    big_files = sorted([x for x in c.included if x.category == FileCategory.SOURCE and x.code_lines > 600], key=lambda x: -x.code_lines)[:20]
    big_funcs = sorted([s for m in f.modules for s in m.symbols if s.kind in ("function", "method") and s.line_end - s.line_start > 120], key=lambda s: s.line_start - s.line_end)[:20]
    out = ["### Interpretation", "", claims_block(f.synthesis.technical_debt, c.ai_missing("a technical-debt assessment")), "",
           f"### Developer markers (TODO/FIXME/HACK) — {len(todos)} {D}", "", table(["Marker", "Location", "Text"], [(x.title.split()[0], f"{x.file}:{x.line_start}", x.explanation) for x in todos[:60]]), "",
           f"### Large files {D}", "", table(["File", "Code lines"], [(x.path, x.code_lines) for x in big_files], "_No source file exceeds 600 code lines._"), "",
           f"### Long functions (>120 lines) {D}", "", table(["Function", "Location", "Lines"], [(s.name, f"{s.file}:{s.line_start}-{s.line_end}", s.line_end - s.line_start) for s in big_funcs], "_None._"), "",
           f"### Duplicated implementations {D}", "", table(["Title", "Evidence"], [(x.title, x.evidence) for x in dup], "_None detected._"), "",
           f"### Import cycles {D}", "", bullet([" ⇄ ".join(cyc) for cyc in f.graph.cycles[:15]], "_None._")]
    return "\n".join(out)


def limitations(c: Ctx) -> str:
    f = c.f
    status = Counter(m.status for m in f.manifest)
    failed_parse = [m for m in f.modules if not m.parse_ok]
    partial_parse = [m for m in f.modules if m.parse_ok and m.parse_error]
    truncated = [m for m in f.manifest if m.reason and "truncated" in m.reason]
    items = [
        f"{D} Analysis coverage: " + ", ".join(f"{v} {k}" for k, v in status.items()) + ". See `data/ANALYSIS_MANIFEST.json` for every file and the reason it was or was not analysed.",
        f"{D} ContextForge never executes uploaded code, installs dependencies or runs migrations: runtime behaviour, generated code and dynamic configuration are not observed.",
        f"{D} Parsers: AST for Python (stdlib `ast`), tree-sitter for JavaScript/TypeScript, schema parsers for Prisma and SQL DDL" +
        (f"; regex heuristics (approximate symbol boundaries, no type information) for {', '.join(c.heuristic_langs)}." if c.heuristic_langs else "."),
        "Route extraction is static: routes registered dynamically (loops, decorators from factories, runtime configuration) and some cross-file prefix chains may be missing or incomplete.",
        "Call traces are resolved by symbol name; dynamic dispatch, dependency injection and higher-order callbacks are not followed.",
        "Dependency vulnerability checks use a small offline advisory table and declared version ranges; lockfile-resolved versions are not evaluated.",
    ]
    if failed_parse:
        items.append(f"{D} {len(failed_parse)} files failed to parse: " + ", ".join(f"`{m.path}` ({m.parse_error})" for m in failed_parse[:10]))
    if partial_parse:
        items.append(f"{D} {len(partial_parse)} files parsed with syntax errors (partial extraction): " + ", ".join(f"`{m.path}`" for m in partial_parse[:10]))
    if truncated:
        items.append(f"{D} {len(truncated)} files were sent to the AI provider truncated to the per-file budget.")
    if not f.ai.enabled:
        items.append(f"{D} AI interpretation was disabled; sections marked {U} need an LLM provider to be filled in.")
    else:
        items.append(f"{D} AI stages: " + ", ".join(f"{k}={v}" for k, v in sorted(f.ai.stages.items())) + f"; {f.ai.requests} requests, {f.ai.failed_requests} failed, {f.ai.cached_responses} served from cache.")
        for e in f.ai.errors[:15]:
            items.append(f"AI error: {e}")
    for w in f.warnings[:20]:
        items.append(f"Warning: {w}")
    return bullet(items)


def missing_information(c: Ctx) -> str:
    f = c.f
    items = []
    undocumented = [e.name for e in f.env_vars if e.used_in and not e.defined_in]
    if undocumented:
        items.append(f"Environment variables read in code but not documented in any template: {', '.join(f'`{x}`' for x in undocumented[:30])}.")
    if not f.overview.env_templates and f.env_vars:
        items.append("No `.env.example` (or similar) template exists although the code reads environment variables.")
    unmatched = [x for x in f.client_calls if not x.matched_route and not x.url.startswith("http")]
    if unmatched and f.routes:
        items.append(f"{len(unmatched)} client HTTP calls do not match any extracted route (backend may live outside this repository).")
    unresolved = [x for x in f.findings if x.category == "suspicious-import"]
    if unresolved:
        items.append(f"{len(unresolved)} relative imports point to files that are not in the archive.")
    no_fields = [d.name for d in f.db_models if not d.fields]
    if no_fields:
        items.append(f"Field lists unknown for models: {', '.join(no_fields[:15])}.")
    if any(t.category == "database" for t in f.technologies) and not f.db_models:
        items.append("A database technology is declared but no schema/models were found in the repository.")
    if not f.overview.test_paths:
        items.append("No automated tests were found.")
    if not f.readme_excerpt:
        items.append("No README with a project description was found.")
    if not any(x.category == FileCategory.LOCKFILE for x in c.included) and f.dependencies:
        items.append("No lockfile: exact dependency versions used in production cannot be determined.")
    excluded = [x for x in f.files if x.status == "excluded"]
    if excluded:
        items.append(f"{len(excluded)} files were excluded by exclusion rules (e.g. dependencies, build output) and are not described.")
    return bullet(items, f"{D} No notable gaps were detected.")


def decisions(c: Ctx) -> str:
    f = c.f
    det = []
    if len(f.overview.subprojects) > 1:
        det.append(f"{I} Multi-project repository: {', '.join(f'`{s}`' for s in f.overview.subprojects)} each have their own manifest.")
    orms = sorted({t.name for t in f.technologies if t.category == "orm"})
    if orms:
        det.append(f"{D} Data access through {', '.join(orms)}.")
    fw = [t.name for t in f.technologies if t.category == "framework"]
    if fw:
        det.append(f"{D} Built on {', '.join(fw[:6])}.")
    if any(t.name == "Docker" for t in f.technologies):
        det.append(f"{D} Containerised deployment (Dockerfile present).")
    vals = [t.name for t in f.technologies if t.category == "validation"]
    if vals:
        det.append(f"{D} Input/schema validation with {', '.join(vals)}.")
    return "\n".join(f"- {x}" for x in det) + "\n\n" + claims_block(f.synthesis.architectural_decisions, c.ai_missing("architectural decisions"))


def debugging_entry_points(c: Ctx) -> str:
    f = c.f
    indeg = Counter(e.target for e in f.graph.edges if e.type == "imports")
    central = [(p, n) for p, n in indeg.most_common(12)]
    err_handlers = [s for m in f.modules for s in m.symbols if re.search(r"(exception_handler|errorHandler|error_handler|handle_error|onError|ErrorBoundary)", s.name + " ".join(s.decorators))]
    out = [claims_block(f.synthesis.debugging_entry_points, c.ai_missing("debugging guidance")), "", f"### Deterministic starting points {D}", "",
           "**Application entry points:** " + (", ".join(loc(p) for p in f.overview.entry_points) or "none detected"), "",
           "**Most imported files (changes here have the widest blast radius):**", "", table(["File", "Imported by"], central), "",
           "**Error handlers:** " + (", ".join(f"`{s.name}` {loc(s.file, s.line_start)}" for s in err_handlers[:10]) or "none detected"), "",
           "**Route definition files:** " + (", ".join(loc(p) for p in sorted({r.file for r in f.routes})[:20]) or "none")]
    return "\n".join(out)


def file_index(c: Ctx) -> str:
    f = c.f
    rows = []
    for x in sorted(f.files, key=lambda x: x.path):
        mod = c.mod_by_path.get(x.path)
        me = c.manifest_by_path.get(x.path)
        rows.append((x.path, x.language or "", x.category.value, x.lines or "", (me.status if me else x.status), ", ".join(mod.roles) if mod else "",
                     (me.reason if me and me.reason else (x.status_reason or "")), (c.summary_by_path[x.path].purpose[:120] if x.path in c.summary_by_path else "")))
    return f"{D} Every file in the archive, including excluded and skipped files.\n\n" + table(["Path", "Language", "Category", "Lines", "Analysis status", "Roles", "Reason", "Summary"], rows)


def open_questions(c: Ctx) -> str:
    f = c.f
    det = []
    for e in [e for e in f.env_vars if e.used_in and not e.defined_in][:10]:
        det.append(f"What value/format does `{e.name}` expect (read at {e.used_in[0].label()})?")
    for x in [x for x in f.client_calls if not x.matched_route and not x.url.startswith("http")][:8]:
        det.append(f"Where is `{x.method} {x.url}` (called at {loc(x.file, x.line)}) served?")
    if f.routes and not any(r.auth for r in f.routes) and not any(t.category == "auth" for t in f.technologies):
        det.append("Is authentication enforced outside this codebase (API gateway, reverse proxy)? No auth was detected in the routes.")
    if any(t.category == "database" for t in f.technologies) and not f.migrations:
        det.append("How is the database schema created/migrated? No migration files were found.")
    for cyc in f.graph.cycles[:3]:
        det.append(f"Is the import cycle between {', '.join(f'`{p}`' for p in cyc[:3])} intentional?")
    ai = [f"{q} {A}" for q in f.synthesis.open_questions]
    return bullet(ai + [f"{q} {I}" for q in det], f"{D} No open questions were generated.")
