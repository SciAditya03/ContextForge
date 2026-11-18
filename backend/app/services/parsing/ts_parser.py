"""JavaScript / TypeScript structural extraction using tree-sitter."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import PurePosixPath

import tree_sitter_javascript as tsjs
import tree_sitter_typescript as tsts
from tree_sitter import Language, Node, Parser

from app.schemas.facts import ClientCall, DbField, DbModel, DbOperation, ImportRef, ModuleInfo, Route, Symbol
from app.services.parsing.base import SQL_RE, ParseResult, RouterMount, join_paths

_PRISMA_OPS = {
    "findMany": "select", "findUnique": "select", "findFirst": "select", "findUniqueOrThrow": "select", "findFirstOrThrow": "select",
    "create": "insert", "createMany": "insert", "update": "update", "updateMany": "update", "upsert": "update",
    "delete": "delete", "deleteMany": "delete", "count": "select", "aggregate": "select", "groupBy": "select",
}
_MONGOOSE_OPS = {"find": "select", "findOne": "select", "findById": "select", "findByIdAndUpdate": "update", "findOneAndUpdate": "update",
                 "updateOne": "update", "updateMany": "update", "deleteOne": "delete", "deleteMany": "delete", "insertMany": "insert",
                 "findByIdAndDelete": "delete", "countDocuments": "select", "aggregate": "select"}
_AUTH_HINT = re.compile(r"(auth|protect|requireUser|verify|jwt|session|guard|isLoggedIn|ensureAuth|passport|permission|role)", re.I)
_NEXT_ROUTE = re.compile(r"(?:^|/)app/(.*)/route\.[cm]?[jt]sx?$")
_NEXT_PAGES_API = re.compile(r"(?:^|/)pages/api/(.*)\.[cm]?[jt]sx?$")


@lru_cache(maxsize=4)
def _parser(kind: str) -> Parser:
    if kind == "tsx":
        lang = Language(tsts.language_tsx())
    elif kind == "ts":
        lang = Language(tsts.language_typescript())
    else:
        lang = Language(tsjs.language())
    return Parser(lang)


def _txt(node: Node | None, src: bytes) -> str:
    if node is None:
        return ""
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _str_value(node: Node | None, src: bytes) -> str | None:
    if node is None:
        return None
    if node.type == "string":
        return _txt(node, src)[1:-1]
    if node.type == "template_string":
        return _txt(node, src)[1:-1]
    return None


def _call_name(node: Node, src: bytes) -> str:
    fn = node.child_by_field_name("function")
    return _txt(fn, src) if fn is not None else ""


def _file_route_path(seg: str) -> str:
    parts = []
    for p in seg.split("/"):
        if p.startswith("(") and p.endswith(")"):
            continue  # route groups
        if p.startswith("@"):
            continue
        parts.append(p)
    path = "/" + "/".join(parts)
    path = re.sub(r"\[\[?\.\.\.(\w+)\]?\]", r"*\1", path)
    path = re.sub(r"\[(\w+)\]", r":\1", path)
    return path.replace("/index", "") or "/"


def parse_typescript(path: str, text: str) -> ParseResult:
    ext = PurePosixPath(path).suffix.lower()
    kind = "tsx" if ext in {".tsx", ".jsx"} else ("ts" if ext in {".ts", ".mts", ".cts"} else "js")
    if kind == "js" and ("<" in text and re.search(r"return\s*\(?\s*<[A-Za-z]", text)):
        kind = "tsx"  # JSX inside .js
    lang = "TypeScript" if ext in {".ts", ".tsx", ".mts", ".cts"} else "JavaScript"
    mod = ModuleInfo(path=path, language=lang, parser=f"tree-sitter-{kind}")
    res = ParseResult(module=mod)
    src = text.encode("utf-8")
    tree = _parser(kind).parse(src)
    root = tree.root_node
    if root.has_error:
        mod.parse_error = "tree-sitter reported syntax errors; extraction may be partial"

    express_apps: set[str] = set()
    client_vars: set[str] = set()
    server_imports = bool(re.search(r"""(from\s+|require\()\s*['"](express|koa|@koa/router|koa-router|hono|fastify|restify|polka|@hapi/hapi)['"]""", text))
    nest_prefix: str | None = None
    is_tsx = kind == "tsx"

    def add_symbol(name: str, kind_: str, node: Node, parent: str | None = None, exported: bool = False, sig: str | None = None, decos: list[str] | None = None, bases: list[str] | None = None, body: Node | None = None, is_async: bool = False) -> Symbol:
        calls: list[str] = []
        handles = False
        raises: list[str] = []
        if body is not None:
            stack = [body]
            while stack:
                n = stack.pop()
                if n.type == "call_expression":
                    cn = _call_name(n, src)
                    if cn and cn not in calls and len(calls) < 50 and len(cn) < 80:
                        calls.append(cn)
                elif n.type == "try_statement":
                    handles = True
                elif n.type == "throw_statement":
                    t = _txt(n, src)
                    m = re.search(r"new\s+([A-Za-z_][\w.]*)", t)
                    if m and m.group(1) not in raises:
                        raises.append(m.group(1))
                elif n.type in {"function_declaration", "class_declaration"} and n is not body:
                    continue
                stack.extend(n.children)
        if kind_ == "function" and name[:1].isupper() and is_tsx and body is not None and ("jsx_element" in _types(body) or "jsx_self_closing_element" in _types(body)):
            kind_ = "component"
        elif kind_ == "function" and re.match(r"^use[A-Z]", name):
            kind_ = "hook"
        sym = Symbol(
            name=name, kind=kind_, file=path, line_start=node.start_point[0] + 1, line_end=node.end_point[0] + 1, parent=parent,
            signature=(sig or "")[:240] or None, exported=exported, decorators=decos or [], bases=bases or [], calls=calls,
            raises=raises, handles_exceptions=handles, is_async=is_async,
        )
        mod.symbols.append(sym)
        return sym

    def fn_signature(node: Node) -> str:
        params = node.child_by_field_name("parameters")
        ret = node.child_by_field_name("return_type")
        return f"({_txt(params, src)[1:-1] if params else ''}){_txt(ret, src) if ret else ''}".replace("\n", " ")

    def handle_decl(node: Node, exported: bool, parent: str | None = None) -> None:
        t = node.type
        if t in {"function_declaration", "generator_function_declaration"}:
            name = _txt(node.child_by_field_name("name"), src)
            is_async = _txt(node, src).lstrip().startswith("async")
            add_symbol(name, "function", node, parent, exported, f"function {name}{fn_signature(node)}", body=node.child_by_field_name("body"), is_async=is_async)
            if exported:
                mod.exports.append(name)
        elif t in {"class_declaration", "abstract_class_declaration"}:
            name = _txt(node.child_by_field_name("name"), src)
            bases: list[str] = []
            decos = [_txt(c, src).lstrip("@").split("(")[0] for c in node.children if c.type == "decorator"]
            # decorators may also live on the export statement parent
            if node.parent is not None and node.parent.type == "export_statement":
                decos += [_txt(c, src).lstrip("@").split("(")[0] for c in node.parent.children if c.type == "decorator"]
            for c in node.children:
                if c.type == "class_heritage":
                    bases = [b for b in re.split(r"[\s,]+", re.sub(r"\b(extends|implements)\b", " ", _txt(c, src))) if b]
            add_symbol(name, "class", node, parent, exported, f"class {name}", decos=decos, bases=bases)
            if exported:
                mod.exports.append(name)
            nonlocal nest_prefix
            all_decos = [c for c in node.children if c.type == "decorator"] + ([c for c in node.parent.children if c.type == "decorator"] if node.parent is not None and node.parent.type == "export_statement" else [])
            controller_prefix = None
            is_entity = False
            table = None
            for d in all_decos:
                dt = _txt(d, src)
                if dt.startswith("@Controller"):
                    m = re.search(r"['\"`]([^'\"`]*)['\"`]", dt)
                    controller_prefix = m.group(1) if m else ""
                if dt.startswith("@Entity"):
                    is_entity = True
                    m = re.search(r"['\"`]([^'\"`]*)['\"`]", dt)
                    table = m.group(1) if m else None
            body = node.child_by_field_name("body")
            entity_fields: list[DbField] = []
            entity_rels: list[dict[str, object]] = []
            if body is not None:
                pending_decos: list[str] = []
                for member in body.children:
                    if member.type == "decorator":
                        pending_decos.append(_txt(member, src))
                        continue
                    mdecos = pending_decos + [_txt(c, src) for c in member.children if c.type == "decorator"]
                    pending_decos = []
                    if member.type == "method_definition":
                        mname = _txt(member.child_by_field_name("name"), src)
                        sym = add_symbol(mname, "method", member, name, False, f"{mname}{fn_signature(member)}",
                                         decos=[d.lstrip("@").split("(")[0] for d in mdecos], body=member.child_by_field_name("body"),
                                         is_async=_txt(member, src).lstrip().startswith("async"))
                        if controller_prefix is not None:
                            for deco in mdecos:
                                m = re.match(r"@(Get|Post|Put|Delete|Patch|Options|Head|All)\s*\(\s*(?:['\"`]([^'\"`]*)['\"`])?", deco)
                                if m:
                                    guards = [g for g in mdecos if g.startswith("@UseGuards")]
                                    res.routes.append(Route(method=m.group(1).upper().replace("ALL", "ANY"), path=join_paths(controller_prefix, m.group(2) or ""),
                                                            handler=f"{name}.{mname}", file=path, line=member.start_point[0] + 1, framework="NestJS",
                                                            auth=[re.sub(r"^@UseGuards\(|\)$", "", g) for g in guards], calls=sym.calls[:20], resolved_prefix=True))
                    elif member.type in {"public_field_definition", "field_definition", "property_declaration"}:
                        fname_node = member.child_by_field_name("name") or member.child_by_field_name("property")
                        fname = _txt(fname_node, src)
                        tnode = member.child_by_field_name("type")
                        ftype = _txt(tnode, src).lstrip(": ").strip() if tnode is not None else None
                        add_symbol(fname, "attribute", member, name, False, f"{fname}: {ftype}" if ftype else fname)
                        if is_entity:
                            dtext = " ".join(mdecos)
                            rel = re.search(r"@(OneToMany|ManyToOne|OneToOne|ManyToMany)\s*\(\s*\(\)\s*=>\s*(\w+)", dtext)
                            if rel:
                                entity_rels.append({"name": fname, "target": rel.group(2), "kind": re.sub(r"(?<!^)([A-Z])", r"_\1", rel.group(1)).lower(), "line": member.start_point[0] + 1})
                            elif "@Column" in dtext or "@PrimaryGeneratedColumn" in dtext or "@PrimaryColumn" in dtext or "Column" in dtext:
                                entity_fields.append(DbField(name=fname, type=ftype, primary_key="Primary" in dtext, unique="unique: true" in dtext,
                                                             nullable=True if "nullable: true" in dtext else None, line=member.start_point[0] + 1))
            if is_entity:
                res.db_models.append(DbModel(name=name, table=table, orm="TypeORM", file=path, line=node.start_point[0] + 1, fields=entity_fields, relationships=entity_rels))
            if controller_prefix is not None:
                nest_prefix = controller_prefix
        elif t in {"interface_declaration"}:
            name = _txt(node.child_by_field_name("name"), src)
            add_symbol(name, "interface", node, parent, exported, _txt(node, src).split("{")[0].strip())
            if exported:
                mod.exports.append(name)
        elif t == "type_alias_declaration":
            name = _txt(node.child_by_field_name("name"), src)
            add_symbol(name, "type", node, parent, exported, _txt(node, src)[:200].replace("\n", " "))
            if exported:
                mod.exports.append(name)
        elif t == "enum_declaration":
            name = _txt(node.child_by_field_name("name"), src)
            add_symbol(name, "enum", node, parent, exported, f"enum {name}")
            if exported:
                mod.exports.append(name)
        elif t in {"lexical_declaration", "variable_declaration"}:
            for decl in node.children:
                if decl.type != "variable_declarator":
                    continue
                nm_node = decl.child_by_field_name("name")
                name = _txt(nm_node, src)
                value = decl.child_by_field_name("value")
                if value is not None and value.type in {"arrow_function", "function_expression", "function"}:
                    is_async = _txt(value, src).lstrip().startswith("async")
                    add_symbol(name, "function", decl, parent, exported, f"const {name} = {fn_signature(value)} =>", body=value.child_by_field_name("body") or value, is_async=is_async)
                elif value is not None and value.type == "call_expression" and _call_name(value, src) in {"React.forwardRef", "forwardRef", "memo", "React.memo", "styled", "observer"}:
                    add_symbol(name, "component", decl, parent, exported, f"const {name} = {_call_name(value, src)}(...)", body=value)
                else:
                    k = "constant" if (name.isupper() or "const" in _txt(node, src)[:6]) else "variable"
                    vtxt = _txt(value, src)[:120].replace("\n", " ") if value is not None else ""
                    add_symbol(name, k, decl, parent, exported, f"{name} = {vtxt}" if vtxt else name)
                    if value is not None and value.type == "call_expression":
                        cn = _call_name(value, src)
                        if cn in {"express", "express.Router", "Router", "fastify", "Fastify", "new Hono", "Hono"} or cn.endswith(("express", "Router")):
                            express_apps.add(name)
                    if value is not None and value.type == "new_expression" and re.match(r"new\s+(Hono|Koa|Router|KoaRouter)\b", _txt(value, src)):
                        express_apps.add(name)
                    if value is not None and value.type == "call_expression" and re.search(r"(axios|ky|ofetch|got)\.(create|extend)$|^(createClient|create\w*Client)$", _call_name(value, src)):
                        client_vars.add(name)
                if exported and name:
                    mod.exports.append(name)

    # ---------- top-level declarations
    for child in root.children:
        if child.type == "export_statement":
            decl = child.child_by_field_name("declaration")
            if decl is not None:
                handle_decl(decl, True)
            else:
                txt = _txt(child, src)
                if txt.startswith("export default"):
                    val = child.child_by_field_name("value")
                    if val is not None and val.type == "identifier":
                        mod.exports.append("default:" + _txt(val, src))
                    elif val is not None and val.type in {"arrow_function", "function_expression", "function"}:
                        add_symbol("default", "function", val, None, True, "export default function", body=val.child_by_field_name("body"))
                        mod.exports.append("default")
                    else:
                        for c in child.children:
                            if c.type in {"function_declaration", "class_declaration"}:
                                handle_decl(c, True)
                        if not any(c.type in {"function_declaration", "class_declaration"} for c in child.children):
                            mod.exports.append("default")
                src_node = child.child_by_field_name("source")
                if src_node is not None:
                    spec = _str_value(src_node, src) or ""
                    mod.imports.append(ImportRef(file=path, module=spec, names=["*re-export*"], line=child.start_point[0] + 1))
                for c in child.children:
                    if c.type == "export_clause":
                        for s in c.children:
                            if s.type == "export_specifier":
                                mod.exports.append(_txt(s.child_by_field_name("alias") or s.child_by_field_name("name"), src))
        elif child.type == "import_statement":
            src_node = child.child_by_field_name("source")
            spec = _str_value(src_node, src) or ""
            names: list[str] = []
            for c in child.children:
                if c.type == "import_clause":
                    for n in _walk(c):
                        if n.type == "identifier" and n.parent is not None and n.parent.type in {"import_clause", "import_specifier", "namespace_import"}:
                            names.append(_txt(n, src))
            mod.imports.append(ImportRef(file=path, module=spec, names=names, line=child.start_point[0] + 1))
            for n in names:
                res.import_aliases[n] = spec
        else:
            handle_decl(child, False)

    # ---------- expression scans
    for n in _walk(root):
        if n.type == "call_expression":
            cn = _call_name(n, src)
            args = n.child_by_field_name("arguments")
            arg_nodes = [a for a in (args.children if args is not None else []) if a.type not in {"(", ")", ","}]
            first = arg_nodes[0] if arg_nodes else None
            line = n.start_point[0] + 1
            if cn in {"require"} and first is not None:
                req_spec = _str_value(first, src)
                if req_spec:
                    mod.imports.append(ImportRef(file=path, module=req_spec, names=[], line=line))
            elif cn == "import" and first is not None:
                req_spec = _str_value(first, src)
                if req_spec:
                    mod.imports.append(ImportRef(file=path, module=req_spec, names=["*dynamic*"], line=line))
            # express-style routes:  app.get('/x', mw, handler)
            m = re.match(r"^(\w+)\.(get|post|put|delete|patch|options|head|all|use|route)$", cn)
            is_server_recv = m is not None and m.group(1) not in client_vars and (
                m.group(1) in express_apps or (server_imports and m.group(1) in {"app", "router", "server", "api", "routes", "r"}))
            if m and first is not None and is_server_recv and len(arg_nodes) >= 2:
                route_path = _str_value(first, src)
                if route_path is not None and route_path.startswith("/"):
                    if m.group(2) == "use":
                        target = _txt(arg_nodes[-1], src) if len(arg_nodes) > 1 else ""
                        if len(arg_nodes) > 1:
                            res.mounts.append(RouterMount(file=path, line=line, target_expr=target, prefix=route_path))
                    elif m.group(2) != "route":
                        mids = [_txt(a, src)[:60] for a in arg_nodes[1:-1]]
                        handler_node = arg_nodes[-1] if len(arg_nodes) > 1 else None
                        handler = _txt(handler_node, src)[:80] if handler_node is not None and handler_node.type in {"identifier", "member_expression"} else ("<inline handler>" if handler_node is not None else None)
                        calls: list[str] = []
                        if handler_node is not None and handler_node.type in {"arrow_function", "function_expression"}:
                            for c in _walk(handler_node):
                                if c.type == "call_expression":
                                    nm = _call_name(c, src)
                                    if nm and nm not in calls and len(nm) < 80:
                                        calls.append(nm)
                        res.routes.append(Route(method=m.group(2).upper().replace("ALL", "ANY"), path=route_path, handler=handler, file=path, line=line,
                                                framework="Express", middleware=mids, auth=[x for x in mids if _AUTH_HINT.search(x)], calls=calls[:25], router_var=m.group(1)))
            # client HTTP calls
            if cn in {"fetch", "window.fetch", "$fetch", "ofetch", "useFetch", "useSWR"} and first is not None:
                url = _str_value(first, src)
                if url and ("/" in url):
                    method = "GET"
                    if len(arg_nodes) > 1:
                        mm = re.search(r"method\s*:\s*['\"`](\w+)['\"`]", _txt(arg_nodes[1], src))
                        if mm:
                            method = mm.group(1).upper()
                    res.client_calls.append(ClientCall(file=path, line=line, method=method, url=url))
                    mod.http_calls.append({"method": method, "url": url, "line": line})
            mm = re.match(r"^(axios|api|http|client|apiClient|request|instance|\w+Api|\w+Client|ky|\$axios|\$http|\w+)\.(get|post|put|delete|patch)$", cn)
            if mm and first is not None and not is_server_recv and (mm.group(1) in client_vars or re.match(r"^(axios|api|http|client|apiClient|request|instance|\w+Api|\w+Client|ky|\$axios|\$http)$", mm.group(1))):
                url = _str_value(first, src)
                if url and "/" in url:
                    res.client_calls.append(ClientCall(file=path, line=line, method=mm.group(2).upper(), url=url))
                    mod.http_calls.append({"method": mm.group(2).upper(), "url": url, "line": line})
            # thin API helpers: request("/api/projects"), apiFetch(`/api/items/${id}`, { method: "DELETE" })
            if (first is not None and not (m and is_server_recv) and cn not in {"fetch", "window.fetch", "$fetch", "ofetch", "useFetch", "useSWR", "require", "import"}
                    and not re.match(r"^(axios|api|http|client|apiClient|request|instance|ky)\.(get|post|put|delete|patch)$", cn)):
                helper_url = _str_value(first, src)
                if helper_url and re.match(r"^/(api|v\d+)(/|$)", helper_url) and re.search(r"(request|fetch|api|http|call|client)", cn, re.I):
                    helper_method = "GET"
                    if len(arg_nodes) > 1:
                        mm2 = re.search(r"method\s*:\s*['\"`](\w+)['\"`]", _txt(arg_nodes[1], src))
                        if mm2:
                            helper_method = mm2.group(1).upper()
                    res.client_calls.append(ClientCall(file=path, line=line, method=helper_method, url=helper_url))
                    mod.http_calls.append({"method": helper_method, "url": helper_url, "line": line})
            # request-config objects: client.post({ url: '/api/x', ... }), __request(OpenAPI, { method: 'GET', url: '/x' }), axios({ method, url })
            cfg_obj = next((a for a in arg_nodes[:2] if a.type == "object"), None)
            if cfg_obj is not None and not (m and is_server_recv):
                props: dict[str, str] = {}
                for pair in cfg_obj.children:
                    if pair.type == "pair":
                        pkey = _txt(pair.child_by_field_name("key"), src).strip("'\"")
                        pval = _str_value(pair.child_by_field_name("value"), src)
                        if pkey in ("url", "method", "path") and pval is not None:
                            props[pkey] = pval
                cfg_url = props.get("url") or props.get("path")
                verb = re.search(r"\.(get|post|put|delete|patch)$", cn)
                cfg_method = (props.get("method") or (verb.group(1) if verb else "")).upper()
                if cfg_url and cfg_url.startswith(("/", "http", "${")) and (cfg_method or re.search(r"(request|axios|fetch|client|http|api)", cn, re.I)):
                    res.client_calls.append(ClientCall(file=path, line=line, method=cfg_method or "GET", url=cfg_url))
                    mod.http_calls.append({"method": cfg_method or "GET", "url": cfg_url, "line": line})
            # prisma / mongoose / generic db ops
            pm = re.match(r"^(?:\w+\.)*(prisma|db|tx|client)\.(\w+)\.(\w+)$", cn)
            if pm and pm.group(3) in _PRISMA_OPS:
                res.db_operations.append(DbOperation(file=path, line=line, operation=_PRISMA_OPS[pm.group(3)], target=pm.group(2)))
            elif (mo := re.match(r"^([A-Z]\w+)\.(\w+)$", cn)) and mo.group(2) in _MONGOOSE_OPS:
                res.db_operations.append(DbOperation(file=path, line=line, operation=_MONGOOSE_OPS[mo.group(2)], target=mo.group(1)))
            elif re.match(r"^(?:\w+\.)*(pool|db|client|knex|connection|conn|sql|pg)\.(query|execute|raw)$", cn) and first is not None:
                q = _str_value(first, src)
                dyn = first.type == "template_string" and "${" in _txt(first, src) or first.type == "binary_expression"
                res.db_operations.append(DbOperation(file=path, line=line, operation="raw_sql", snippet=(q or "<dynamic>")[:200] if not dyn else "<dynamically built SQL>", raw_sql=True))
            # mongoose models
            if cn in {"mongoose.model", "model"} and first is not None and (mname := _str_value(first, src)):
                res.db_models.append(DbModel(name=mname, orm="Mongoose", file=path, line=line, table=mname.lower() + "s"))
            if cn.endswith(".define") and first is not None and (mname := _str_value(first, src)) and "sequelize" in cn.lower():
                fields = []
                if len(arg_nodes) > 1 and arg_nodes[1].type == "object":
                    for pair in arg_nodes[1].children:
                        if pair.type == "pair":
                            fields.append(DbField(name=_txt(pair.child_by_field_name("key"), src), type=re.sub(r"\s+", " ", _txt(pair.child_by_field_name("value"), src))[:60], line=pair.start_point[0] + 1))
                res.db_models.append(DbModel(name=mname, orm="Sequelize", file=path, line=line, fields=fields))
        elif n.type == "member_expression":
            t = _txt(n, src)
            m = re.match(r"^(?:process\.env|import\.meta\.env)\.([A-Z_][A-Z0-9_]*)$", t)
            if m:
                mod.env_vars.append((m.group(1), n.start_point[0] + 1))
        elif n.type == "subscript_expression":
            t = _txt(n, src)
            m = re.match(r"^process\.env\[['\"]([A-Z_][A-Z0-9_]*)['\"]\]$", t)
            if m:
                mod.env_vars.append((m.group(1), n.start_point[0] + 1))
        elif n.type in {"string", "template_string"}:
            v = _txt(n, src)[1:-1]
            if SQL_RE.match(v) and len(v) > 12:
                mod.string_literals_sql.append((v[:200], n.start_point[0] + 1))
        elif n.type == "new_expression" and _txt(n, src).startswith(("new Schema(", "new mongoose.Schema(")):
            mod.roles.append("data-model")

    # Next.js file-based routes
    if (m := _NEXT_ROUTE.search(path)) is not None:
        route_path = _file_route_path(m.group(1))
        for sym in mod.symbols:
            if sym.parent is None and sym.name in {"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"} and sym.exported:
                res.routes.append(Route(method=sym.name, path=route_path, handler=sym.name, file=path, line=sym.line_start, framework="Next.js Route Handler",
                                        calls=sym.calls[:25], resolved_prefix=True, auth=[c for c in sym.calls if _AUTH_HINT.search(c)]))
    elif (m := _NEXT_PAGES_API.search(path)) is not None:
        route_path = "/api" + _file_route_path(m.group(1))
        methods = sorted(set(re.findall(r"req\.method\s*===?\s*['\"](\w+)['\"]", text))) or ["ANY"]
        line = next((s.line_start for s in mod.symbols if s.name in {"handler", "default"}), 1)
        for meth in methods:
            res.routes.append(Route(method=meth.upper(), path=route_path, handler="default", file=path, line=line, framework="Next.js API Route", resolved_prefix=True))

    # GraphQL schema / resolvers hint
    if "gql`" in text or "typeDefs" in text:
        for mm in re.finditer(r"\b(type\s+(Query|Mutation|Subscription))\s*\{([^}]*)\}", text):
            for fm in re.finditer(r"^\s*(\w+)\s*[(:]", mm.group(3), re.M):
                line = text.count("\n", 0, mm.start()) + 1
                res.routes.append(Route(method=mm.group(2).upper(), path=fm.group(1), file=path, line=line, framework="GraphQL", kind="graphql", resolved_prefix=True))
    if re.search(r"\bio\.on\(\s*['\"]connection['\"]|new\s+WebSocketServer|socket\.on\(", text):
        for mm in re.finditer(r"socket\.on\(\s*['\"]([\w:\-]+)['\"]", text):
            res.routes.append(Route(method="WS", path=mm.group(1), file=path, line=text.count("\n", 0, mm.start()) + 1, framework="WebSocket", kind="websocket", resolved_prefix=True))

    mod.exports = sorted(set(mod.exports))
    mod.roles = sorted(set(mod.roles + _infer_roles(path, mod, res)))
    return res


def _walk(node: Node):  # type: ignore[no-untyped-def]
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def _types(node: Node) -> set[str]:
    out: set[str] = set()
    for i, n in enumerate(_walk(node)):
        out.add(n.type)
        if i > 4000:
            break
    return out


def _infer_roles(path: str, mod: ModuleInfo, res: ParseResult) -> list[str]:
    roles: list[str] = []
    low = path.lower()
    if res.routes:
        roles.append("api-routes")
    if res.db_models:
        roles.append("data-model")
    if res.db_operations:
        roles.append("data-access")
    if res.client_calls:
        roles.append("api-client")
    if any(s.kind == "component" for s in mod.symbols) or re.search(r"(^|/)components?/", low):
        roles.append("ui-component")
    if re.search(r"(^|/)(app|pages)/.*(page|layout)\.[jt]sx?$", low) or re.search(r"(^|/)pages/(?!api/).*\.[jt]sx$", low):
        roles.append("page")
    if any(s.kind == "hook" for s in mod.symbols) or "/hooks/" in low:
        roles.append("hook")
    if re.search(r"(store|slice|reducer|context|atom)s?[./]", low):
        roles.append("state")
    for key, role in (("service", "service"), ("controller", "controller"), ("middleware", "middleware"), ("auth", "auth"),
                      ("util", "utility"), ("helper", "utility"), ("lib/", "utility"), ("worker", "worker"), ("job", "worker"),
                      ("config", "config"), ("schema", "schema"), ("model", "data-model"), ("types", "types"), ("repositor", "repository"),
                      ("/api/", "api-client" if not res.routes else "api-routes")):
        if key in low:
            roles.append(role)
    return roles
