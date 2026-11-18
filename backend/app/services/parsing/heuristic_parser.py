"""Regex-based extraction for languages without a bundled AST parser.

Results are labelled ``heuristic-<lang>`` so downstream documents can state the
limitation explicitly.
"""

from __future__ import annotations

import re

from app.schemas.facts import ClientCall, DbField, DbModel, DbOperation, ImportRef, ModuleInfo, Route, Symbol
from app.services.parsing.base import SQL_RE, ParseResult, join_paths

LangSpec = dict[str, list[tuple[str, re.Pattern[str]]]]

SPECS: dict[str, dict[str, object]] = {
    "Go": {
        "symbols": [
            ("function", re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)\s*(\([^)]*\)[^{]*)", re.M)),
            ("class", re.compile(r"^type\s+([A-Za-z_]\w*)\s+struct\b", re.M)),
            ("interface", re.compile(r"^type\s+([A-Za-z_]\w*)\s+interface\b", re.M)),
            ("type", re.compile(r"^type\s+([A-Za-z_]\w*)\s+(?!struct|interface)\w", re.M)),
            ("constant", re.compile(r"^const\s+([A-Za-z_]\w*)", re.M)),
        ],
        "imports": [re.compile(r'^\s*(?:import\s+)?(?:\w+\s+)?"([^"]+)"', re.M)],
        "exported": lambda n: n[:1].isupper(),
    },
    "Java": {
        "symbols": [
            ("class", re.compile(r"^\s*(?:public|protected|private|abstract|final|static|\s)*\s*(?:class|record)\s+([A-Z]\w*)", re.M)),
            ("interface", re.compile(r"^\s*(?:public\s+)?(?:@)?interface\s+([A-Z]\w*)", re.M)),
            ("enum", re.compile(r"^\s*(?:public\s+)?enum\s+([A-Z]\w*)", re.M)),
            ("method", re.compile(r"^\s+(?:public|protected|private)\s+(?:static\s+)?(?:final\s+)?(?:synchronized\s+)?[\w<>\[\],\s?]+\s+([a-z]\w*)\s*(\([^)]*\))", re.M)),
        ],
        "imports": [re.compile(r"^import\s+(?:static\s+)?([\w.]+)\s*;", re.M)],
        "exported": lambda n: True,
    },
    "Kotlin": {
        "symbols": [
            ("class", re.compile(r"^\s*(?:data\s+|sealed\s+|open\s+|abstract\s+|enum\s+)?class\s+([A-Z]\w*)", re.M)),
            ("interface", re.compile(r"^\s*interface\s+([A-Z]\w*)", re.M)),
            ("function", re.compile(r"^\s*(?:suspend\s+|private\s+|public\s+|internal\s+|override\s+)*fun\s+(?:<[^>]*>\s*)?([a-zA-Z_]\w*)\s*(\([^)]*\))", re.M)),
            ("class", re.compile(r"^\s*object\s+([A-Z]\w*)", re.M)),
        ],
        "imports": [re.compile(r"^import\s+([\w.]+)", re.M)],
        "exported": lambda n: True,
    },
    "C#": {
        "symbols": [
            ("class", re.compile(r"^\s*(?:public|internal|private|protected|static|sealed|abstract|partial|\s)*\s*(?:class|record|struct)\s+([A-Z]\w*)", re.M)),
            ("interface", re.compile(r"^\s*(?:public\s+)?interface\s+(I[A-Z]\w*)", re.M)),
            ("enum", re.compile(r"^\s*(?:public\s+)?enum\s+([A-Z]\w*)", re.M)),
            ("method", re.compile(r"^\s+(?:public|protected|private|internal)\s+(?:static\s+|async\s+|virtual\s+|override\s+)*[\w<>\[\],\s?]+\s+([A-Z]\w*)\s*(\([^)]*\))", re.M)),
        ],
        "imports": [re.compile(r"^using\s+([\w.]+)\s*;", re.M)],
        "exported": lambda n: True,
    },
    "Rust": {
        "symbols": [
            ("function", re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+([a-z_]\w*)\s*(?:<[^>]*>)?\s*(\([^)]*\))", re.M)),
            ("class", re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Z]\w*)", re.M)),
            ("enum", re.compile(r"^\s*(?:pub\s+)?enum\s+([A-Z]\w*)", re.M)),
            ("interface", re.compile(r"^\s*(?:pub\s+)?trait\s+([A-Z]\w*)", re.M)),
            ("module", re.compile(r"^\s*(?:pub\s+)?mod\s+([a-z_]\w*)", re.M)),
        ],
        "imports": [re.compile(r"^\s*use\s+([\w:]+)", re.M)],
        "exported": lambda n: True,
    },
    "PHP": {
        "symbols": [
            ("class", re.compile(r"^\s*(?:abstract\s+|final\s+)?class\s+([A-Z]\w*)", re.M)),
            ("interface", re.compile(r"^\s*interface\s+([A-Z]\w*)", re.M)),
            ("function", re.compile(r"^\s*(?:public\s+|private\s+|protected\s+|static\s+)*function\s+([a-zA-Z_]\w*)\s*(\([^)]*\))", re.M)),
        ],
        "imports": [re.compile(r"^use\s+([\w\\]+)", re.M), re.compile(r"(?:require|include)(?:_once)?\s*\(?\s*['\"]([^'\"]+)['\"]", re.M)],
        "exported": lambda n: True,
    },
    "Ruby": {
        "symbols": [
            ("class", re.compile(r"^\s*class\s+([A-Z][\w:]*)", re.M)),
            ("module", re.compile(r"^\s*module\s+([A-Z][\w:]*)", re.M)),
            ("method", re.compile(r"^\s*def\s+((?:self\.)?[a-z_]\w*[?!=]?)\s*(\([^)]*\))?", re.M)),
        ],
        "imports": [re.compile(r"^\s*require(?:_relative)?\s+['\"]([^'\"]+)['\"]", re.M)],
        "exported": lambda n: not n.startswith("_"),
    },
    "Swift": {
        "symbols": [
            ("class", re.compile(r"^\s*(?:public\s+|final\s+|open\s+)*(?:class|struct|actor)\s+([A-Z]\w*)", re.M)),
            ("interface", re.compile(r"^\s*(?:public\s+)?protocol\s+([A-Z]\w*)", re.M)),
            ("enum", re.compile(r"^\s*(?:public\s+)?enum\s+([A-Z]\w*)", re.M)),
            ("function", re.compile(r"^\s*(?:public\s+|private\s+|static\s+|override\s+|@\w+\s+)*func\s+([a-zA-Z_]\w*)\s*(\([^)]*\))", re.M)),
        ],
        "imports": [re.compile(r"^import\s+(\w+)", re.M)],
        "exported": lambda n: True,
    },
    "Dart": {
        "symbols": [
            ("class", re.compile(r"^\s*(?:abstract\s+)?class\s+([A-Z]\w*)", re.M)),
            ("enum", re.compile(r"^\s*enum\s+([A-Z]\w*)", re.M)),
            ("function", re.compile(r"^\s*(?:Future<[^>]*>|void|[A-Z]\w*(?:<[^>]*>)?|int|String|bool|double)\s+([a-z_]\w*)\s*(\([^)]*\))\s*(?:async\s*)?\{", re.M)),
        ],
        "imports": [re.compile(r"^import\s+['\"]([^'\"]+)['\"]", re.M)],
        "exported": lambda n: not n.startswith("_"),
    },
    "C": {
        "symbols": [
            ("function", re.compile(r"^(?:static\s+|inline\s+|extern\s+)*[\w\*\s]+?\b([a-zA-Z_]\w*)\s*(\([^;{)]*\))\s*\{", re.M)),
            ("class", re.compile(r"^(?:typedef\s+)?struct\s+([a-zA-Z_]\w*)", re.M)),
        ],
        "imports": [re.compile(r'^#include\s+[<"]([^>"]+)[>"]', re.M)],
        "exported": lambda n: True,
    },
    "C++": {
        "symbols": [
            ("class", re.compile(r"^\s*(?:class|struct)\s+([A-Za-z_]\w*)\s*(?::[^{]*)?\{", re.M)),
            ("function", re.compile(r"^(?:[\w:<>\*&\s]+?)\b([A-Za-z_][\w:]*)\s*(\([^;{)]*\))\s*(?:const\s*)?\{", re.M)),
            ("module", re.compile(r"^namespace\s+(\w+)", re.M)),
        ],
        "imports": [re.compile(r'^#include\s+[<"]([^>"]+)[>"]', re.M)],
        "exported": lambda n: True,
    },
    "Shell": {
        "symbols": [("function", re.compile(r"^\s*(?:function\s+)?([a-zA-Z_][\w\-]*)\s*\(\)\s*\{", re.M))],
        "imports": [re.compile(r"^\s*(?:source|\.)\s+(\S+)", re.M)],
        "exported": lambda n: True,
    },
    "Vue": {"symbols": [], "imports": [re.compile(r"^\s*import\s+.*?from\s+['\"]([^'\"]+)['\"]", re.M)], "exported": lambda n: True},
    "Svelte": {"symbols": [], "imports": [re.compile(r"^\s*import\s+.*?from\s+['\"]([^'\"]+)['\"]", re.M)], "exported": lambda n: True},
}

_KEYWORDS = {"if", "for", "while", "switch", "return", "catch", "sizeof", "else", "new", "delete", "main_loop"}

ROUTE_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("Go", "Gin/Echo/Fiber/chi", re.compile(r"\b(\w+)\.(GET|POST|PUT|DELETE|PATCH|Get|Post|Put|Delete|Patch|Handle|HandleFunc)\s*\(\s*\"([^\"]+)\"\s*,\s*([\w.]+)?")),
    ("Go", "net/http", re.compile(r"http\.(HandleFunc|Handle)\s*\(\s*\"([^\"]+)\"\s*,\s*([\w.]+)")),
    ("Java", "Spring", re.compile(r"@(Get|Post|Put|Delete|Patch|Request)Mapping\s*\(\s*(?:value\s*=\s*|path\s*=\s*)?\"?([^\")]*)\"?")),
    ("Kotlin", "Spring/Ktor", re.compile(r"@(Get|Post|Put|Delete|Patch|Request)Mapping\s*\(\s*(?:value\s*=\s*|path\s*=\s*)?\"?([^\")]*)\"?|\b(get|post|put|delete|patch)\s*\(\s*\"([^\"]+)\"\s*\)\s*\{")),
    ("C#", "ASP.NET", re.compile(r"\[(Http(Get|Post|Put|Delete|Patch))(?:\(\"([^\"]*)\"\))?\]|\.Map(Get|Post|Put|Delete|Patch)\(\s*\"([^\"]+)\"")),
    ("PHP", "Laravel/Slim", re.compile(r"(?:Route::|\$app->|\$router->)(get|post|put|delete|patch|any)\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*([^)]+)\)")),
    ("Ruby", "Rails/Sinatra", re.compile(r"^\s*(get|post|put|patch|delete)\s+['\"]([^'\"]+)['\"](?:\s*(?:,|=>)\s*(?:to:\s*)?['\"]?([\w#/]+))?", re.M)),
    ("Rust", "Actix/Rocket", re.compile(r"#\[(get|post|put|delete|patch)\(\s*\"([^\"]+)\"")),
    ("Rust", "Axum", re.compile(r"\.route\(\s*\"([^\"]+)\"\s*,\s*(get|post|put|delete|patch)\(([\w:]+)\)")),
]


def _line(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _block_end(lines: list[str], start: int) -> int:
    """Approximate end line of a brace/indent block starting at ``start`` (1-based)."""
    depth = 0
    seen = False
    for i in range(start - 1, min(len(lines), start + 1500)):
        ln = lines[i]
        depth += ln.count("{") - ln.count("}")
        if "{" in ln:
            seen = True
        if seen and depth <= 0:
            return i + 1
    return start


def parse_heuristic(path: str, text: str, language: str) -> ParseResult:
    mod = ModuleInfo(path=path, language=language, parser=f"heuristic-{language.lower()}")
    res = ParseResult(module=mod)
    spec = SPECS.get(language)
    lines = text.splitlines()
    if spec:
        exported = spec["exported"]
        current_class: str | None = None
        class_end = 0
        found: list[tuple[int, str, str, str | None]] = []
        for kind, pat in spec["symbols"]:  # type: ignore[attr-defined]
            for m in pat.finditer(text):
                name = m.group(1)
                if name in _KEYWORDS:
                    continue
                sig = m.group(2) if m.lastindex and m.lastindex >= 2 else None
                found.append((_line(text, m.start()), kind, name, sig))
        found.sort()
        seen: set[tuple[int, str]] = set()
        for line, kind, name, sig in found:
            if (line, name) in seen:
                continue
            seen.add((line, name))
            end = _block_end(lines, line) if language not in {"Ruby", "Shell"} else line
            parent = None
            if kind in {"class", "interface", "enum"}:
                current_class, class_end = name, end
            elif current_class and line <= class_end:
                parent = current_class
                if kind == "function":
                    kind = "method"
            body = "\n".join(lines[line - 1 : end])
            calls = list(dict.fromkeys(re.findall(r"\b([A-Za-z_][\w.]*)\s*\(", body)))[:30] if kind in {"function", "method"} else []
            mod.symbols.append(Symbol(name=name, kind=kind, file=path, line_start=line, line_end=max(end, line), parent=parent,
                                      signature=(f"{name}{sig}" if sig else name)[:200], exported=bool(exported(name)),  # type: ignore[operator]
                                      calls=[c for c in calls if c not in _KEYWORDS and c != name]))
        for pat in spec["imports"]:  # type: ignore[attr-defined]
            for m in pat.finditer(text):
                mod.imports.append(ImportRef(file=path, module=m.group(1), line=_line(text, m.start())))

    # Routes
    class_prefix = ""
    if language in {"Java", "Kotlin"}:
        m = re.search(r"@RequestMapping\s*\(\s*(?:value\s*=\s*|path\s*=\s*)?\"([^\"]*)\"\s*\)\s*(?:@\w+(?:\([^)]*\))?\s*)*(?:public\s+)?class", text)
        if m:
            class_prefix = m.group(1)
    if language == "C#":
        m = re.search(r"\[Route\(\"([^\"]+)\"\)\]", text)
        if m:
            class_prefix = m.group(1)
    for lang, fw, pat in ROUTE_PATTERNS:
        if lang != language:
            continue
        for m in pat.finditer(text):
            line = _line(text, m.start())
            g = [x for x in m.groups()]
            method, rpath, handler = "ANY", "", None
            if lang == "Go" and fw == "net/http":
                method, rpath, handler = "ANY", g[1], g[2]
            elif lang == "Go":
                method = "ANY" if g[1] in {"Handle", "HandleFunc"} else g[1].upper()
                rpath, handler = g[2], g[3]
            elif lang in {"Java", "Kotlin"}:
                if g[0]:
                    method = "ANY" if g[0] == "Request" else g[0].upper()
                    rpath = join_paths(class_prefix, g[1] or "")
                    if g[0] == "Request" and m.start() < text.find("class "):
                        continue  # class-level mapping
                    nxt = re.search(r"\s(\w+)\s*\(", text[m.end() : m.end() + 400])
                    handler = nxt.group(1) if nxt else None
                elif len(g) > 3 and g[2]:
                    method, rpath = g[2].upper(), g[3]
                else:
                    continue
            elif lang == "C#":
                if g[0]:
                    method, rpath = g[1].upper(), join_paths(class_prefix.replace("[controller]", re.sub(r"Controller$", "", next((s.name for s in mod.symbols if s.kind == "class"), "")).lower()), g[2] or "")
                    nxt = re.search(r"\s(\w+)\s*\(", text[m.end() : m.end() + 400])
                    handler = nxt.group(1) if nxt else None
                else:
                    method, rpath = g[3].upper(), g[4]
            elif lang == "PHP":
                method, rpath, handler = g[0].upper(), g[1], g[2].strip()[:80]
            elif lang == "Ruby":
                method, rpath, handler = g[0].upper(), g[1], g[2]
            elif lang == "Rust" and fw == "Actix/Rocket":
                method, rpath = g[0].upper(), g[1]
                nxt = re.search(r"fn\s+(\w+)", text[m.end() : m.end() + 300])
                handler = nxt.group(1) if nxt else None
            elif lang == "Rust":
                rpath, method, handler = g[0], g[1].upper(), g[2]
            if not rpath.startswith("/") and lang not in {"Ruby"}:
                rpath = "/" + rpath
            res.routes.append(Route(method=method.replace("ANY", "ANY"), path=rpath, handler=handler, file=path, line=line, framework=fw, resolved_prefix=True))

    # JPA entities
    if language in {"Java", "Kotlin"} and "@Entity" in text:
        cm = re.search(r"@Entity[\s\S]*?class\s+(\w+)", text)
        tm = re.search(r"@Table\s*\(\s*name\s*=\s*\"(\w+)\"", text)
        if cm:
            fields: list[DbField] = []
            rels: list[dict[str, object]] = []
            for fm in re.finditer(r"((?:@\w+(?:\([^)]*\))?\s*)+)\s*(?:private|protected|public)?\s*(?:val|var)?\s*([\w<>]+)\s+(\w+)\s*[;=]", text):
                annos = fm.group(1)
                ln = _line(text, fm.start())
                if re.search(r"@(OneToMany|ManyToOne|OneToOne|ManyToMany)", annos):
                    kind = re.search(r"@(OneToMany|ManyToOne|OneToOne|ManyToMany)", annos).group(1)  # type: ignore[union-attr]
                    rels.append({"name": fm.group(3), "target": re.sub(r".*<(\w+)>", r"\1", fm.group(2)), "kind": kind, "line": ln})
                elif "@Column" in annos or "@Id" in annos:
                    fields.append(DbField(name=fm.group(3), type=fm.group(2), primary_key="@Id" in annos, unique="unique = true" in annos,
                                          nullable=False if "nullable = false" in annos else None, line=ln))
            res.db_models.append(DbModel(name=cm.group(1), table=tm.group(1) if tm else None, orm="JPA/Hibernate", file=path, line=_line(text, cm.start()), fields=fields, relationships=rels))
    # GORM models
    if language == "Go" and "gorm" in text:
        for sm in re.finditer(r"type\s+(\w+)\s+struct\s*\{([^}]*)\}", text):
            body = sm.group(2)
            if "gorm" not in body and "gorm.Model" not in body:
                continue
            fields = [DbField(name=fm.group(1), type=fm.group(2), primary_key="primaryKey" in (fm.group(3) or ""), line=_line(text, sm.start()))
                      for fm in re.finditer(r"^\s*(\w+)\s+([\w.*\[\]]+)\s*(`[^`]*`)?", body, re.M)]
            res.db_models.append(DbModel(name=sm.group(1), orm="GORM", file=path, line=_line(text, sm.start()), fields=fields))
    # Rails ActiveRecord
    if language == "Ruby" and re.search(r"<\s*(ApplicationRecord|ActiveRecord::Base)", text):
        cm = re.search(r"class\s+(\w+)\s*<", text)
        if cm:
            rels = [{"name": m.group(2), "target": m.group(2), "kind": m.group(1), "line": _line(text, m.start())}
                    for m in re.finditer(r"^\s*(has_many|belongs_to|has_one|has_and_belongs_to_many)\s+:(\w+)", text, re.M)]
            res.db_models.append(DbModel(name=cm.group(1), orm="ActiveRecord", file=path, line=_line(text, cm.start()), relationships=rels))

    # Env vars
    for pat in (r"os\.Getenv\(\"([A-Z_][A-Z0-9_]*)\"\)", r"System\.getenv\(\"([A-Z_][A-Z0-9_]*)\"\)", r"env::var\(\"([A-Z_][A-Z0-9_]*)\"\)",
                r"ENV\[['\"]([A-Z_][A-Z0-9_]*)['\"]\]", r"getenv\(['\"]([A-Z_][A-Z0-9_]*)['\"]\)", r"\$\{([A-Z_][A-Z0-9_]*)(?::[^}]*)?\}",
                r"Environment\.GetEnvironmentVariable\(\"([A-Z_][A-Z0-9_]*)\"\)", r"\$_ENV\[['\"]([A-Z_][A-Z0-9_]*)['\"]\]"):
        for m in re.finditer(pat, text):
            mod.env_vars.append((m.group(1), _line(text, m.start())))
    # SQL strings and raw queries
    for m in re.finditer(r"[\"'`]((?:SELECT|INSERT INTO|UPDATE|DELETE FROM)\b[^\"'`]{8,})[\"'`]", text, re.I):
        mod.string_literals_sql.append((m.group(1)[:200], _line(text, m.start())))
        res.db_operations.append(DbOperation(file=path, line=_line(text, m.start()), operation="raw_sql", snippet=m.group(1)[:200], raw_sql=True))
    # HTTP client calls
    for m in re.finditer(r"(?:http\.(Get|Post)|HttpClient\(\)\.(?:get|post)|\.(GetAsync|PostAsync|PutAsync|DeleteAsync))\s*\(\s*\"([^\"]+)\"", text):
        method = (m.group(1) or m.group(2) or "GET").replace("Async", "").upper()
        res.client_calls.append(ClientCall(file=path, line=_line(text, m.start()), method=method, url=m.group(3)))
    if res.routes:
        mod.roles.append("api-routes")
    if res.db_models:
        mod.roles.append("data-model")
    low = path.lower()
    for key, role in (("service", "service"), ("controller", "controller"), ("middleware", "middleware"), ("auth", "auth"),
                      ("repositor", "repository"), ("model", "data-model"), ("util", "utility"), ("handler", "controller"), ("config", "config")):
        if key in low:
            mod.roles.append(role)
    mod.roles = sorted(set(mod.roles))
    mod.exports = [s.name for s in mod.symbols if s.exported and s.parent is None][:200]
    return res


# ---------------------------------------------------------------- Prisma
def parse_prisma(path: str, text: str) -> ParseResult:
    mod = ModuleInfo(path=path, language="Prisma", parser="prisma-schema")
    res = ParseResult(module=mod)
    scalar = {"String", "Int", "BigInt", "Float", "Decimal", "Boolean", "DateTime", "Json", "Bytes", "Unsupported"}
    for m in re.finditer(r"^(model|enum)\s+(\w+)\s*\{([^}]*)\}", text, re.M):
        kind, name, body = m.group(1), m.group(2), m.group(3)
        line = _line(text, m.start())
        mod.symbols.append(Symbol(name=name, kind="class" if kind == "model" else "enum", file=path, line_start=line, line_end=_line(text, m.end()), exported=True))
        if kind != "model":
            continue
        fields: list[DbField] = []
        rels: list[dict[str, object]] = []
        idx: list[str] = []
        table = None
        for i, fl in enumerate(body.splitlines()):
            s = fl.strip()
            fline = line + i
            if not s or s.startswith("//"):
                continue
            if s.startswith("@@"):
                if mm := re.match(r"@@map\(\"(\w+)\"\)", s):
                    table = mm.group(1)
                if mm := re.match(r"@@(index|unique)\(\[([^\]]+)\]", s):
                    idx.append(f"{mm.group(1)}({mm.group(2)})")
                continue
            parts = s.split()
            if len(parts) < 2:
                continue
            fname, ftype = parts[0], parts[1]
            base_type = ftype.rstrip("?[]")
            attrs = " ".join(parts[2:])
            if base_type not in scalar and base_type[:1].isupper() and ("@relation" in attrs or ftype.endswith("[]") or True):
                if base_type in scalar:
                    pass
                else:
                    fk = re.search(r"fields:\s*\[(\w+)\]\s*,\s*references:\s*\[(\w+)\]", attrs)
                    rels.append({"name": fname, "target": base_type, "kind": "one_to_many" if ftype.endswith("[]") else "many_to_one",
                                 "fields": fk.group(1) if fk else None, "references": fk.group(2) if fk else None, "line": fline})
                    if fk:
                        for f in fields:
                            if f.name == fk.group(1):
                                f.foreign_key = f"{base_type}.{fk.group(2)}"
                    continue
            fields.append(DbField(name=fname, type=ftype, primary_key="@id" in attrs, unique="@unique" in attrs, nullable=ftype.endswith("?"),
                                  default=(re.search(r"@default\(([^)]*\)?)\)", attrs).group(1) if "@default" in attrs else None), line=fline))  # type: ignore[union-attr]
        # second pass: FK fields may be declared after the relation
        for r in rels:
            if r.get("fields"):
                for f in fields:
                    if f.name == r["fields"]:
                        f.foreign_key = f"{r['target']}.{r['references']}"
        res.db_models.append(DbModel(name=name, table=table or name, orm="Prisma", file=path, line=line, fields=fields, relationships=rels, indexes=idx))
    mod.roles = ["data-model", "schema"]
    return res


# ---------------------------------------------------------------- SQL
def parse_sql(path: str, text: str) -> ParseResult:
    mod = ModuleInfo(path=path, language="SQL", parser="sql-ddl")
    res = ParseResult(module=mod)
    for m in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"\[]?(?:\w+\.)?(\w+)[`\"\]]?\s*\((.*?)\)\s*;", text, re.I | re.S):
        name, body = m.group(1), m.group(2)
        line = _line(text, m.start())
        fields: list[DbField] = []
        rels: list[dict[str, object]] = []
        pk_cols: set[str] = set()
        for pkm in re.finditer(r"PRIMARY\s+KEY\s*\(([^)]+)\)", body, re.I):
            pk_cols |= {c.strip(" `\"") for c in pkm.group(1).split(",")}
        offset = 0
        for raw in re.split(r",(?![^()]*\))", body):
            s = raw.strip()
            offset_line = line + body[:body.find(raw)].count("\n") + 1 if raw else line
            offset += 1
            if not s:
                continue
            up = s.upper()
            if up.startswith(("PRIMARY KEY", "CONSTRAINT", "UNIQUE", "INDEX", "KEY", "CHECK")) or up.startswith("FOREIGN KEY"):
                fk = re.search(r"FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+[`\"]?(\w+)[`\"]?\s*\(([^)]+)\)", s, re.I)
                if fk:
                    col = fk.group(1).strip(" `\"")
                    rels.append({"name": col, "target": fk.group(2), "kind": "many_to_one", "line": offset_line})
                    for f in fields:
                        if f.name == col:
                            f.foreign_key = f"{fk.group(2)}.{fk.group(3).strip()}"
                continue
            cm = re.match(r"[`\"\[]?(\w+)[`\"\]]?\s+([\w]+(?:\s*\([^)]*\))?)(.*)", s, re.S)
            if not cm:
                continue
            col, ctype, rest = cm.group(1), cm.group(2), cm.group(3)
            ref = re.search(r"REFERENCES\s+[`\"]?(\w+)[`\"]?\s*\(([^)]+)\)", rest, re.I)
            fields.append(DbField(name=col, type=ctype, primary_key="PRIMARY KEY" in rest.upper() or col in pk_cols,
                                  foreign_key=f"{ref.group(1)}.{ref.group(2).strip()}" if ref else None,
                                  nullable=False if "NOT NULL" in rest.upper() else (None if "PRIMARY KEY" in rest.upper() else True),
                                  unique="UNIQUE" in rest.upper(), default=(re.search(r"DEFAULT\s+([^\s,]+)", rest, re.I).group(1) if re.search(r"DEFAULT\s+", rest, re.I) else None),  # type: ignore[union-attr]
                                  line=offset_line))
            if ref:
                rels.append({"name": col, "target": ref.group(1), "kind": "many_to_one", "line": offset_line})
        res.db_models.append(DbModel(name=name, table=name, orm="SQL DDL", file=path, line=line, fields=fields, relationships=rels))
        mod.symbols.append(Symbol(name=name, kind="table", file=path, line_start=line, line_end=_line(text, m.end()), exported=True))
    for m in re.finditer(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+ON\s+[`\"]?(\w+)[`\"]?\s*\(([^)]+)\)", text, re.I):
        for dbm in res.db_models:
            if dbm.name == m.group(2):
                dbm.indexes.append(f"{m.group(1)}({m.group(3).strip()})")
    for m in re.finditer(r"ALTER\s+TABLE\s+[`\"]?(\w+)[`\"]?\s+ADD\s+(?:CONSTRAINT\s+\w+\s+)?FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+[`\"]?(\w+)", text, re.I):
        for dbm in res.db_models:
            if dbm.name == m.group(1):
                dbm.relationships.append({"name": m.group(2).strip(), "target": m.group(3), "kind": "many_to_one", "line": _line(text, m.start())})
    mod.roles = ["schema"]
    if SQL_RE.search(text):
        pass
    return res
