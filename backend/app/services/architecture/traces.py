"""Static, best-effort execution traces: route handler → internal calls → database operations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from app.schemas.facts import DbOperation, ModuleInfo, Route, Symbol

_BUILTIN_CALLS = {
    "print", "len", "str", "int", "float", "dict", "list", "set", "tuple", "isinstance", "range", "enumerate", "zip", "sorted",
    "map", "filter", "any", "all", "min", "max", "sum", "open", "super", "getattr", "setattr", "hasattr", "type", "repr",
    "console.log", "JSON.stringify", "JSON.parse", "Object.keys", "Object.entries", "Array.isArray", "Promise.all", "parseInt",
    "res.json", "res.status", "res.send", "setState", "useState", "useEffect", "require", "next",
}


@dataclass
class TraceNode:
    name: str
    file: str | None
    line_start: int | None
    line_end: int | None
    resolved: bool
    db_ops: list[DbOperation] = field(default_factory=list)
    children: list[TraceNode] = field(default_factory=list)


class CallResolver:
    def __init__(self, modules: list[ModuleInfo], db_ops: list[DbOperation]) -> None:
        self.by_name: dict[str, list[Symbol]] = defaultdict(list)
        self.imports_of: dict[str, set[str]] = defaultdict(set)
        for m in modules:
            for s in m.symbols:
                if s.kind in ("function", "method", "component", "hook"):
                    self.by_name[s.name].append(s)
            for imp in m.imports:
                if imp.resolved:
                    self.imports_of[m.path].add(imp.resolved)
                self.imports_of[m.path].update(imp.also_resolved)
        self.ops_by_file: dict[str, list[DbOperation]] = defaultdict(list)
        for o in db_ops:
            self.ops_by_file[o.file].append(o)
        self.sym_index = {(s.file, s.name): s for ss in self.by_name.values() for s in ss}

    def resolve(self, call: str, from_file: str) -> Symbol | None:
        name = call.rstrip("()").split("(")[0].split(".")[-1]
        if not name or call in _BUILTIN_CALLS or name in _BUILTIN_CALLS:
            return None
        cands = self.by_name.get(name, [])
        if not cands:
            return None
        same = [c for c in cands if c.file == from_file]
        if same:
            return same[0]
        imported = [c for c in cands if c.file in self.imports_of.get(from_file, set())]
        if imported:
            return imported[0]
        return cands[0] if len(cands) == 1 else None

    def ops_in(self, s: Symbol) -> list[DbOperation]:
        return [o for o in self.ops_by_file.get(s.file, []) if s.line_start <= o.line <= s.line_end]

    def trace_symbol(self, s: Symbol, depth: int = 3, seen: set[tuple[str, str]] | None = None) -> TraceNode:
        seen = seen or set()
        seen.add((s.file, s.name))
        node = TraceNode(name=f"{s.parent + '.' if s.parent else ''}{s.name}", file=s.file, line_start=s.line_start, line_end=s.line_end,
                         resolved=True, db_ops=self.ops_in(s))
        if depth <= 0:
            return node
        for c in s.calls[:20]:
            tgt = self.resolve(c, s.file)
            if tgt is None or (tgt.file, tgt.name) in seen:
                continue
            node.children.append(self.trace_symbol(tgt, depth - 1, seen))
        return node

    def trace_route(self, r: Route, depth: int = 3) -> TraceNode | None:
        if not r.handler:
            return None
        hname = r.handler.split(".")[-1]
        s = self.sym_index.get((r.file, hname))
        if s is None:
            if r.calls:
                node = TraceNode(name=r.handler, file=r.file, line_start=r.line, line_end=None, resolved=False,
                                 db_ops=[o for o in self.ops_by_file.get(r.file, []) if abs(o.line - r.line) < 40])
                for c in r.calls[:15]:
                    tgt = self.resolve(c, r.file)
                    if tgt is not None:
                        node.children.append(self.trace_symbol(tgt, depth - 1))
                return node
            return None
        return self.trace_symbol(s, depth)


def render_trace(node: TraceNode, indent: int = 0) -> list[str]:
    loc = f"`{node.file}:{node.line_start}-{node.line_end}`" if node.file and node.line_end else (f"`{node.file}:{node.line_start}`" if node.file else "")
    lines = [f"{'  ' * indent}- `{node.name}` {loc}"]
    for o in node.db_ops[:6]:
        tgt = f" → {o.target}" if o.target else ""
        lines.append(f"{'  ' * (indent + 1)}- 🗄 DB {o.operation}{tgt} `{o.file}:{o.line}`" + (" (raw SQL)" if o.raw_sql else ""))
    for ch in node.children[:10]:
        lines.extend(render_trace(ch, indent + 1))
    return lines


def count_callers(modules: list[ModuleInfo]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for m in modules:
        for s in m.symbols:
            for c in s.calls:
                counts[c.rstrip("()").split(".")[-1]] += 1
    return counts
