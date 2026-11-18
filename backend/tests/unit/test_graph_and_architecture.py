from pathlib import Path

from app.schemas.facts import ConfigFile, FileRecord, ImportRef
from app.services.architecture.analyzer import match_client_calls, resolve_routes
from app.services.architecture.graph import ImportResolver, build_graph, find_cycles
from app.services.parsing.python_parser import parse_python
from app.services.parsing.ts_parser import parse_typescript


def _rec(p: str) -> FileRecord:
    return FileRecord(path=p, size=1, language="Python" if p.endswith(".py") else "TypeScript")


def test_python_and_ts_import_resolution():
    files = [_rec(p) for p in ("backend/app/__init__.py", "backend/app/db.py", "backend/app/api/items.py", "web/src/lib/api.ts", "web/src/components/Card.tsx", "web/tsconfig.json")]
    cfg = [ConfigFile(path="web/tsconfig.json", kind="typescript", summary={"baseUrl": ".", "paths": {"@/*": ["./src/*"]}})]
    r = ImportResolver(files, cfg)
    rel = ImportRef(file="backend/app/api/items.py", module="/backend.app.db", names=["get_db"], line=1)
    r.resolve(rel, "Python")
    assert rel.resolved == "backend/app/db.py"
    absolute = ImportRef(file="backend/app/api/items.py", module="app.db", names=["x"], line=1)
    r.resolve(absolute, "Python")
    assert absolute.resolved == "backend/app/db.py"
    ext = ImportRef(file="backend/app/api/items.py", module="fastapi", names=["FastAPI"], line=1)
    r.resolve(ext, "Python")
    assert ext.external and ext.package == "fastapi"
    std = ImportRef(file="backend/app/api/items.py", module="os.path", names=["join"], line=1)
    r.resolve(std, "Python")
    assert not std.external and std.package is None
    alias = ImportRef(file="web/src/components/Card.tsx", module="@/lib/api", line=1)
    r.resolve(alias, "TypeScript")
    assert alias.resolved == "web/src/lib/api.ts"
    relts = ImportRef(file="web/src/components/Card.tsx", module="../lib/api", line=1)
    r.resolve(relts, "TypeScript")
    assert relts.resolved == "web/src/lib/api.ts"
    scoped = ImportRef(file="web/src/components/Card.tsx", module="@tanstack/react-query/build", line=1)
    r.resolve(scoped, "TypeScript")
    assert scoped.package == "@tanstack/react-query"


def test_cycle_detection():
    adj = {"a": ["b"], "b": ["c"], "c": ["a"], "d": ["a"], "e": []}
    assert find_cycles(adj) == [["a", "b", "c"]]


def test_route_prefix_resolution_across_files():
    main = parse_python("app/main.py", "from fastapi import FastAPI\nfrom app.api import items\napp = FastAPI()\napp.include_router(items.router, prefix='/api')\n")
    items = parse_python("app/api/items.py", "from fastapi import APIRouter\nrouter = APIRouter(prefix='/items')\n@router.get('/{id}')\ndef get(id: int):\n    pass\n")
    files = [_rec("app/main.py"), _rec("app/api/items.py"), _rec("app/api/__init__.py"), _rec("app/__init__.py")]
    resolver = ImportResolver(files, [])
    routes = resolve_routes([main, items], resolver)
    assert [(r.method, r.path) for r in routes] == [("GET", "/api/items/{id}")]


def test_express_mount_and_client_matching():
    idx = parse_typescript("src/index.ts", "import express from 'express';\nimport users from './routes/users';\nconst app = express();\napp.use('/api/users', users);\n")
    users = parse_typescript("src/routes/users.ts", "import { Router } from 'express';\nconst router = Router();\nrouter.get('/:id', (req, res) => res.json({}));\nexport default router;\n")
    files = [FileRecord(path=p, size=1, language="TypeScript") for p in ("src/index.ts", "src/routes/users.ts")]
    routes = resolve_routes([idx, users], ImportResolver(files, []))
    assert [(r.method, r.path) for r in routes] == [("GET", "/api/users/:id")]
    client = parse_typescript("web/api.ts", "export const get = (id) => fetch(`${BASE}/api/users/${id}`);\nexport const del = () => fetch('/api/nothing', { method: 'DELETE' });\n")
    calls = match_client_calls(client.client_calls, routes)
    assert calls[0].matched_route == "GET /api/users/:id"
    assert calls[1].matched_route is None


def test_build_graph_nodes_and_edges(tmp_path: Path):
    a = parse_python("pkg/a.py", "from pkg import b\nimport requests\n")
    b = parse_python("pkg/b.py", "from pkg import a\n")
    files = [_rec("pkg/a.py"), _rec("pkg/b.py"), _rec("pkg/__init__.py")]
    resolver = ImportResolver(files, [])
    for m in (a.module, b.module):
        for i in m.imports:
            resolver.resolve(i, "Python")
    g = build_graph([a.module, b.module], files)
    assert any(e.source == "pkg/a.py" and e.target == "pkg/b.py" for e in g.edges)
    assert any(n.id == "pkg:requests" and n.type == "external" for n in g.nodes)
    assert g.cycles == [["pkg/a.py", "pkg/b.py"]]
