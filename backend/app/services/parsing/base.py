"""Shared parse result types and helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.schemas.facts import ClientCall, DbModel, DbOperation, ModuleInfo, Route


def _parser_version() -> str:
    """Hash of the parser sources: any parser change invalidates the parse cache automatically."""
    import hashlib
    from pathlib import Path

    h = hashlib.sha256()
    for p in sorted(Path(__file__).parent.glob("*.py")) + [Path(__file__).parent.parent / "security" / "secrets.py"]:
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


PARSER_VERSION = _parser_version()

SQL_RE = re.compile(r"^\s*(SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|CREATE\s+TABLE|ALTER\s+TABLE|WITH)\b", re.I)
HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}


@dataclass
class RouterMount:
    """``app.include_router(x.router, prefix='/api')`` style mounts, resolved later."""

    file: str
    line: int
    target_expr: str  # e.g. "items.router" or "router"
    prefix: str


@dataclass
class ParseResult:
    module: ModuleInfo
    routes: list[Route] = field(default_factory=list)
    db_models: list[DbModel] = field(default_factory=list)
    db_operations: list[DbOperation] = field(default_factory=list)
    client_calls: list[ClientCall] = field(default_factory=list)
    router_prefixes: dict[str, str] = field(default_factory=dict)  # router variable -> prefix
    mounts: list[RouterMount] = field(default_factory=list)
    import_aliases: dict[str, str] = field(default_factory=dict)  # local name -> module path
    constants: dict[str, str] = field(default_factory=dict)  # module/class-level string constants (for prefix/URL resolution)
    dep_aliases: dict[str, str] = field(default_factory=dict)  # FastAPI `X = Annotated[T, Depends(fn)]` -> fn
    class_fields: dict[str, tuple[list[str], list[Any]]] = field(default_factory=dict)  # transient, not cached

    def to_json(self) -> str:
        return json.dumps({
            "module": self.module.model_dump(mode="json"),
            "routes": [r.model_dump(mode="json") for r in self.routes],
            "db_models": [m.model_dump(mode="json") for m in self.db_models],
            "db_operations": [o.model_dump(mode="json") for o in self.db_operations],
            "client_calls": [c.model_dump(mode="json") for c in self.client_calls],
            "router_prefixes": self.router_prefixes,
            "mounts": [m.__dict__ for m in self.mounts],
            "import_aliases": self.import_aliases,
            "constants": self.constants,
            "dep_aliases": self.dep_aliases,
        })

    @classmethod
    def from_json(cls, raw: str) -> ParseResult:
        d = json.loads(raw)
        return cls(
            module=ModuleInfo.model_validate(d["module"]),
            routes=[Route.model_validate(x) for x in d["routes"]],
            db_models=[DbModel.model_validate(x) for x in d["db_models"]],
            db_operations=[DbOperation.model_validate(x) for x in d["db_operations"]],
            client_calls=[ClientCall.model_validate(x) for x in d["client_calls"]],
            router_prefixes=d["router_prefixes"],
            mounts=[RouterMount(**m) for m in d["mounts"]],
            import_aliases=d["import_aliases"],
            constants=d.get("constants", {}),
            dep_aliases=d.get("dep_aliases", {}),
        )


def normalize_url_template(url: str) -> str:
    """Turn ``${API}/users/${id}`` or f-string remnants into ``/users/:param``."""
    u = url.strip()
    u = re.sub(r"^\$\{[^}]*\}", "", u)  # leading base-url variable
    u = re.sub(r"^\{[^}]*\}", "", u)
    u = re.sub(r"^https?://[^/]+", "", u)
    u = re.sub(r"\$\{[^}]*\}|\{[^}]*\}", ":param", u)
    u = u.split("?", 1)[0]
    if not u.startswith("/"):
        u = "/" + u
    return u


def route_pattern_key(path: str) -> str:
    """Canonicalize a route path for matching: params become ``:p``."""
    p = re.sub(r"\{[^}]+\}|:[A-Za-z_][A-Za-z0-9_]*|\[[^\]]+\]|<[^>]+>|\*", ":p", path)
    p = re.sub(r"/+", "/", p).rstrip("/")
    return p or "/"


def join_paths(*parts: str) -> str:
    out = "/".join(p.strip("/") for p in parts if p and p.strip("/"))
    return "/" + out if out else "/"
