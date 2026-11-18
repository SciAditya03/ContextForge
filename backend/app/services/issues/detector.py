"""Bug and issue intelligence: deterministic detectors over the extracted facts."""

from __future__ import annotations

import hashlib
import re
import sys
from collections import defaultdict

from pyflakes import api as pyflakes_api
from pyflakes import messages as pf_messages
from pyflakes.reporter import Reporter

from app.schemas.facts import ClientCall, DependencyGraph, FileCategory, Finding
from app.services.parsing.python_parser import compat_source
from app.services.security.scanner import ScanContext


def _fid(*parts: object) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode(), usedforsecurity=False).hexdigest()[:10]


class _Collect(Reporter):
    def __init__(self) -> None:
        self.messages: list[pf_messages.Message] = []
        self.syntax: list[tuple[int, str]] = []

    def flake(self, message: pf_messages.Message) -> None:  # type: ignore[override]
        self.messages.append(message)

    def syntaxError(self, filename: str, msg: str, lineno: int, offset: int, text: str) -> None:  # type: ignore[override]  # noqa: N802
        self.syntax.append((lineno or 0, msg))

    def unexpectedError(self, filename: str, msg: str) -> None:  # type: ignore[override]  # noqa: N802
        pass


def _targets_newer_python(ctx: ScanContext) -> str | None:
    """Return the declared minimum Python version when it is newer than the running interpreter."""
    for t in ctx.technologies:
        if t.category == "runtime" and t.name == "Python" and t.version:
            m = re.search(r"(\d+)\.(\d+)", t.version)
            if m and (int(m.group(1)), int(m.group(2))) > sys.version_info[:2]:
                return f"{m.group(1)}.{m.group(2)}"
    return None


def _pyflakes(ctx: ScanContext) -> list[Finding]:
    out: list[Finding] = []
    gen = _generated(ctx)
    for m in ctx.modules:
        if m.language != "Python" or m.path in gen:
            continue
        rec = next((f for f in ctx.files if f.path == m.path), None)
        rep = _Collect()
        source = ctx.text(m.path)
        if m.parse_ok and m.parse_error and "newer Python syntax" in m.parse_error:
            source = compat_source(source) or source
        pyflakes_api.check(source, m.path, rep)  # static analysis only; nothing is executed
        module_names = {s.name for s in m.symbols if s.parent is None}
        is_test = rec is not None and rec.category == FileCategory.TEST
        newer_target = _targets_newer_python(ctx)
        for line, msg in rep.syntax:
            out.append(Finding(id=_fid("syntax", m.path, line), title="Python syntax error" if not newer_target else "Python syntax not parseable by the analyser",
                               severity="medium" if newer_target else "high", category="syntax", file=m.path, line_start=line,
                               explanation=msg + (f" The project targets Python {newer_target}, newer than the analyser's {sys.version_info.major}.{sys.version_info.minor}; "
                                                  "this may be valid newer syntax." if newer_target else ""),
                               evidence=msg, impact="The module cannot be imported (if this is a genuine error).", suggestion="Fix the syntax error or confirm it is valid for the target Python version.",
                               confidence=0.5 if newer_target else 0.95, status="manual_verification" if newer_target else "confirmed"))
        unused_imports = 0
        for msg in rep.messages:
            text = msg.message % msg.message_args
            line = msg.lineno
            if isinstance(msg, pf_messages.UndefinedName):
                name = msg.message_args[0]
                if name in {"__file__", "__name__", "reveal_type"}:
                    continue
                if name in module_names:
                    # defined later in the same module: a forward reference (fine in annotations with
                    # `from __future__ import annotations` or on Python >= 3.14 / PEP 649)
                    out.append(Finding(id=_fid("fwdref", m.path, line, name), title=f"Forward reference to '{name}' before its definition", severity="info",
                                       category="undefined-reference", file=m.path, line_start=line, line_end=line,
                                       explanation=f"pyflakes: {text}. `{name}` is defined later in this module.", evidence=text,
                                       impact="NameError only if evaluated eagerly (Python < 3.14 without postponed annotations).",
                                       suggestion="Quote the annotation or add `from __future__ import annotations` if older Python versions must be supported.",
                                       confidence=0.5, status="manual_verification"))
                    continue
                out.append(Finding(id=_fid("undef", m.path, line, name), title=f"Undefined name '{name}'", severity="low" if is_test else "high",
                                   category="undefined-reference", file=m.path, line_start=line, line_end=line, explanation=f"pyflakes: {text}.",
                                   evidence=text, impact="NameError at runtime when this code path executes.",
                                   suggestion="Import or define the name, or fix the typo.", confidence=0.85, status="confirmed"))
            elif isinstance(msg, pf_messages.UndefinedLocal | pf_messages.UndefinedExport):
                out.append(Finding(id=_fid("undefl", m.path, line), title="Undefined local/export reference", severity="medium", category="undefined-reference",
                                   file=m.path, line_start=line, explanation=f"pyflakes: {text}.", evidence=text, impact="Runtime error on this path.",
                                   suggestion="Assign before use / fix __all__.", confidence=0.8, status="confirmed"))
            elif isinstance(msg, pf_messages.UnusedImport):
                unused_imports += 1
                if unused_imports <= 3 and not m.path.endswith("__init__.py"):
                    out.append(Finding(id=_fid("unusedimp", m.path, line), title="Unused import", severity="info", category="dead-code", file=m.path,
                                       line_start=line, explanation=f"pyflakes: {text}.", evidence=text, impact="Noise; may hide a missing usage or slow imports.",
                                       suggestion="Remove the import or use it.", confidence=0.7, status="confirmed"))
            elif isinstance(msg, pf_messages.RedefinedWhileUnused):
                out.append(Finding(id=_fid("redef", m.path, line), title="Name redefined before use", severity="low", category="duplicated-logic", file=m.path,
                                   line_start=line, explanation=f"pyflakes: {text}.", evidence=text, impact="The earlier definition is dead or shadowed unexpectedly.",
                                   suggestion="Rename or remove the duplicate definition.", confidence=0.7, status="confirmed"))
            elif isinstance(msg, pf_messages.UnusedVariable):
                continue
            elif isinstance(msg, pf_messages.IsLiteral | pf_messages.FStringMissingPlaceholders | pf_messages.PercentFormatInvalidFormat | pf_messages.StringDotFormatExtraPositionalArguments):
                out.append(Finding(id=_fid("pflk", m.path, line, type(msg).__name__), title=f"Suspicious expression ({type(msg).__name__})", severity="low",
                                   category="suspicious-code", file=m.path, line_start=line, explanation=f"pyflakes: {text}.", evidence=text,
                                   impact="Likely logic error.", suggestion="Review the expression.", confidence=0.7, status="confirmed"))
    return out


def _unresolved_imports(ctx: ScanContext) -> list[Finding]:
    out = []
    for m in ctx.modules:
        for imp in m.imports:
            if imp.resolved or imp.external:
                continue
            is_rel = imp.module.startswith((".", "/")) and m.language in {"JavaScript", "TypeScript"} or (m.language == "Python" and imp.module.startswith("/"))
            if not is_rel:
                continue
            spec = imp.module.lstrip("/") if m.language == "Python" else imp.module
            if m.language == "Python" and spec.split(".")[-1] in {"__version__", "version", "_version"}:
                continue
            if m.language in {"JavaScript", "TypeScript"} and re.search(r"\.(css|scss|sass|less|svg|png|jpg|jpeg|gif|webp|json|md|html|txt)$", spec):
                continue
            out.append(Finding(id=_fid("unres", m.path, imp.line, spec), title=f"Unresolved relative import '{spec}'", severity="medium", category="suspicious-import",
                               file=m.path, line_start=imp.line, explanation="A relative import could not be matched to any file in the archive.",
                               evidence=f"import of '{imp.module}' (names: {', '.join(imp.names[:5]) or '-'})",
                               impact="Module-not-found at build/run time, or the file was excluded from the upload.",
                               suggestion="Check the path/casing, and whether the target was excluded or generated at build time.",
                               confidence=0.55, status="suspicious"))
    return out[:60]


def _cycles(graph: DependencyGraph) -> list[Finding]:
    out = []
    for comp in graph.cycles[:30]:
        out.append(Finding(id=_fid("cycle", *comp), title=f"Circular import between {len(comp)} files", severity="medium" if len(comp) < 6 else "high",
                           category="circular-dependency", file=comp[0], explanation="These files import each other directly or transitively.",
                           evidence=" ⇄ ".join(comp[:10]) + (" …" if len(comp) > 10 else ""),
                           impact="Import-order bugs (partially initialised modules), tight coupling, harder refactoring.",
                           suggestion="Extract shared definitions into a lower-level module or use dependency inversion.", confidence=0.9, status="confirmed"))
    return out


def _unused_dependencies(ctx: ScanContext) -> list[Finding]:
    out = []
    for d in ctx.dependencies:
        if d.used is False and not d.dev:
            out.append(Finding(id=_fid("unuseddep", d.manifest, d.name), title=f"Dependency '{d.name}' never imported", severity="info", category="unused-dependency",
                               file=d.manifest, line_start=d.line, explanation="The package is declared as a runtime dependency but no import of it was found in analysed source files.",
                               evidence=f"{d.manifest}: {d.name} {d.version or ''}".strip(), impact="Larger install/attack surface; possibly a leftover.",
                               suggestion="Confirm it is not loaded dynamically / via config, then remove it.", confidence=0.45, status="suspicious"))
    return out[:40]


def _env_issues(ctx: ScanContext) -> list[Finding]:
    out = []
    has_templates = any(f.category == FileCategory.ENV_TEMPLATE for f in ctx.files if f.status == "included")
    builtin = {"NODE_ENV", "PORT", "HOME", "PATH", "PWD", "CI", "HOSTNAME", "DEBUG", "PYTHONPATH", "TZ", "LANG", "USER", "VERCEL", "VERCEL_URL", "NEXT_RUNTIME"}
    for ev in ctx.env_vars:
        if ev.used_in and not ev.defined_in and ev.name not in builtin:
            ref = ev.used_in[0]
            out.append(Finding(id=_fid("envmissing", ev.name), title=f"Environment variable '{ev.name}' not documented", severity="low" if has_templates else "info",
                               category="missing-configuration", file=ref.file, line_start=ref.line_start,
                               explanation=f"`{ev.name}` is read in code ({len(ev.used_in)} place(s)) but is not defined in any .env template in the repository.",
                               evidence=", ".join(f"{r.file}:{r.line_start}" for r in ev.used_in[:4]), impact="Deployments may start with a missing/empty value.",
                               suggestion="Document it in .env.example with a safe placeholder and validate at startup.", confidence=0.6, status="confirmed"))
        elif ev.defined_in and not ev.used_in and has_templates:
            ref = ev.defined_in[0]
            out.append(Finding(id=_fid("envunused", ev.name), title=f"Environment variable '{ev.name}' defined but never read in code", severity="info",
                               category="missing-configuration", file=ref.file, line_start=ref.line_start,
                               explanation="Declared in an env template but no direct read was found (it may be consumed by a framework or config loader).",
                               evidence=f"{ref.file}:{ref.line_start}", impact="Stale configuration or indirect usage.", suggestion="Verify and clean up.",
                               confidence=0.35, status="manual_verification"))
    return out[:60]


def _api_contracts(ctx: ScanContext, calls: list[ClientCall]) -> list[Finding]:
    out: list[Finding] = []
    if not ctx.routes:
        return out
    for c in calls:
        if c.matched_route:
            method = c.matched_route.split(" ", 1)[0]
            if method not in (c.method, "ANY"):
                out.append(Finding(id=_fid("apimeth", c.file, c.line), title=f"HTTP method mismatch for {c.url}", severity="medium", category="api-contract",
                                   file=c.file, line_start=c.line, explanation=f"Client sends {c.method} but the matched backend route is {c.matched_route}.",
                                   evidence=f"{c.method} {c.url} → {c.matched_route}", impact="405 Method Not Allowed at runtime.",
                                   suggestion="Align client method with the route definition.", confidence=0.55, status="suspicious"))
            continue
        if c.url.startswith(("http://", "https://")) and not re.search(r"localhost|127\.0\.0\.1", c.url):
            continue  # external API
        external_base = c.url.startswith(("{", "${")) and not re.search(r"(?i)(api_?base|base_?url|api_?url|backend)", c.url.split("}")[0]) or bool(re.match(r"^\{?\$?\{?[\w.]*(payment|stripe|github|slack|external|service|provider)", c.url, re.I))
        out.append(Finding(id=_fid("apinomatch", c.file, c.line), title=f"Client call to {c.method} {c.url} has no matching backend route", severity="info" if external_base else "low",
                           category="api-contract", file=c.file, line_start=c.line,
                           explanation="The URL used by this client call could not be matched to any route extracted from the repository." + (" Its base URL comes from configuration, so it may target an external service." if external_base else ""),
                           evidence=f"{c.method} {c.url}", impact="Possible 404, a route defined outside this repository, or a route the extractor could not detect.",
                           suggestion="Confirm the endpoint exists and that base-URL/prefix configuration matches.", confidence=0.35, status="manual_verification"))
    return out[:40]


def _generated(ctx: ScanContext) -> set[str]:
    return {f.path for f in ctx.files if f.generated}


def _duplicates(ctx: ScanContext) -> list[Finding]:
    buckets: dict[str, list[tuple[str, str, int, int]]] = defaultdict(list)
    gen = _generated(ctx)
    for m in ctx.modules:
        rec = next((f for f in ctx.files if f.path == m.path), None)
        if (rec is not None and rec.category == FileCategory.TEST) or m.path in gen:
            continue
        lines = ctx.text(m.path).splitlines()
        for s in m.symbols:
            if s.kind not in {"function", "method", "component", "hook"} or s.line_end - s.line_start < 6:
                continue
            body = lines[s.line_start : s.line_end]  # skip signature line
            norm = "\n".join(re.sub(r"\s+", " ", ln.strip()) for ln in body if ln.strip() and not ln.strip().startswith(("#", "//")))
            if len(norm) < 120:
                continue
            buckets[hashlib.sha1(norm.encode(), usedforsecurity=False).hexdigest()].append((m.path, s.name, s.line_start, s.line_end))
    out = []
    for h, occ in buckets.items():
        if len(occ) < 2:
            continue
        first = occ[0]
        out.append(Finding(id=_fid("dup", h), title=f"Duplicated implementation of '{first[1]}' ({len(occ)} copies)", severity="low", category="duplicated-logic",
                           file=first[0], line_start=first[2], line_end=first[3],
                           explanation="Function bodies are identical after whitespace normalisation.",
                           evidence="; ".join(f"{p}:{a}-{b} ({n})" for p, n, a, b in occ[:6]), impact="Bug fixes must be applied in several places; drift risk.",
                           suggestion="Extract a shared helper.", confidence=0.85, status="confirmed"))
    return out[:30]


def _inconsistent_types(ctx: ScanContext) -> list[Finding]:
    defs: dict[str, list[tuple[str, int, frozenset[str]]]] = defaultdict(list)
    gen = _generated(ctx)
    for m in ctx.modules:
        if m.language != "TypeScript" or m.path in gen:
            continue
        attrs: dict[str, set[str]] = defaultdict(set)
        lines = ctx.text(m.path).splitlines()
        for s in m.symbols:
            if s.kind in {"interface", "type"} and s.parent is None and s.name[:1].isupper():
                body = "\n".join(lines[s.line_start - 1 : s.line_end])
                attrs[s.name] = set(re.findall(r"^\s*(?:readonly\s+)?(\w+)\??\s*:", body, re.M))
                defs[s.name].append((m.path, s.line_start, frozenset(attrs[s.name])))
    out = []
    for name, ds in defs.items():
        if len(ds) < 2 or len({d[2] for d in ds}) < 2:
            continue
        out.append(Finding(id=_fid("typeinc", name), title=f"Type '{name}' defined {len(ds)} times with different shapes", severity="low", category="type-inconsistency",
                           file=ds[0][0], line_start=ds[0][1], explanation="The same type/interface name is declared in multiple files with different properties.",
                           evidence="; ".join(f"{p}:{ln} {{{', '.join(sorted(a))[:80]}}}" for p, ln, a in ds[:4]),
                           impact="Frontend/backend or module contracts may silently diverge.", suggestion="Define the type once and import it, or generate it from the API schema.",
                           confidence=0.6, status="suspicious"))
    return out[:20]


def _null_refs(ctx: ScanContext) -> list[Finding]:
    out = []
    pat = re.compile(r"^\s*(\w+)\s*=\s*.*\.(first|one_or_none|get|scalar_one_or_none|find_one|findOne|findUnique|findFirst|find)\(.*\)\s*;?\s*$")
    for m in ctx.modules:
        if m.language not in {"Python", "JavaScript", "TypeScript"}:
            continue
        lines = ctx.text(m.path).splitlines()
        for i, line in enumerate(lines):
            mm = pat.match(line.replace("await ", "").replace("const ", "").replace("let ", ""))
            if not mm or mm.group(2) == "get" and ".objects.get" not in line and "session.get" not in line and "db.get" not in line:
                continue
            var = mm.group(1)
            window = lines[i + 1 : i + 6]
            v = re.escape(var)
            guard_pat = (rf"\bif\s+(not\s+)?{v}\s*(:|\bis\b|==|!=|\band\b|\bor\b)|\bif\s*\(\s*!?\s*{v}\s*(\)|&&|\|\||===?|!==?)"
                         rf"|\b{v}\s+is\s+(not\s+)?None|\b{v}\s*(===?|!==?)\s*(null|undefined)|\bassert\s+{v}\b|\bnot\s+{v}\b|!{v}\b"
                         rf"|{v}\s*\?\?|{v}\?\.|raise_for|or_404|OrThrow")
            guard = any(re.search(guard_pat, w) for w in window)
            use = next((j for j, w in enumerate(window) if re.search(rf"\b{var}\.(?!\s)", w)), None)
            if use is not None and not guard and not re.search(r"OrThrow|or_404|get_or_404", line):
                out.append(Finding(id=_fid("null", m.path, i + 1), title=f"Possible null dereference of '{var}'", severity="medium", category="null-reference", file=m.path,
                                   line_start=i + 1, line_end=i + 2 + use, explanation=f"`{var}` comes from a lookup that can return no result and is dereferenced without a visible check.",
                                   evidence=line.strip()[:160], impact="AttributeError/TypeError (500) when the record does not exist.",
                                   suggestion="Check for None/null and return 404 or raise a domain error.", confidence=0.45, status="suspicious"))
    return out[:40]


def _todo_markers(ctx: ScanContext) -> list[Finding]:
    out = []
    pat = re.compile(r"(#|//|/\*|\*)\s*(TODO|FIXME|HACK|XXX|BUG)\b[:\s]*(.*)")
    for m in ctx.modules:
        for i, line in enumerate(ctx.text(m.path).splitlines(), 1):
            mm = pat.search(line)
            if mm:
                sev = "low" if mm.group(2) in {"FIXME", "BUG", "HACK"} else "info"
                out.append(Finding(id=_fid("todo", m.path, i), title=f"{mm.group(2)} marker", severity=sev, category="technical-debt", file=m.path, line_start=i,
                                   explanation=(mm.group(3) or "").strip()[:200] or "(no description)", evidence=line.strip()[:200],
                                   impact="Known incomplete or fragile code flagged by developers.", suggestion="Track and resolve.", confidence=0.95, status="confirmed"))
    return out[:80]


def _unhandled_route_errors(ctx: ScanContext) -> list[Finding]:
    out = []
    sym_index = {(s.file, s.name): s for m in ctx.modules for s in m.symbols}
    for r in ctx.routes:
        if r.kind != "http" or not r.handler:
            continue
        s = sym_index.get((r.file, r.handler.split(".")[-1]))
        if s is None:
            continue
        risky = [c for c in s.calls if re.search(r"(fetch|axios|requests\.|httpx|\.query|\.execute|prisma\.|\.save|\.commit|\.create|\.update|\.delete|open\(|json\.loads|JSON\.parse)", c)]
        if risky and not s.handles_exceptions and r.framework in {"Express"}:
            out.append(Finding(id=_fid("unhandled", r.file, r.line), title=f"Async route without error handling: {r.method} {r.path}", severity="medium", category="unhandled-exception",
                               file=r.file, line_start=s.line_start, line_end=s.line_end,
                               explanation="The handler performs I/O but has no try/catch; Express 4 does not forward rejected promises to error middleware.",
                               evidence=f"calls: {', '.join(risky[:5])}", impact="Unhandled promise rejection; the request may hang or the process may crash.",
                               suggestion="Wrap in try/catch and call next(err), or use an async error wrapper.", confidence=0.5, status="suspicious"))
    return out[:30]


def detect_issues(ctx: ScanContext, graph: DependencyGraph, calls: list[ClientCall]) -> list[Finding]:
    findings: list[Finding] = []
    for fn in (_pyflakes, _unresolved_imports, _unused_dependencies, _env_issues, _duplicates, _inconsistent_types, _null_refs, _todo_markers, _unhandled_route_errors):
        try:
            findings.extend(fn(ctx))  # type: ignore[operator]
        except Exception as exc:  # a detector bug must not break analysis
            findings.append(Finding(id=_fid("detector", fn.__name__), title=f"Detector {fn.__name__} failed", severity="info", category="analysis",
                                    explanation=str(exc)[:300], confidence=1.0, status="confirmed"))
    findings.extend(_cycles(graph))
    findings.extend(_api_contracts(ctx, calls))
    return findings
