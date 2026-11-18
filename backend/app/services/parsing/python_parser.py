"""Python structural extraction using the standard-library ``ast`` module."""

from __future__ import annotations

import ast
import re

from app.schemas.facts import ClientCall, DbField, DbModel, DbOperation, ImportRef, ModuleInfo, Route, Symbol
from app.services.parsing.base import HTTP_METHODS, SQL_RE, ParseResult, RouterMount

_ORM_BASES = {"Base", "DeclarativeBase", "Model", "db.Model", "models.Model", "SQLModel", "Document", "BaseModel_ORM"}
_DB_OP_ATTRS = {
    "query": "orm_query", "execute": "raw_sql", "executemany": "raw_sql", "add": "insert", "add_all": "insert",
    "commit": "transaction", "rollback": "transaction", "delete": "delete", "merge": "update", "flush": "transaction",
    "filter": "select", "filter_by": "select", "scalars": "select", "scalar": "select", "get": None,
    "insert_one": "insert", "insert_many": "insert", "find": "select", "find_one": "select", "update_one": "update",
    "update_many": "update", "delete_one": "delete", "delete_many": "delete", "aggregate": "select", "bulk_create": "insert",
    "create": None, "save": "update", "refresh": "select",
}
_DB_RECEIVERS = re.compile(r"^(db|session|sess|conn|connection|cursor|cur|engine|self\.db|self\.session|db_session|async_session|tx|collection|.*_collection|.*objects|.*repo)$", re.I)
_HTTP_CLIENTS = re.compile(r"^(requests|httpx|client|session|self\.client|http|aiohttp\.ClientSession\(\)|.*_client)$")
_NON_BODY_TYPES = {"Optional", "List", "Dict", "Any", "Request", "Response", "BackgroundTasks", "UploadFile", "Session", "AsyncSession", "WebSocket", "HTTPConnection"}
_AUTH_HINT = re.compile(r"(auth|user|token|login|permission|jwt|oauth|session|admin|scope|role|verify|api_key)", re.I)


def _name(node: ast.AST | None) -> str:
    if node is None:
        return ""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return _name(node.func) + "()"
    if isinstance(node, ast.Subscript):
        return _name(node.value)
    if isinstance(node, ast.Constant):
        return repr(node.value)
    return ast.unparse(node) if hasattr(ast, "unparse") else ""


def _ann(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)[:120]
    except Exception:
        return _name(node)


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            else:
                parts.append("{" + (_name(getattr(v, "value", None)) or "x") + "}")
        return "".join(parts)
    return None


def _kw(call: ast.Call, name: str) -> ast.AST | None:
    for k in call.keywords:
        if k.arg == name:
            return k.value
    return None


def _annotated_dependency(node: ast.AST | None) -> str | None:
    """``Annotated[T, Depends(fn)]`` / ``Security(fn)`` -> ``fn`` (FastAPI dependency aliases)."""
    if isinstance(node, ast.Subscript) and _name(node.value).endswith("Annotated") and isinstance(node.slice, ast.Tuple):
        for meta in node.slice.elts[1:]:
            if isinstance(meta, ast.Call) and _name(meta.func).split(".")[-1] in {"Depends", "Security"}:
                return _name(meta.args[0]) if meta.args else _name(node.slice.elts[0])
    return None


def _signature(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    try:
        args = ast.unparse(fn.args)
    except Exception:
        args = "..."
    ret = ""
    if fn.returns is not None:
        try:
            ret = " -> " + ast.unparse(fn.returns)
        except Exception:
            ret = ""
    prefix = "async def" if isinstance(fn, ast.AsyncFunctionDef) else "def"
    return f"{prefix} {fn.name}({args}){ret}"[:300]


class _BodyScan(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.raises: list[str] = []
        self.handles = False
        self.status_codes: list[int] = []

    def visit_Call(self, node: ast.Call) -> None:
        n = _name(node.func)
        if n and n not in self.calls and len(self.calls) < 60:
            self.calls.append(n)
        if n.endswith("HTTPException") or n.endswith("abort"):
            sc = _kw(node, "status_code") or (node.args[0] if node.args else None)
            if isinstance(sc, ast.Constant) and isinstance(sc.value, int):
                self.status_codes.append(sc.value)
            elif sc is not None:
                m = re.search(r"(\d{3})", _name(sc))
                if m:
                    self.status_codes.append(int(m.group(1)))
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        if node.exc is not None:
            n = _name(node.exc.func if isinstance(node.exc, ast.Call) else node.exc)
            if n and n not in self.raises:
                self.raises.append(n)
                if isinstance(node.exc, ast.Call) and n.endswith("HTTPException"):
                    sc = _kw(node.exc, "status_code") or (node.exc.args[0] if node.exc.args else None)
                    if isinstance(sc, ast.Constant) and isinstance(sc.value, int):
                        self.status_codes.append(sc.value)
                    elif sc is not None and (m := re.search(r"(\d{3})", _name(sc))):
                        self.status_codes.append(int(m.group(1)))
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        self.handles = True
        self.generic_visit(node)

    # don't descend into nested function definitions' bodies twice
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return


def _scan_body(fn: ast.AST) -> _BodyScan:
    s = _BodyScan()
    for stmt in getattr(fn, "body", []):
        s.visit(stmt)
    return s


_UNPAREN_EXCEPT = re.compile(r"^(\s*except\*?\s+)(?!\()([\w.]+(?:\s*,\s*[\w.]+)+)(\s*(?:as\s+\w+\s*)?:)", re.M)


def compat_source(text: str) -> str | None:
    """Rewrite syntax newer than the analysing interpreter into an equivalent older form (line numbers preserved).

    Currently: PEP 758 (Python 3.14) unparenthesised ``except A, B:`` -> ``except (A, B):``.
    """
    new = _UNPAREN_EXCEPT.sub(r"\1(\2)\3", text)
    return new if new != text else None


def _const_value(node: ast.AST | None, constants: dict[str, str]) -> str | None:
    """A literal string, or ``{expr}`` placeholder for a non-literal expression (resolved later from project constants)."""
    s = _const_str(node)
    if s is not None:
        return s
    if node is None:
        return None
    n = _name(node)
    if n and re.match(r"^[A-Za-z_][\w.]*$", n):
        return constants.get(n.split(".")[-1], "{" + n + "}")
    return None


def parse_python(path: str, text: str) -> ParseResult:
    mod = ModuleInfo(path=path, language="Python", parser="python-ast")
    res = ParseResult(module=mod)
    try:
        tree = ast.parse(text, filename=path, type_comments=False)
    except SyntaxError as exc:
        alt = compat_source(text)
        try:
            if alt is None:
                raise exc
            tree = ast.parse(alt, filename=path, type_comments=False)
            mod.parse_error = "parsed after normalising newer Python syntax (PEP 758 unparenthesised except); valid on Python >= 3.14"
        except SyntaxError:
            mod.parse_ok = False
            mod.parse_error = f"SyntaxError line {exc.lineno}: {exc.msg}"
            return res

    mod.docstring = (ast.get_docstring(tree) or "")[:500] or None
    nested_handlers: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for top in tree.body:
        targets: list[ast.expr] = top.targets if isinstance(top, ast.Assign) else ([top.target] if isinstance(top, ast.AnnAssign) else [])
        value = getattr(top, "value", None)
        for t in targets:
            if isinstance(t, ast.Name):
                if (s := _const_str(value)) is not None and "{" not in s:
                    res.constants[t.id] = s
                if (dep := _annotated_dependency(value)) is not None:
                    res.dep_aliases[t.id] = dep
        if isinstance(top, ast.ClassDef):
            for item in top.body:
                if isinstance(item, ast.AnnAssign | ast.Assign):
                    tg = item.target if isinstance(item, ast.AnnAssign) else (item.targets[0] if item.targets else None)
                    if isinstance(tg, ast.Name) and (s := _const_str(item.value)) is not None and "{" not in s:
                        res.constants.setdefault(tg.id, s)
    is_django_urls = path.endswith("urls.py")
    blueprints: dict[str, str] = {}

    # ---------- imports
    pkg_parts = path.split("/")[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mod.imports.append(ImportRef(file=path, module=a.name, names=[a.asname or a.name], line=node.lineno))
                res.import_aliases[a.asname or a.name.split(".")[0]] = a.name
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = pkg_parts[: len(pkg_parts) - (node.level - 1)] if node.level > 1 else pkg_parts
                base = ".".join([*up, base] if base else up)
                base = "." * 0 + base
                rel_marker = True
            else:
                rel_marker = False
            names = [a.name for a in node.names]
            mod.imports.append(ImportRef(file=path, module=("/" + base) if rel_marker else base, names=names, line=node.lineno))
            for a in node.names:
                full = f"{base}.{a.name}" if base else a.name
                res.import_aliases[a.asname or a.name] = ("/" + full) if rel_marker else full

    # ---------- module-level symbols
    def handle_function(fn: ast.FunctionDef | ast.AsyncFunctionDef, parent: str | None) -> Symbol:
        scan = _scan_body(fn)
        decos = [_name(d.func if isinstance(d, ast.Call) else d) for d in fn.decorator_list]
        sym = Symbol(
            name=fn.name,
            kind="method" if parent else "function",
            file=path,
            line_start=fn.lineno,
            line_end=getattr(fn, "end_lineno", fn.lineno) or fn.lineno,
            parent=parent,
            signature=_signature(fn),
            decorators=decos,
            docstring=(ast.get_docstring(fn) or "")[:300] or None,
            exported=not fn.name.startswith("_"),
            is_async=isinstance(fn, ast.AsyncFunctionDef),
            calls=scan.calls,
            raises=scan.raises,
            handles_exceptions=scan.handles,
        )
        mod.symbols.append(sym)
        _extract_route(fn, sym, scan)
        return sym

    def _extract_route(fn: ast.FunctionDef | ast.AsyncFunctionDef, sym: Symbol, scan: _BodyScan) -> None:
        for d in fn.decorator_list:
            if not isinstance(d, ast.Call) or not isinstance(d.func, ast.Attribute):
                continue
            attr = d.func.attr
            owner = _name(d.func.value)
            route_path = _const_str(d.args[0]) if d.args else _const_str(_kw(d, "path"))
            if route_path is None:
                continue
            methods: list[str] = []
            framework = "FastAPI"
            kind = "http"
            if attr in HTTP_METHODS:
                methods = [attr.upper()]
                if owner in blueprints or "bp" in owner.lower() or "blueprint" in owner.lower():
                    framework = "Flask"
            elif attr == "route":
                framework = "Flask"
                mnode = _kw(d, "methods")
                if isinstance(mnode, ast.List | ast.Tuple):
                    methods = [str(_const_str(e)).upper() for e in mnode.elts if _const_str(e)]
                methods = methods or ["GET"]
            elif attr == "api_route":
                mnode = _kw(d, "methods")
                if isinstance(mnode, ast.List | ast.Tuple):
                    methods = [str(_const_str(e)).upper() for e in mnode.elts if _const_str(e)]
                methods = methods or ["GET"]
            elif attr == "websocket":
                methods, kind = ["WS"], "websocket"
            else:
                continue
            params: list[str] = []
            auth: list[str] = []
            body_model: str | None = None
            param_annotations: dict[str, str] = {}
            all_args = fn.args.args + fn.args.kwonlyargs
            defaults = [None] * (len(fn.args.args) - len(fn.args.defaults)) + list(fn.args.defaults) + list(fn.args.kw_defaults)
            for a, default in zip(all_args, defaults, strict=False):
                if a.arg in ("self", "cls", "request", "req"):
                    continue
                ann = _ann(a.annotation)
                if ann:
                    param_annotations[a.arg] = ann
                inline_dep = _annotated_dependency(a.annotation)
                if inline_dep is not None:
                    if _AUTH_HINT.search(inline_dep) and not inline_dep.endswith("Form"):
                        auth.append(inline_dep)
                    else:
                        sym.calls.append(inline_dep)
                    continue
                if isinstance(default, ast.Call) and _name(default.func).endswith(("Depends", "Security")):
                    dep = _name(default.args[0]) if default.args else ann
                    if (_AUTH_HINT.search(dep) and not dep.endswith(("Form", "RequestForm"))) or _name(default.func).endswith("Security"):
                        auth.append(dep)
                    else:
                        sym.calls.append(dep)
                    continue
                if (
                    ann and ann[:1].isupper() and ann not in _NON_BODY_TYPES
                    and "{" + a.arg + "}" not in route_path and body_model is None
                ):
                    body_model = ann
                    continue
                params.append(f"{a.arg}: {ann}" if ann else a.arg)
            for dep_node in (_kw(d, "dependencies"),):
                if isinstance(dep_node, ast.List):
                    for e in dep_node.elts:
                        if isinstance(e, ast.Call) and e.args:
                            auth.append(_name(e.args[0]))
            for dname in sym.decorators:
                if _AUTH_HINT.search(dname) and dname.split(".")[-1] not in HTTP_METHODS | {"route"}:
                    auth.append(dname)
            resp = _kw(d, "response_model")
            sc = _kw(d, "status_code")
            codes = list(scan.status_codes)
            if isinstance(sc, ast.Constant) and isinstance(sc.value, int):
                codes.insert(0, sc.value)
            for m in methods:
                res.routes.append(Route(
                    method=m, path=route_path, handler=sym.name, file=path, line=d.lineno, framework=framework, kind=kind,
                    params=params, body_model=body_model, response_model=_name(resp) if resp is not None else None,
                    auth=auth, calls=[c for c in sym.calls if not c.startswith(("print", "len", "str", "int"))][:25],
                    status_codes=sorted(set(codes)), errors=sym.raises,
                    router_var=owner, param_annotations=param_annotations,
                ))

    # app-factory pattern: route handlers declared inside create_app()-style functions
    top_level = {id(n) for n in tree.body}
    class_methods = {id(item) for n in ast.walk(tree) if isinstance(n, ast.ClassDef) for item in n.body}
    for fn_node in ast.walk(tree):
        if (isinstance(fn_node, ast.FunctionDef | ast.AsyncFunctionDef) and id(fn_node) not in top_level and id(fn_node) not in class_methods
                and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in HTTP_METHODS | {"route", "api_route", "websocket"}
                        for d in fn_node.decorator_list)):
            nested_handlers.append(fn_node)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            handle_function(node, None)
        elif isinstance(node, ast.ClassDef):
            _handle_class(node, path, mod, res, handle_function)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            for t in targets:
                if isinstance(t, ast.Name):
                    kind = "constant" if t.id.isupper() else "variable"
                    sig = None
                    if value is not None:
                        try:
                            sig = f"{t.id} = {ast.unparse(value)}"[:200]
                        except Exception:
                            sig = None
                    mod.symbols.append(Symbol(name=t.id, kind=kind, file=path, line_start=node.lineno, line_end=getattr(node, "end_lineno", node.lineno) or node.lineno, signature=sig, exported=not t.id.startswith("_")))
                    if isinstance(value, ast.Call):
                        cname = _name(value.func)
                        if cname.endswith("APIRouter"):
                            pre = _const_value(_kw(value, "prefix"), res.constants) or ""
                            res.router_prefixes[t.id] = pre
                        elif cname.endswith("Blueprint"):
                            pre = _const_value(_kw(value, "url_prefix"), res.constants) or ""
                            res.router_prefixes[t.id] = pre
                            blueprints[t.id] = pre
                        elif cname.endswith(("FastAPI", "Flask")):
                            res.router_prefixes[t.id] = ""
            # Django urlpatterns
            if is_django_urls and any(isinstance(t, ast.Name) and t.id == "urlpatterns" for t in targets) and isinstance(value, ast.List | ast.BinOp):
                elts = value.elts if isinstance(value, ast.List) else []
                for e in elts:
                    if isinstance(e, ast.Call) and _name(e.func) in {"path", "re_path", "url"} and e.args:
                        rp = _const_str(e.args[0]) or ""
                        handler = _name(e.args[1]) if len(e.args) > 1 else None
                        if handler and handler.endswith("include()"):
                            continue
                        res.routes.append(Route(method="ANY", path="/" + rp.lstrip("^/").rstrip("$"), handler=handler, file=path, line=e.lineno, framework="Django"))

    for inner in nested_handlers:
        handle_function(inner, None)

    # ---------- whole-tree scans: env vars, mounts, db ops, http client calls, sql strings
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fname = _name(node.func)
            # env vars
            if fname in {"os.getenv", "os.environ.get", "getenv", "environ.get", "env", "config"} and node.args:
                v = _const_str(node.args[0])
                if v and re.match(r"^[A-Z][A-Z0-9_]+$", v):
                    mod.env_vars.append((v, node.lineno))
            # router mounts
            if isinstance(node.func, ast.Attribute) and node.func.attr in {"include_router", "register_blueprint", "mount"} and node.args:
                mount_target = _name(node.args[0]) if node.func.attr != "mount" else (_name(node.args[1]) if len(node.args) > 1 else "")
                prefix = (_const_value(_kw(node, "prefix"), res.constants) or _const_value(_kw(node, "url_prefix"), res.constants)
                          or (_const_str(node.args[0]) if node.func.attr == "mount" else "") or "")
                if mount_target:
                    res.mounts.append(RouterMount(file=path, line=node.lineno, target_expr=mount_target, prefix=prefix))
            # middleware
            if isinstance(node.func, ast.Attribute) and node.func.attr == "add_middleware" and node.args:
                mod.roles.append("middleware-registration")
            # db operations
            if isinstance(node.func, ast.Attribute):
                attr = node.func.attr
                recv = _name(node.func.value)
                op = _DB_OP_ATTRS.get(attr, "missing")
                if op != "missing" and (_DB_RECEIVERS.match(recv) or recv.endswith(".objects") or attr in {"query", "execute"} and recv):
                    if op is None:
                        op = "select" if attr == "get" else "insert"
                    if attr == "get" and not (recv.endswith(".objects") or "session" in recv.lower() or recv == "db"):
                        continue
                    target: str | None = None
                    if node.args:
                        target = _name(node.args[0])[:80]
                    snippet = None
                    raw = False
                    if attr in {"execute", "executemany"} and node.args:
                        s = _const_str(node.args[0])
                        if s:
                            snippet, raw = s[:200], True
                        elif isinstance(node.args[0], ast.BinOp | ast.JoinedStr) or (isinstance(node.args[0], ast.Call) and _name(node.args[0].func).endswith("format")):
                            snippet, raw = "<dynamically built SQL>", True
                    if recv.endswith(".objects"):
                        target = recv.rsplit(".", 1)[0]
                    res.db_operations.append(DbOperation(file=path, line=node.lineno, operation=op, target=target, snippet=snippet, raw_sql=raw))
                # http client calls
                if attr in HTTP_METHODS | {"request"} and _HTTP_CLIENTS.match(recv) and node.args:
                    url = _const_str(node.args[0]) if attr != "request" else (_const_str(node.args[1]) if len(node.args) > 1 else None)
                    if url and ("/" in url or url.startswith("{")):
                        method = attr.upper() if attr != "request" else (_const_str(node.args[0]) or "GET").upper()
                        res.client_calls.append(ClientCall(file=path, line=node.lineno, method=method, url=url))
                        mod.http_calls.append({"method": method, "url": url, "line": node.lineno})
        elif isinstance(node, ast.Subscript) and _name(node.value) in {"os.environ", "environ"}:
            v = _const_str(node.slice)
            if v:
                mod.env_vars.append((v, node.lineno))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and SQL_RE.match(node.value):
            mod.string_literals_sql.append((node.value[:200], getattr(node, "lineno", 0)))

    # pydantic-settings style env: class Settings(BaseSettings) fields
    for sym in mod.symbols:
        if sym.kind == "class" and any(b.endswith("BaseSettings") for b in sym.bases):
            for s2 in mod.symbols:
                if s2.parent == sym.name and s2.kind == "attribute":
                    mod.env_vars.append((s2.name.upper(), s2.line_start))

    # ORM models inherit annotated fields from base classes declared in the same module
    for dbm in res.db_models:
        seen = {f.name for f in dbm.fields}
        inherited: list[DbField] = []
        stack = list(res.class_fields.get(dbm.name, ([], []))[0])
        visited: set[str] = set()
        while stack:
            b = stack.pop(0).split(".")[-1]
            if b in visited or b not in res.class_fields:
                continue
            visited.add(b)
            b_bases, b_fields = res.class_fields[b]
            for fld in b_fields:
                if fld.name not in seen:
                    seen.add(fld.name)
                    inherited.append(fld)
            stack.extend(b_bases)
        dbm.fields = inherited + dbm.fields
    mod.exports = [s.name for s in mod.symbols if s.parent is None and s.exported and s.kind in ("class", "function")]
    mod.roles = sorted(set(mod.roles + _infer_roles(path, mod, res)))
    return res


def _handle_class(node: ast.ClassDef, path: str, mod: ModuleInfo, res: ParseResult, handle_function) -> None:  # type: ignore[no-untyped-def]
    bases = [_name(b) for b in node.bases]
    kw_table = any(k.arg == "table" and isinstance(k.value, ast.Constant) and k.value.value is True for k in node.keywords)
    decos = [_name(d.func if isinstance(d, ast.Call) else d) for d in node.decorator_list]
    kind = "class"
    if any(b.endswith("Enum") or b in {"IntEnum", "StrEnum"} for b in bases):
        kind = "enum"
    elif any(b.endswith("Protocol") or b in {"ABC", "abc.ABC"} for b in bases):
        kind = "interface"
    mod.symbols.append(Symbol(
        name=node.name, kind=kind, file=path, line_start=node.lineno, line_end=getattr(node, "end_lineno", node.lineno) or node.lineno,
        decorators=decos, bases=bases, docstring=(ast.get_docstring(node) or "")[:300] or None, exported=not node.name.startswith("_"),
    ))
    table: str | None = None
    fields: list[DbField] = []
    candidate_fields: list[DbField] = []
    rels: list[dict[str, object]] = []
    indexes: list[str] = []
    is_orm = (
        any(b in _ORM_BASES or b.endswith(("db.Model", "models.Model", "DeclarativeBase")) for b in bases)
        and not any(b.endswith(("BaseModel",)) and b != "db.Model" for b in bases)
    ) or kw_table
    if "SQLModel" in bases and not kw_table:
        is_orm = False
    orm = "Django ORM" if any("models.Model" in b for b in bases) else ("SQLModel" if kw_table else "SQLAlchemy")
    if any(b == "Document" for b in bases):
        orm = "MongoEngine/Beanie"
    for item in node.body:
        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
            handle_function(item, node.name)
        elif isinstance(item, ast.Assign | ast.AnnAssign):
            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
            value = item.value
            for t in targets:
                if not isinstance(t, ast.Name):
                    continue
                ann = _ann(item.annotation) if isinstance(item, ast.AnnAssign) else None
                mod.symbols.append(Symbol(name=t.id, kind="attribute", file=path, line_start=item.lineno, line_end=item.lineno, parent=node.name, signature=(f"{t.id}: {ann}" if ann else t.id)))
                if t.id == "__tablename__":
                    table = _const_str(value)
                    is_orm = True
                    continue
                if t.id in ("__table_args__", "Meta", "model_config") or (value is None and ann is None):
                    continue
                f = _db_field(t.id, ann, value, item.lineno)
                if f is None:
                    continue
                if isinstance(f, DbField):
                    candidate_fields.append(f)  # remembered for subclasses (e.g. SQLModel `UserBase` -> `User(table=True)`)
                if not is_orm:
                    continue
                if isinstance(f, dict):
                    rels.append(f)
                else:
                    fields.append(f)
                    if f.index:
                        indexes.append(f.name)
        elif isinstance(item, ast.ClassDef):
            if item.name == "Meta":
                for s in item.body:
                    if isinstance(s, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "db_table" for t in s.targets):
                        table = _const_str(s.value)
            else:
                _handle_class(item, path, mod, res, handle_function)
    res.class_fields[node.name] = (bases, candidate_fields)
    if is_orm and (fields or rels or table):
        if table is None and orm in ("Django ORM", "SQLModel"):
            table = node.name.lower()  # framework default naming
        res.db_models.append(DbModel(name=node.name, table=table, orm=orm, file=path, line=node.lineno, fields=fields, relationships=rels, indexes=indexes))


def _const_bool(node: ast.AST | None) -> bool | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    return None


def _relation_target(ann: str) -> str:
    """``Mapped[list["Item"]]`` / ``list[Item]`` / ``User | None`` -> the related class name."""
    t = re.sub(r"\b(Mapped|List|list|Optional|Set|set|Sequence)\[", "", ann)
    t = re.sub(r"[\]'\"]", "", t)
    t = re.sub(r"\s*\|\s*None|None\s*\|\s*", "", t)
    return t.strip()


def _db_field(name: str, ann: str | None, value: ast.AST | None, line: int) -> DbField | dict[str, object] | None:
    if isinstance(value, ast.Call):
        fn = _name(value.func)
        short = fn.split(".")[-1]
        if short in {"relationship", "Relationship", "relation"}:
            target = _const_str(value.args[0]) if value.args else None
            if target is None and ann:
                target = _relation_target(ann)
            back = _const_str(_kw(value, "back_populates")) or _const_str(_kw(value, "backref"))
            return {"name": name, "target": target, "kind": "relationship", "back_populates": back, "line": line}
        if short in {"ForeignKey", "OneToOneField", "ManyToManyField"} and fn.startswith(("models.", "ForeignKey", "OneToOne", "ManyToMany")):
            target = _name(value.args[0]) if value.args else None
            if value.args and (s := _const_str(value.args[0])):
                target = s
            kind = {"ForeignKey": "many_to_one", "OneToOneField": "one_to_one", "ManyToManyField": "many_to_many"}[short]
            return {"name": name, "target": target, "kind": kind, "line": line}
        if short in {"Column", "mapped_column", "Field"} or fn.startswith("models.") or short.endswith("Field"):
            col_type = None
            fk = None
            for a in value.args:
                an = _name(a)
                if isinstance(a, ast.Call) and _name(a.func).endswith("ForeignKey") and a.args:
                    fk = _const_str(a.args[0]) or _name(a.args[0])
                elif col_type is None and not isinstance(a, ast.Constant):
                    col_type = an.rstrip("()")
            if fn.startswith("models."):
                col_type = short
            fk_kw = _kw(value, "foreign_key")
            if fk_kw is not None:
                fk = _const_str(fk_kw)
            pk = _kw(value, "primary_key")
            nullable = _kw(value, "nullable")
            null_dj = _kw(value, "null")
            unique = _kw(value, "unique")
            index = _kw(value, "index") or _kw(value, "db_index")
            default = _kw(value, "default")
            if col_type is None and ann:
                col_type = re.sub(r"^Mapped\[(.*)\]$", r"\1", ann)
            return DbField(
                name=name, type=col_type, primary_key=isinstance(pk, ast.Constant) and pk.value is True, foreign_key=fk,
                nullable=_const_bool(nullable) if _const_bool(nullable) is not None else _const_bool(null_dj),
                unique=isinstance(unique, ast.Constant) and unique.value is True,
                index=isinstance(index, ast.Constant) and index.value is True,
                default=_name(default)[:60] if default is not None else None, line=line,
            )
    if ann and ("Mapped[" in ann or ann in {"int", "str", "float", "bool", "datetime", "Optional"}):
        t = re.sub(r"^Mapped\[(.*)\]$", r"\1", ann)
        return DbField(name=name, type=t, nullable="Optional" in t or "None" in t, line=line)
    return None


def _infer_roles(path: str, mod: ModuleInfo, res: ParseResult) -> list[str]:
    roles: list[str] = []
    low = path.lower()
    if res.routes:
        roles.append("api-routes")
    if res.db_models:
        roles.append("data-model")
    if res.db_operations:
        roles.append("data-access")
    if any(s.kind == "class" and any(b.endswith("BaseModel") for b in s.bases) for s in mod.symbols):
        roles.append("schema")
    for key, role in (("service", "service"), ("repositor", "repository"), ("controller", "controller"), ("middleware", "middleware"),
                      ("auth", "auth"), ("security", "auth"), ("util", "utility"), ("helper", "utility"), ("worker", "worker"),
                      ("task", "worker"), ("config", "config"), ("settings", "config"), ("schema", "schema"), ("model", "data-model"),
                      ("crud", "data-access"), ("dao", "data-access"), ("view", "controller"), ("route", "api-routes"), ("api/", "api-routes")):
        if key in low:
            roles.append(role)
    if any(d.endswith(("celery.task", "shared_task", "app.task")) for s in mod.symbols for d in s.decorators):
        roles.append("worker")
    return roles
