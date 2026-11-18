"""Layer 1: technology stack, configuration and environment detection."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

import yaml

from app.schemas.facts import (
    ConfigFile,
    Dependency,
    EnvVar,
    EvidenceClass,
    FileRecord,
    RepositoryOverview,
    SourceRef,
    Technology,
)
from app.services.dependency.knowledge import DEPLOY_FILE_TECH, lookup_image, lookup_package
from app.services.dependency.manifests import ManifestInfo

_ENV_LINE = re.compile(r"^\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$")


class TechCollector:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], Technology] = {}

    def add(self, name: str, category: str, ref: SourceRef | None, cls: EvidenceClass = EvidenceClass.DETECTED, version: str | None = None, note: str | None = None) -> None:
        key = (name, category)
        t = self.items.get(key)
        if t is None:
            t = Technology(name=name, category=category, classification=cls, version=version, note=note)
            self.items[key] = t
        else:
            if cls == EvidenceClass.DETECTED:
                t.classification = EvidenceClass.DETECTED
            t.version = t.version or version
        if ref and len(t.evidence) < 8 and all(e.file != ref.file or e.line_start != ref.line_start for e in t.evidence):
            t.evidence.append(ref)

    def list(self) -> list[Technology]:
        order = ["language", "runtime", "framework", "ui", "styling", "state", "orm", "database", "cache", "queue", "auth",
                 "validation", "http_client", "realtime", "integration", "ai", "ml", "cloud", "storage", "logging", "middleware",
                 "config", "migration", "testing", "build", "package_manager", "deploy", "worker", "library"]
        return sorted(self.items.values(), key=lambda t: (order.index(t.category) if t.category in order else 99, t.name))


def detect_stack(
    root: Path,
    overview: RepositoryOverview,
    files: list[FileRecord],
    manifests: list[ManifestInfo],
) -> tuple[list[Technology], list[Dependency], list[ConfigFile], list[EnvVar], list[dict[str, str]], list[str]]:
    tc = TechCollector()
    warnings: list[str] = []
    deps: list[Dependency] = []
    configs: list[ConfigFile] = []
    build_cmds: list[dict[str, str]] = []

    for lang, stats in overview.languages.items():
        if lang in {"Markdown", "Text", "JSON", "YAML", "TOML", "INI", "XML", "reStructuredText", "Env"}:
            continue
        sample = next((f.path for f in files if f.language == lang and f.status == "included"), None)
        tc.add(lang, "language", SourceRef(file=sample) if sample else None, note=f"{stats['files']} files, {stats['code_lines']} code lines")

    for m in manifests:
        if m.package_manager:
            tc.add(m.package_manager, "package_manager", SourceRef(file=m.path))
        for rt, ver in m.runtime.items():
            label = {"node": "Node.js", "python": "Python", "go": "Go", "java": "Java", "php": "PHP", "ruby": "Ruby"}.get(rt, rt)
            tc.add(label, "runtime", SourceRef(file=m.path), version=ver)
        if m.ecosystem == "javascript":
            tc.add("Node.js", "runtime", SourceRef(file=m.path), cls=EvidenceClass.INFERRED, note="implied by package.json")
        for d in m.dependencies:
            hit = lookup_package(d.name)
            if hit:
                d.category = hit[1]
                tc.add(hit[0], hit[1], SourceRef(file=m.path, line_start=d.line), version=d.version)
            deps.append(d)
        for sname, cmd in m.scripts.items():
            build_cmds.append({"source": m.path, "name": sname, "command": cmd})

    by_name = {PurePosixPath(f.path).name: f for f in files if f.status == "included"}
    included = [f for f in files if f.status == "included"]

    # Deploy platforms by marker file
    for f in included:
        name = PurePosixPath(f.path).name
        if name in DEPLOY_FILE_TECH:
            t = DEPLOY_FILE_TECH[name]
            tc.add(t[0], t[1], SourceRef(file=f.path))
        if f.path.startswith(".github/workflows/"):
            tc.add("GitHub Actions", "deploy", SourceRef(file=f.path))
        if f.path.startswith(".gitlab-ci"):
            tc.add("GitLab CI", "deploy", SourceRef(file=f.path))
        if f.path.endswith(".tf"):
            tc.add("Terraform", "deploy", SourceRef(file=f.path))
            text = _read(root, f.path, 200_000)
            for prov in set(re.findall(r'provider\s+"([a-z0-9_]+)"', text)):
                cloud = {"aws": "AWS", "google": "Google Cloud", "azurerm": "Azure", "cloudflare": "Cloudflare"}.get(prov)
                if cloud:
                    tc.add(cloud, "cloud", SourceRef(file=f.path))
        if name.startswith("Dockerfile") or name == "Containerfile":
            tc.add("Docker", "deploy", SourceRef(file=f.path))
            text = _read(root, f.path, 100_000)
            for i, line in enumerate(text.splitlines(), 1):
                mm = re.match(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)", line, re.I)
                if mm:
                    hit = lookup_image(mm.group(1))
                    if hit:
                        tc.add(hit[0], hit[1], SourceRef(file=f.path, line_start=i), version=mm.group(1).split(":")[-1] if ":" in mm.group(1) else None)
                    else:
                        tc.add(f"Base image {mm.group(1)}", "deploy", SourceRef(file=f.path, line_start=i))
                mm = re.match(r"^\s*(CMD|ENTRYPOINT)\s+(.*)$", line)
                if mm:
                    build_cmds.append({"source": f.path, "name": mm.group(1).lower(), "command": mm.group(2).strip()})
        if name in {"docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"}:
            tc.add("Docker Compose", "deploy", SourceRef(file=f.path))
            text = _read(root, f.path, 200_000)
            try:
                data = yaml.safe_load(text) or {}
                services = data.get("services", {}) or {}
                summary: dict[str, object] = {}
                for sname, svc in services.items():
                    if not isinstance(svc, dict):
                        continue
                    img = svc.get("image")
                    summary[sname] = {"image": img, "build": svc.get("build"), "ports": svc.get("ports"), "depends_on": svc.get("depends_on")}
                    if img and (hit := lookup_image(str(img))):
                        img_line = next((n for n, ln in enumerate(text.splitlines(), 1) if str(img) in ln), None)
                        tc.add(hit[0], hit[1], SourceRef(file=f.path, line_start=img_line))
                configs.append(ConfigFile(path=f.path, kind="docker-compose", summary={"services": summary}))
            except yaml.YAMLError as exc:
                warnings.append(f"Could not parse {f.path}: {exc}")
        if name == "prisma" or f.path.endswith(".prisma"):
            text = _read(root, f.path, 200_000)
            mm = re.search(r'provider\s*=\s*"(postgresql|mysql|sqlite|mongodb|sqlserver|cockroachdb)"', text)
            if mm:
                db = {"postgresql": "PostgreSQL", "mysql": "MySQL", "sqlite": "SQLite", "mongodb": "MongoDB", "sqlserver": "SQL Server", "cockroachdb": "CockroachDB"}[mm.group(1)]
                tc.add(db, "database", SourceRef(file=f.path, line_start=text.count("\n", 0, mm.start()) + 1))
            tc.add("Prisma", "orm", SourceRef(file=f.path))

    # Config file summaries
    for f in included:
        name = PurePosixPath(f.path).name
        if name in {"tsconfig.json", "jsconfig.json"}:
            text = _read(root, f.path, 100_000)
            try:
                data = json.loads(re.sub(r"^\s*//.*$", "", text, flags=re.M))
                co = data.get("compilerOptions", {})
                configs.append(ConfigFile(path=f.path, kind="typescript", summary={k: co.get(k) for k in ("target", "module", "strict", "jsx", "baseUrl", "paths", "moduleResolution") if k in co}))
            except json.JSONDecodeError:
                configs.append(ConfigFile(path=f.path, kind="typescript", summary={"note": "JSONC not fully parseable"}))
        elif name.startswith(("next.config.", "vite.config.", "webpack.config.", "tailwind.config.", "postcss.config.", "nuxt.config.", "svelte.config.")):
            kind = name.split(".")[0]
            text = _read(root, f.path, 50_000)
            keys = sorted(set(re.findall(r"^\s{2,4}([a-zA-Z]+)\s*:", text, re.M)))[:20]
            configs.append(ConfigFile(path=f.path, kind=kind, summary={"top_level_keys": keys}))
            if kind == "next":
                tc.add("Next.js", "framework", SourceRef(file=f.path))
            if kind == "vite":
                tc.add("Vite", "build", SourceRef(file=f.path))
            if kind == "tailwind":
                tc.add("Tailwind CSS", "styling", SourceRef(file=f.path))
        elif name in {"alembic.ini"}:
            tc.add("Alembic", "migration", SourceRef(file=f.path))
            configs.append(ConfigFile(path=f.path, kind="alembic"))
        elif name in {"pytest.ini", "conftest.py", "jest.config.js", "jest.config.ts", "vitest.config.ts", "playwright.config.ts"}:
            kind = name.split(".")[0]
            configs.append(ConfigFile(path=f.path, kind=kind))
        elif name in {"application.properties", "application.yml", "application.yaml"}:
            text = _read(root, f.path, 50_000)
            keys = sorted(set(re.findall(r"^([a-z][a-z0-9.\-]+)\s*[=:]", text, re.M)))[:30]
            configs.append(ConfigFile(path=f.path, kind="spring", summary={"keys": keys}))
            if "spring.datasource.url" in text and (mm := re.search(r"jdbc:(\w+):", text)):
                tc.add({"postgresql": "PostgreSQL", "mysql": "MySQL", "h2": "H2", "mariadb": "MariaDB"}.get(mm.group(1), mm.group(1)), "database", SourceRef(file=f.path))
        elif f.category.value in {"config", "build"} and f.path not in {c.path for c in configs}:
            configs.append(ConfigFile(path=f.path, kind=f.category.value))

    # Makefile targets
    if (mk := by_name.get("Makefile")) is not None:
        text = _read(root, mk.path, 100_000)
        for mm in re.finditer(r"^([a-zA-Z0-9_\-]+):(?!=)", text, re.M):
            build_cmds.append({"source": mk.path, "name": mm.group(1), "command": f"make {mm.group(1)}"})

    # Environment variable templates
    env_vars: dict[str, EnvVar] = {}
    for f in included:
        if f.category.value in ("env_template",):
            text = _read(root, f.path, 100_000)
            for i, line in enumerate(text.splitlines(), 1):
                mm = _ENV_LINE.match(line)
                if mm:
                    ev = env_vars.setdefault(mm.group(1), EnvVar(name=mm.group(1)))
                    ev.defined_in.append(SourceRef(file=f.path, line_start=i))
                    ev.has_default = ev.has_default or bool(mm.group(2).strip())
        if f.category.value == "env_file":
            text = _read(root, f.path, 100_000)
            for i, line in enumerate(text.splitlines(), 1):
                mm = _ENV_LINE.match(line)
                if mm:
                    ev = env_vars.setdefault(mm.group(1), EnvVar(name=mm.group(1)))
                    ev.defined_in.append(SourceRef(file=f.path, line_start=i))

    # Environment variable references inside config/deploy/schema files (docker-compose ${VAR}, prisma env("VAR"), ...)
    for f in included:
        if f.category.value not in ("deploy", "config", "schema", "build") or f.size > 500_000:
            continue
        text = _read(root, f.path, 500_000)
        for i, line in enumerate(text.splitlines(), 1):
            for mm in re.finditer(r"\$\{([A-Z_][A-Z0-9_]*)(?::?-[^}]*)?\}|\benv\(\s*[\"']([A-Z_][A-Z0-9_]*)[\"']\s*\)", line):
                name = mm.group(1) or mm.group(2)
                ev = env_vars.setdefault(name, EnvVar(name=name))
                if len(ev.used_in) < 20:
                    ev.used_in.append(SourceRef(file=f.path, line_start=i))

    # Inferred: frameworks implied by file conventions
    paths = [f.path for f in included]
    if any(re.search(r"(^|/)app/(.*/)?page\.[jt]sx$", p) for p in paths):
        tc.add("Next.js App Router", "framework", SourceRef(file=next(p for p in paths if re.search(r"(^|/)app/(.*/)?page\.[jt]sx$", p))), cls=EvidenceClass.INFERRED, note="app/**/page.tsx convention")
    if any(p.endswith("manage.py") for p in paths):
        tc.add("Django", "framework", SourceRef(file=next(p for p in paths if p.endswith("manage.py"))), cls=EvidenceClass.INFERRED)
    if any(PurePosixPath(p).name in {"pytest.ini", "conftest.py"} for p in paths):
        tc.add("pytest", "testing", SourceRef(file=next(p for p in paths if PurePosixPath(p).name in {"pytest.ini", "conftest.py"})), cls=EvidenceClass.INFERRED)

    return tc.list(), deps, configs, list(env_vars.values()), build_cmds, warnings


def _read(root: Path, rel: str, limit: int) -> str:
    try:
        with open(root / rel, "rb") as fh:
            return fh.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return ""
