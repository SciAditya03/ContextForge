"""Layers 3-5: route resolution, client/API matching, architecture layers, env and dependency usage."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import PurePosixPath

from app.schemas.facts import (
    ArchitectureComponent,
    ClientCall,
    DbModel,
    Dependency,
    EnvVar,
    EvidenceClass,
    FileCategory,
    FileRecord,
    ModuleInfo,
    Route,
    SourceRef,
    Technology,
)
from app.services.architecture.graph import ImportResolver
from app.services.parsing.base import ParseResult, join_paths, normalize_url_template, route_pattern_key

# distribution name -> import name(s)
PY_IMPORT_NAMES: dict[str, list[str]] = {
    "python-jose": ["jose"], "pyjwt": ["jwt"], "pyyaml": ["yaml"], "beautifulsoup4": ["bs4"], "pillow": ["PIL"],
    "scikit-learn": ["sklearn"], "python-dotenv": ["dotenv"], "psycopg2-binary": ["psycopg2"], "python-multipart": ["multipart"],
    "pydantic-settings": ["pydantic_settings"], "opencv-python": ["cv2"], "attrs": ["attr", "attrs"], "google-generativeai": ["google"],
    "google-genai": ["google"], "sentry-sdk": ["sentry_sdk"], "mysqlclient": ["MySQLdb"], "pymysql": ["pymysql"],
    "argon2-cffi": ["argon2"], "email-validator": ["email_validator"], "typing-extensions": ["typing_extensions"],
    "sqlalchemy": ["sqlalchemy"], "flask-sqlalchemy": ["flask_sqlalchemy"], "djangorestframework": ["rest_framework"],
    "fastapi-users": ["fastapi_users"], "passlib": ["passlib"], "bcrypt": ["bcrypt"],
}
# packages that are normally used via CLI/config, not import
NON_IMPORTED = re.compile(
    r"^(uvicorn|gunicorn|hypercorn|pytest.*|black|ruff|mypy|flake8|isort|coverage|tox|pre-commit|pylint|types-.*|"
    r"@types/.*|typescript|eslint.*|prettier.*|@typescript-eslint/.*|ts-node|tsx|nodemon|vite|webpack.*|esbuild|turbo|"
    r"tailwindcss|postcss|autoprefixer|@tailwindcss/.*|jest|vitest|@vitest/.*|@playwright/test|cypress|concurrently|rimraf|"
    r"cross-env|husky|lint-staged|@biomejs/biome|psycopg2(-binary)?|asyncpg|pymysql|mysqlclient|aiosqlite|pg|mysql2|sqlite3|"
    r"alembic|prisma|wheel|setuptools|pip|poetry.*|hatch.*|mkdocs.*|sphinx.*|ipython|jupyter.*|notebook|"
    r"@next/.*|eslint-config-.*|babel-.*|@babel/.*|sass|less|.*-loader|.*-plugin.*|gevent|eventlet|python-multipart|email-validator|"
    r"next|react-dom|@vitejs/.*|@sveltejs/.*|@nestjs/cli|nest-cli|@prisma/client|bcrypt|tw-animate-css)$",
    re.I,
)


_PLACEHOLDER = re.compile(r"(?<!\$)\{([A-Za-z_][\w.]*)\}")  # Python f-string style only; JS ${...} is left alone
_AUTH_DEP = re.compile(r"(auth|user|token|login|permission|jwt|oauth|session_user|admin|scope|role|verify|api_key|superuser|current)", re.I)


def project_constants(results: list[ParseResult]) -> dict[str, str]:
    """Constants with a single unambiguous value across the project (e.g. ``API_V1_STR = "/api/v1"``)."""
    values: dict[str, set[str]] = defaultdict(set)
    for r in results:
        for k, v in r.constants.items():
            if k.isupper() or k.endswith(("_PREFIX", "_URL", "_PATH", "_STR", "_ROOT")):
                values[k].add(v)
    return {k: next(iter(v)) for k, v in values.items() if len(v) == 1}


def resolve_placeholders(text: str, constants: dict[str, str]) -> str:
    """Replace ``{settings.API_V1_STR}`` with the constant's literal value when it is known."""
    def repl(m: re.Match[str]) -> str:
        key = m.group(1).split(".")[-1]
        return constants.get(key, m.group(0))

    return _PLACEHOLDER.sub(repl, text)


def apply_dependency_aliases(routes: list[Route], results: list[ParseResult]) -> None:
    """FastAPI ``CurrentUser = Annotated[User, Depends(get_current_user)]`` aliases used as parameter annotations."""
    aliases: dict[str, str] = {}
    for r in results:
        aliases.update(r.dep_aliases)
    if not aliases:
        return
    for rt in routes:
        for pname, ann in rt.param_annotations.items():
            base = ann.split("[")[0].split(".")[-1].strip()
            dep = aliases.get(base)
            if dep is None:
                continue
            rt.params = [p for p in rt.params if not p.startswith(f"{pname}:") and p != pname]
            if rt.body_model == ann:
                rt.body_model = None
            target = rt.auth if (_AUTH_DEP.search(dep) or _AUTH_DEP.search(base)) and not re.search(r"(get_db|session$|SessionDep)", dep + base) else rt.calls
            if dep not in target:
                target.append(dep)
        if rt.body_model is None:
            # the first remaining non-path, non-primitive annotated parameter is the request body
            for pname, ann in rt.param_annotations.items():
                base = ann.split("[")[0].split(".")[-1]
                if base in aliases or "{" + pname + "}" in rt.path or not ann[:1].isupper() or base in {"Request", "Response", "Session", "AsyncSession", "BackgroundTasks", "UploadFile", "WebSocket", "Optional", "Any"}:
                    continue
                if any(p.startswith(f"{pname}:") for p in rt.params):
                    rt.body_model = ann
                    rt.params = [p for p in rt.params if not p.startswith(f"{pname}:")]
                break


def resolve_routes(results: list[ParseResult], resolver: ImportResolver) -> list[Route]:
    """Apply APIRouter / Blueprint / express.Router prefixes and mount prefixes."""
    by_file = {r.module.path: r for r in results}
    constants = project_constants(results)
    # (file, router_var) -> list of mount prefixes (from parents)
    mounts: dict[tuple[str, str], list[tuple[str, str, str]]] = defaultdict(list)  # -> [(parent_file, parent_var, prefix)]

    def target_of(r: ParseResult, expr: str) -> tuple[str, str] | None:
        expr = expr.strip()
        parts = expr.split(".")
        alias = parts[0]
        if alias in r.import_aliases:
            module = r.import_aliases[alias]
            lang = r.module.language
            from app.schemas.facts import ImportRef

            if lang == "Python":
                # "items.router" -> module "<pkg>.items", var "router";  "router" -> module "<pkg>.items.router"
                if len(parts) > 1:
                    imp = ImportRef(file=r.module.path, module=module, names=[], line=0)
                    resolver.resolve(imp, lang)
                    return (imp.resolved, parts[1]) if imp.resolved else None
                mod_path, _, attr = module.rpartition(".")
                imp = ImportRef(file=r.module.path, module=mod_path, names=[attr], line=0)
                resolver.resolve(imp, lang)
                return (imp.resolved, attr) if imp.resolved else None
            imp = ImportRef(file=r.module.path, module=module, names=[], line=0)
            resolver.resolve(imp, lang)
            if imp.resolved:
                tgt = by_file.get(imp.resolved)
                var: str | None = parts[1] if len(parts) > 1 else None
                if var is None and tgt is not None:
                    # default export of an express Router file: pick its router variable
                    rv = [rt.router_var for rt in tgt.routes if rt.router_var]
                    var = rv[0] if rv and rv[0] else "router"
                return (imp.resolved, var or "router")
            return None
        if len(parts) == 1:
            return (r.module.path, alias)
        return None

    for r in results:
        for m in r.mounts:
            tgt = target_of(r, m.target_expr)
            if tgt:
                # which variable in r does the mount call belong to? (best effort: app or main router)
                mounts[tgt].append((r.module.path, _mount_owner(r), resolve_placeholders(m.prefix, constants)))

    def full_prefix(file: str, var: str | None, depth: int = 0) -> str:
        if depth > 6 or var is None:
            return ""
        r = by_file.get(file)
        own = resolve_placeholders(r.router_prefixes.get(var, ""), constants) if r else ""
        parents = mounts.get((file, var), [])
        if not parents:
            return own
        pf, pv, mp = parents[0]
        return join_paths(full_prefix(pf, pv, depth + 1), mp, own)

    out: list[Route] = []
    for r in results:
        for rt in r.routes:
            if not rt.resolved_prefix and rt.kind in ("http", "websocket"):
                pre = full_prefix(rt.file, rt.router_var)
                original = rt.path
                rt.path = join_paths(pre, rt.path) if pre else (rt.path if rt.path.startswith("/") else "/" + rt.path)
                # FastAPI/Flask concatenate prefix + path literally, so a trailing slash is significant there
                if rt.framework in ("FastAPI", "Flask") and original.endswith("/") and not rt.path.endswith("/"):
                    rt.path += "/"
                rt.resolved_prefix = True
            out.append(rt)
    apply_dependency_aliases(out, results)
    return sorted(out, key=lambda x: (x.path, x.method))


def _mount_owner(r: ParseResult) -> str:
    for var, pre in r.router_prefixes.items():
        if pre == "" and var in {"app", "application", "api"}:
            return var
    if r.router_prefixes:
        return next(iter(r.router_prefixes))
    return "app"


def match_client_calls(calls: list[ClientCall], routes: list[Route], constants: dict[str, str] | None = None) -> list[ClientCall]:
    index: dict[str, list[Route]] = defaultdict(list)
    for rt in routes:
        if rt.kind == "http":
            index[route_pattern_key(rt.path)].append(rt)
    for c in calls:
        norm = normalize_url_template(resolve_placeholders(c.url, constants or {}))
        key = route_pattern_key(norm.replace(":param", ":p"))
        cands = index.get(key, [])
        if not cands:
            # tolerate a prefix difference introduced by a proxy rewrite (e.g. frontend `/api/x` -> backend `/x`),
            # but only when the shared suffix has at least two path segments
            for k, rts in index.items():
                shorter = key if len(key) < len(k) else k
                if shorter.count("/") >= 2 and (k.endswith(key) or key.endswith(k)):
                    cands = rts
                    break
        hit = next((r for r in cands if r.method in (c.method, "ANY")), None) or (cands[0] if cands else None)
        if hit:
            c.matched_route = f"{hit.method} {hit.path}"
    return calls


LAYER_RULES: list[tuple[str, set[str], re.Pattern[str] | None]] = [
    ("frontend", {"ui-component", "page", "hook"}, re.compile(r"(^|/)(frontend|client|web|ui|app/\(.*\)|components|pages|views|screens)/", re.I)),
    ("api", {"api-routes", "controller"}, re.compile(r"(^|/)(api|routes|routers|controllers|endpoints|handlers)/", re.I)),
    ("service", {"service"}, re.compile(r"(^|/)(services?|usecases?|domain|core|business)/", re.I)),
    ("data", {"data-model", "data-access", "repository"}, re.compile(r"(^|/)(models?|entities|repositor(y|ies)|db|database|dao|prisma|migrations?)/", re.I)),
    ("schema", {"schema", "types"}, re.compile(r"(^|/)(schemas?|types|dto|dtos|interfaces)/", re.I)),
    ("auth", {"auth"}, re.compile(r"(auth|security|permissions?|jwt|session|login)", re.I)),
    ("middleware", {"middleware", "middleware-registration"}, re.compile(r"middleware", re.I)),
    ("worker", {"worker"}, re.compile(r"(^|/)(workers?|jobs?|tasks?|queues?|celery|cron)/", re.I)),
    ("state", {"state"}, re.compile(r"(^|/)(store|stores|state|redux|slices|contexts?)/", re.I)),
    ("api-client", {"api-client"}, re.compile(r"(^|/)(lib/api|api-client|services/api|client/api)", re.I)),
    ("config", {"config"}, re.compile(r"(^|/)(config|settings|core/config)", re.I)),
    ("utility", {"utility"}, re.compile(r"(^|/)(utils?|helpers?|lib|common|shared)/", re.I)),
]


def detect_components(modules: list[ModuleInfo], files: list[FileRecord], techs: list[Technology]) -> list[ArchitectureComponent]:
    comps: dict[str, ArchitectureComponent] = {}
    for m in modules:
        rec = next((f for f in files if f.path == m.path), None)
        if rec is not None and rec.category == FileCategory.TEST:
            comps.setdefault("test", ArchitectureComponent(layer="test", classification=EvidenceClass.DETECTED)).files.append(m.path)
            continue
        for layer, roles, pat in LAYER_RULES:
            role_hit = bool(roles & set(m.roles))
            path_hit = bool(pat and pat.search(m.path))
            if role_hit or path_hit:
                c = comps.setdefault(layer, ArchitectureComponent(layer=layer))
                c.files.append(m.path)
                if role_hit:
                    c.classification = EvidenceClass.DETECTED
                    reason = f"{m.path}: roles {sorted(roles & set(m.roles))}"
                else:
                    reason = f"{m.path}: path convention"
                if len(c.evidence) < 12:
                    c.evidence.append(reason)
    cats = defaultdict(list)
    for t in techs:
        cats[t.category].append(t.name)
    for cat, layer in (("cache", "cache"), ("queue", "worker"), ("logging", "logging"), ("storage", "storage"), ("deploy", "deploy"), ("integration", "integration"), ("cloud", "integration")):
        if cats.get(cat):
            c = comps.setdefault(layer, ArchitectureComponent(layer=layer, classification=EvidenceClass.INFERRED))
            c.evidence.append(f"technologies: {', '.join(sorted(set(cats[cat])))}")
    deploy_files = [f.path for f in files if f.category == FileCategory.DEPLOY and f.status == "included"]
    if deploy_files:
        comps.setdefault("deploy", ArchitectureComponent(layer="deploy", classification=EvidenceClass.DETECTED)).files.extend(deploy_files)
    return sorted(comps.values(), key=lambda c: c.layer)


def aggregate_env(env_defs: list[EnvVar], modules: list[ModuleInfo]) -> list[EnvVar]:
    by_name = {e.name: e for e in env_defs}
    for m in modules:
        for name, line in m.env_vars:
            ev = by_name.setdefault(name, EnvVar(name=name))
            if len(ev.used_in) < 20:
                ev.used_in.append(SourceRef(file=m.path, line_start=line))
    return sorted(by_name.values(), key=lambda e: e.name)


def mark_dependency_usage(deps: list[Dependency], modules: list[ModuleInfo], files: list[FileRecord]) -> None:
    """Mark ``used`` on direct dependencies (per subproject) by comparing with imported packages."""
    imported_by_root: dict[str, set[str]] = defaultdict(set)
    for m in modules:
        for imp in m.imports:
            if imp.package:
                imported_by_root["*"].add(imp.package.lower())
            top = imp.module.lstrip("/").split(".")[0].split("/")[0].lower()
            if imp.module.startswith("@"):
                top = "/".join(imp.module.split("/")[:2]).lower()
            if top:
                imported_by_root["*"].add(top)
    imported = imported_by_root["*"]
    # textual usage in config/build files (e.g. tailwind plugins in config)
    for d in deps:
        if d.ecosystem not in {"npm", "pypi"}:
            continue
        if NON_IMPORTED.match(d.name):
            d.used = None
            continue
        names = {d.name.lower(), d.name.lower().replace("-", "_")}
        names |= {n.lower() for n in PY_IMPORT_NAMES.get(d.name.lower(), [])}
        d.used = bool(names & imported)


def test_summary(files: list[FileRecord], techs: list[Technology], build_cmds: list[dict[str, str]]) -> dict[str, object]:
    tests = [f for f in files if f.category == FileCategory.TEST and f.status == "included"]
    by_dir: dict[str, int] = defaultdict(int)
    for f in tests:
        by_dir[str(PurePosixPath(f.path).parent)] += 1
    frameworks = sorted({t.name for t in techs if t.category == "testing"})
    cmds = [c for c in build_cmds if re.search(r"test|spec|e2e|lint|typecheck|check", c["name"] + " " + c["command"], re.I)]
    return {"test_files": len(tests), "directories": dict(sorted(by_dir.items())), "frameworks": frameworks, "commands": cmds,
            "test_lines": sum(f.lines for f in tests)}


def merge_db_models(models: list[DbModel]) -> list[DbModel]:
    """Collapse SQL DDL (usually migrations) describing a table that an ORM model already defines."""
    orm = [m for m in models if m.orm != "SQL DDL"]
    keyed: dict[str, DbModel] = {}
    for m in orm:
        keyed.setdefault((m.table or m.name).lower(), m)
        keyed.setdefault(m.name.lower(), m)
    out = list(orm)
    for m in models:
        if m.orm != "SQL DDL":
            continue
        hit = keyed.get((m.table or m.name).lower())
        if hit is not None:
            hit.also_defined_in.append(f"{m.file}:{m.line}")
            if not hit.fields and m.fields:
                hit.fields = m.fields
        else:
            out.append(m)
    return out
