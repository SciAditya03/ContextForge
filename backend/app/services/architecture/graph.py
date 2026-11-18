"""Import resolution, dependency graph construction and cycle detection."""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import PurePosixPath

from app.schemas.facts import (
    ConfigFile,
    DependencyGraph,
    FileRecord,
    GraphEdge,
    GraphNode,
    ImportRef,
    ModuleInfo,
)

STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"__future__", "typing_extensions"}
NODE_BUILTINS = {
    "fs", "path", "os", "http", "https", "url", "util", "crypto", "stream", "events", "child_process", "net", "tls", "zlib",
    "buffer", "assert", "querystring", "readline", "worker_threads", "cluster", "dns", "process", "timers", "perf_hooks", "v8", "vm",
}
JS_EXTS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts", ".vue", ".svelte", ".json"]


class ImportResolver:
    def __init__(self, files: list[FileRecord], configs: list[ConfigFile], go_modules: dict[str, str] | None = None) -> None:
        self.paths = {f.path for f in files if f.status == "included"}
        self.py_index: dict[str, list[str]] = defaultdict(list)  # dotted -> paths
        for p in self.paths:
            if p.endswith(".py"):
                dotted = p[:-3].replace("/", ".")
                if dotted.endswith(".__init__"):
                    dotted = dotted[: -len(".__init__")]
                self.py_index[dotted].append(p)
        self.ts_aliases: list[tuple[str, str, str]] = []  # (config_dir, alias_prefix, target_prefix)
        for c in configs:
            if c.kind == "typescript":
                base_dir = str(PurePosixPath(c.path).parent)
                base_dir = "" if base_dir == "." else base_dir
                base_url = (c.summary.get("baseUrl") or ".").strip("./")
                for alias, targets in (c.summary.get("paths") or {}).items():
                    if not targets:
                        continue
                    a = alias.rstrip("*")
                    t = targets[0].rstrip("*").lstrip("./")
                    tgt = "/".join(x for x in (base_dir, base_url, t) if x).rstrip("/")
                    self.ts_aliases.append((base_dir, a, tgt + "/" if a.endswith("/") else tgt))
        self.go_modules = go_modules or {}
        self.java_index: dict[str, str] = {}
        for p in self.paths:
            if p.endswith((".java", ".kt")):
                m = re.search(r"(?:^|/)(?:src/(?:main|test)/(?:java|kotlin)/)(.*)\.(java|kt)$", p)
                if m:
                    self.java_index[m.group(1).replace("/", ".")] = p

    # ------------------------------------------------------------------
    def resolve(self, imp: ImportRef, language: str) -> None:
        if language == "Python":
            self._resolve_py(imp)
        elif language in {"JavaScript", "TypeScript", "Vue", "Svelte"}:
            self._resolve_js(imp)
        elif language == "Go":
            for mod_name, mod_dir in self.go_modules.items():
                if imp.module.startswith(mod_name):
                    sub = imp.module[len(mod_name) :].strip("/")
                    d = "/".join(x for x in (mod_dir, sub) if x)
                    hit = next((p for p in sorted(self.paths) if p.endswith(".go") and str(PurePosixPath(p).parent) == d and not p.endswith("_test.go")), None)
                    if hit:
                        imp.resolved = hit
                        return
            imp.external = "." in imp.module.split("/")[0]
            imp.package = imp.module if imp.external else None
        elif language in {"Java", "Kotlin"}:
            if imp.module in self.java_index:
                imp.resolved = self.java_index[imp.module]
            else:
                parts = imp.module.split(".")
                imp.external = not any(k.startswith(".".join(parts[:2])) for k in self.java_index)
                imp.package = ".".join(parts[:3]) if imp.external else None
        elif language in {"C", "C++"}:
            cand = [p for p in self.paths if p.endswith("/" + imp.module) or p == imp.module]
            if cand:
                imp.resolved = sorted(cand, key=len)[0]
            else:
                imp.external = True
                imp.package = imp.module
        elif language == "Ruby":
            base = str(PurePosixPath(imp.file).parent)
            for c in (f"{base}/{imp.module}.rb", f"{imp.module}.rb", f"lib/{imp.module}.rb", f"app/{imp.module}.rb"):
                c = str(PurePosixPath(c))
                if c in self.paths:
                    imp.resolved = c
                    return
            imp.external, imp.package = True, imp.module.split("/")[0]
        elif language == "Rust":
            first = imp.module.split("::")[0]
            if first in {"crate", "super", "self"}:
                imp.resolved = None
            else:
                imp.external = first not in {"std", "core", "alloc"}
                imp.package = first if imp.external else None

    def _best(self, candidates: list[str], importer: str) -> str:
        imp_parts = importer.split("/")

        def score(p: str) -> int:
            parts = p.split("/")
            n = 0
            for a, b in zip(parts, imp_parts, strict=False):
                if a != b:
                    break
                n += 1
            return n

        return sorted(candidates, key=lambda p: (-score(p), len(p)))[0]

    def _py_lookup(self, dotted: str, importer: str) -> str | None:
        if dotted in self.py_index:
            return self._best(self.py_index[dotted], importer)
        suffix = "." + dotted
        cands = [p for k, ps in self.py_index.items() if k.endswith(suffix) for p in ps]
        if cands:
            return self._best(cands, importer)
        return None

    def _resolve_py(self, imp: ImportRef) -> None:
        rel = imp.module.startswith("/")
        mod = imp.module.lstrip("/")
        # `from pkg import a, b` imports submodules pkg/a.py and pkg/b.py when they exist
        subs: list[str] = []
        if imp.names and imp.names[0] != "*":
            for n in imp.names:
                h = self._py_lookup(f"{mod}.{n}" if mod else n, imp.file)
                if h and h not in subs:
                    subs.append(h)
        hit = subs[0] if subs else (self._py_lookup(mod, imp.file) if mod else None)
        if hit:
            imp.resolved = hit
            imp.also_resolved = subs[1:]
            return
        top = mod.split(".")[0]
        if rel or not top:
            imp.external = False
            return
        imp.external = True
        imp.package = top if top not in STDLIB else None
        if top in STDLIB:
            imp.external = False
            imp.package = None
            imp.names = imp.names  # stdlib: neither internal nor third-party

    def _js_candidates(self, base: str) -> list[str]:
        base = str(PurePosixPath(base))
        out = [base] + [base + e for e in JS_EXTS] + [f"{base}/index{e}" for e in JS_EXTS]
        if base.endswith(".js"):
            out += [base[:-3] + ".ts", base[:-3] + ".tsx"]
        return out

    def _resolve_js(self, imp: ImportRef) -> None:
        spec = imp.module
        if not spec:
            return
        if spec.startswith("."):
            base_dir = PurePosixPath(imp.file).parent
            joined = _normpath(str(base_dir / spec))
            for c in self._js_candidates(joined):
                if c in self.paths:
                    imp.resolved = c
                    return
            return
        for cfg_dir, alias, target in sorted(self.ts_aliases, key=lambda t: -len(t[1])):
            if spec.startswith(alias) and (not cfg_dir or imp.file.startswith(cfg_dir + "/")):
                rest = spec[len(alias) :]
                joined = _normpath(f"{target}{rest}" if target.endswith("/") or not rest else f"{target}/{rest}")
                for c in self._js_candidates(joined):
                    if c in self.paths:
                        imp.resolved = c
                        return
        if spec.startswith(("@/", "~/")):
            rest = spec[2:]
            roots = sorted({p.split("/src/")[0] + "/src" for p in self.paths if "/src/" in p} | {"src", ""})
            for r in roots:
                for c in self._js_candidates(f"{r}/{rest}" if r else rest):
                    if c in self.paths:
                        imp.resolved = c
                        return
            return
        name = spec.removeprefix("node:")
        if name.split("/")[0] in NODE_BUILTINS or spec.startswith("node:"):
            return
        imp.external = True
        parts = name.split("/")
        imp.package = "/".join(parts[:2]) if name.startswith("@") else parts[0]


def _normpath(p: str) -> str:
    out: list[str] = []
    for part in p.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if out:
                out.pop()
            continue
        out.append(part)
    return "/".join(out)


def module_of(path: str) -> str:
    parent = str(PurePosixPath(path).parent)
    return "(root)" if parent == "." else parent


def build_graph(modules: list[ModuleInfo], files: list[FileRecord]) -> DependencyGraph:
    file_map = {f.path: f for f in files}
    g = DependencyGraph()
    internal_paths = {m.path for m in modules}
    for m in modules:
        rec = file_map.get(m.path)
        g.nodes.append(GraphNode(
            id=m.path, label=PurePosixPath(m.path).name, type="file", group=module_of(m.path),
            data={"language": m.language, "roles": m.roles, "symbols": len(m.symbols), "lines": rec.lines if rec else 0,
                  "entry_point": bool(rec and rec.is_entry_point), "category": rec.category.value if rec else None},
        ))
    externals: dict[str, int] = defaultdict(int)
    edge_weights: dict[tuple[str, str, str], int] = defaultdict(int)
    for m in modules:
        for imp in m.imports:
            for target in ([imp.resolved] if imp.resolved else []) + imp.also_resolved:
                if target in internal_paths and target != m.path:
                    edge_weights[(m.path, target, "imports")] += 1
            if not imp.resolved and imp.external and imp.package:
                externals[imp.package] += 1
                edge_weights[(m.path, f"pkg:{imp.package}", "depends_on")] += 1
    for (s, t, typ), w in edge_weights.items():
        g.edges.append(GraphEdge(source=s, target=t, type=typ, weight=w))
    for pkg, count in sorted(externals.items(), key=lambda kv: -kv[1]):
        g.nodes.append(GraphNode(id=f"pkg:{pkg}", label=pkg, type="external", group="external", data={"importers": count}))

    # module-level aggregation
    mod_files: dict[str, list[str]] = defaultdict(list)
    for m in modules:
        mod_files[module_of(m.path)].append(m.path)
    for mod, paths in sorted(mod_files.items()):
        roles: dict[str, int] = defaultdict(int)
        for p in paths:
            for r in next((x.roles for x in modules if x.path == p), []):
                roles[r] += 1
        g.module_nodes.append(GraphNode(id=mod, label=mod, type="module", data={"files": len(paths), "roles": dict(roles)}))
    mweights: dict[tuple[str, str], int] = defaultdict(int)
    for e in g.edges:
        if e.type == "imports":
            a, b = module_of(e.source), module_of(e.target)
            if a != b:
                mweights[(a, b)] += e.weight
    g.module_edges = [GraphEdge(source=a, target=b, type="imports", weight=w) for (a, b), w in mweights.items()]
    g.cycles = find_cycles({p: [e.target for e in g.edges if e.source == p and e.type == "imports"] for p in internal_paths})
    return g


def find_cycles(adj: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan's SCC (iterative); returns components with more than one node."""
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    result: list[list[str]] = []
    counter = 0
    for start in sorted(adj):
        if start in index:
            continue
        work: list[tuple[str, int]] = [(start, 0)]
        while work:
            node, i = work.pop()
            if i == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            recurse = False
            nbrs = adj.get(node, [])
            for j in range(i, len(nbrs)):
                w = nbrs[j]
                if w not in index:
                    work.append((node, j + 1))
                    work.append((w, 0))
                    recurse = True
                    break
                if w in on_stack:
                    low[node] = min(low[node], index[w])
            if recurse:
                continue
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                if len(comp) > 1:
                    result.append(sorted(comp))
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return result
