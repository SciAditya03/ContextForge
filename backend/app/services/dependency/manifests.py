"""Layer 1: dependency manifest parsing (no code is ever executed)."""

from __future__ import annotations

import json
import re
import tomllib
import xml.etree.ElementTree as ET  # noqa: S405 - DTD/entities rejected before parsing
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from app.schemas.facts import Dependency


@dataclass
class ManifestInfo:
    path: str
    ecosystem: str
    dependencies: list[Dependency] = field(default_factory=list)
    scripts: dict[str, str] = field(default_factory=dict)
    runtime: dict[str, str] = field(default_factory=dict)  # e.g. {"python": ">=3.11"}
    package_manager: str | None = None
    name: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _line_of(text: str, needle: str) -> int | None:
    idx = text.find(needle)
    if idx < 0:
        return None
    return text.count("\n", 0, idx) + 1


_REQ_LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._\-]*)(\[[^\]]*\])?\s*([<>=!~^][^;#]*)?")


def parse_requirement(spec: str) -> tuple[str, str | None] | None:
    m = _REQ_LINE.match(spec)
    if not m:
        return None
    ver = (m.group(3) or "").strip() or None
    return m.group(1).lower().replace("_", "-"), ver


def parse_requirements_txt(path: str, text: str) -> ManifestInfo:
    info = ManifestInfo(path, "python", package_manager="pip")
    dev = any(t in PurePosixPath(path).name for t in ("dev", "test"))
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith(("#", "-", "git+", "http")):
            continue
        r = parse_requirement(s)
        if r:
            info.dependencies.append(Dependency(name=r[0], version=r[1], ecosystem="pypi", manifest=path, line=i, dev=dev))
    return info


def parse_pyproject(path: str, text: str) -> ManifestInfo:
    info = ManifestInfo(path, "python")
    data = tomllib.loads(text)
    proj = data.get("project", {})
    info.name = proj.get("name")
    if rp := proj.get("requires-python"):
        info.runtime["python"] = rp
    for spec in proj.get("dependencies", []) or []:
        if r := parse_requirement(spec):
            info.dependencies.append(Dependency(name=r[0], version=r[1], ecosystem="pypi", manifest=path, line=_line_of(text, spec)))
    for group, specs in (proj.get("optional-dependencies", {}) or {}).items():
        for spec in specs:
            if r := parse_requirement(spec):
                info.dependencies.append(Dependency(name=r[0], version=r[1], ecosystem="pypi", manifest=path, line=_line_of(text, spec), dev=group in ("dev", "test", "tests", "lint")))
    for _g, specs in (data.get("dependency-groups", {}) or {}).items():
        for spec in specs:
            if isinstance(spec, str) and (r := parse_requirement(spec)):
                info.dependencies.append(Dependency(name=r[0], version=r[1], ecosystem="pypi", manifest=path, line=_line_of(text, spec), dev=True))
    poetry = data.get("tool", {}).get("poetry", {})
    if poetry:
        info.package_manager = "poetry"
        info.name = info.name or poetry.get("name")
        for section, dev in (("dependencies", False), ("dev-dependencies", True)):
            for name, ver in (poetry.get(section, {}) or {}).items():
                if name.lower() == "python":
                    info.runtime["python"] = str(ver)
                    continue
                v = ver if isinstance(ver, str) else (ver.get("version") if isinstance(ver, dict) else None)
                info.dependencies.append(Dependency(name=name.lower(), version=v, ecosystem="pypi", manifest=path, line=_line_of(text, f"{name} ="), dev=dev))
        for gname, group in (poetry.get("group", {}) or {}).items():
            for name, ver in (group.get("dependencies", {}) or {}).items():
                v = ver if isinstance(ver, str) else None
                info.dependencies.append(Dependency(name=name.lower(), version=v, ecosystem="pypi", manifest=path, line=_line_of(text, f"{name} ="), dev=gname != "main"))
    if "uv" in data.get("tool", {}):
        info.package_manager = "uv"
    info.package_manager = info.package_manager or "pip"
    scripts = proj.get("scripts", {}) or poetry.get("scripts", {}) or {}
    info.scripts = {k: str(v) for k, v in scripts.items()}
    info.extra["tools"] = sorted(data.get("tool", {}).keys())
    return info


def parse_pipfile(path: str, text: str) -> ManifestInfo:
    info = ManifestInfo(path, "python", package_manager="pipenv")
    data = tomllib.loads(text)
    for section, dev in (("packages", False), ("dev-packages", True)):
        for name, ver in (data.get(section, {}) or {}).items():
            v = ver if isinstance(ver, str) else None
            info.dependencies.append(Dependency(name=name.lower(), version=None if v == "*" else v, ecosystem="pypi", manifest=path, line=_line_of(text, name), dev=dev))
    if rv := data.get("requires", {}).get("python_version"):
        info.runtime["python"] = rv
    return info


def parse_setup_py(path: str, text: str) -> ManifestInfo:
    info = ManifestInfo(path, "python", package_manager="setuptools")
    m = re.search(r"install_requires\s*=\s*\[(.*?)\]", text, re.S)
    if m:
        for spec in re.findall(r"['\"]([^'\"]+)['\"]", m.group(1)):
            if r := parse_requirement(spec):
                info.dependencies.append(Dependency(name=r[0], version=r[1], ecosystem="pypi", manifest=path, line=_line_of(text, spec)))
    return info


def parse_package_json(path: str, text: str, siblings: set[str]) -> ManifestInfo:
    info = ManifestInfo(path, "javascript")
    data = json.loads(text)
    info.name = data.get("name")
    for section, dev in (("dependencies", False), ("devDependencies", True), ("peerDependencies", False), ("optionalDependencies", False)):
        for name, ver in (data.get(section, {}) or {}).items():
            info.dependencies.append(Dependency(name=name, version=str(ver), ecosystem="npm", manifest=path, line=_line_of(text, f'"{name}"'), dev=dev))
    info.scripts = {k: str(v) for k, v in (data.get("scripts", {}) or {}).items()}
    if eng := data.get("engines"):
        info.runtime.update({k: str(v) for k, v in eng.items()})
    pm = data.get("packageManager")
    if pm:
        info.package_manager = str(pm).split("@")[0]
    elif "pnpm-lock.yaml" in siblings:
        info.package_manager = "pnpm"
    elif "yarn.lock" in siblings:
        info.package_manager = "yarn"
    elif "bun.lockb" in siblings or "bun.lock" in siblings:
        info.package_manager = "bun"
    else:
        info.package_manager = "npm"
    if ws := data.get("workspaces"):
        info.extra["workspaces"] = ws
    info.extra["type"] = data.get("type")
    info.extra["main"] = data.get("main")
    return info


def _safe_xml(text: str) -> ET.Element:
    if re.search(r"<!(DOCTYPE|ENTITY)", text, re.I):
        raise ValueError("XML with DTD/entities is not parsed (XXE protection)")
    return ET.fromstring(text)  # noqa: S314


def parse_pom(path: str, text: str) -> ManifestInfo:
    info = ManifestInfo(path, "java", package_manager="maven")
    root = _safe_xml(text)
    ns = {"m": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {}
    q = (lambda t: f"m:{t}") if ns else (lambda t: t)
    for dep in root.iter(f"{{{ns['m']}}}dependency" if ns else "dependency"):
        g = dep.findtext(q("groupId"), namespaces=ns) or ""
        a = dep.findtext(q("artifactId"), namespaces=ns) or ""
        v = dep.findtext(q("version"), namespaces=ns)
        scope = dep.findtext(q("scope"), namespaces=ns)
        info.dependencies.append(Dependency(name=f"{g}:{a}", version=v, ecosystem="maven", manifest=path, line=_line_of(text, f"<artifactId>{a}</artifactId>"), dev=scope == "test"))
    jv = root.find(f"{q('properties')}/{q('java.version')}", namespaces=ns)
    if jv is not None and jv.text:
        info.runtime["java"] = jv.text
    return info


_GRADLE_DEP = re.compile(r"^\s*(implementation|api|compileOnly|runtimeOnly|testImplementation|kapt|annotationProcessor)\s*\(?\s*['\"]([^'\":]+):([^'\":]+)(?::([^'\"]+))?['\"]", re.M)


def parse_gradle(path: str, text: str) -> ManifestInfo:
    info = ManifestInfo(path, "java", package_manager="gradle")
    for m in _GRADLE_DEP.finditer(text):
        info.dependencies.append(Dependency(name=f"{m.group(2)}:{m.group(3)}", version=m.group(4), ecosystem="maven", manifest=path, line=text.count("\n", 0, m.start()) + 1, dev=m.group(1).startswith("test")))
    if "kotlin(" in text or "org.jetbrains.kotlin" in text:
        info.extra["kotlin"] = True
    return info


def parse_cargo(path: str, text: str) -> ManifestInfo:
    info = ManifestInfo(path, "rust", package_manager="cargo")
    data = tomllib.loads(text)
    info.name = data.get("package", {}).get("name")
    if ed := data.get("package", {}).get("edition"):
        info.runtime["rust-edition"] = str(ed)
    for section, dev in (("dependencies", False), ("dev-dependencies", True), ("build-dependencies", True)):
        for name, ver in (data.get(section, {}) or {}).items():
            v = ver if isinstance(ver, str) else (ver.get("version") if isinstance(ver, dict) else None)
            info.dependencies.append(Dependency(name=name, version=v, ecosystem="cargo", manifest=path, line=_line_of(text, f"{name} ="), dev=dev))
    return info


def parse_go_mod(path: str, text: str) -> ManifestInfo:
    info = ManifestInfo(path, "go", package_manager="go modules")
    if m := re.search(r"^module\s+(\S+)", text, re.M):
        info.name = m.group(1)
    if m := re.search(r"^go\s+(\S+)", text, re.M):
        info.runtime["go"] = m.group(1)
    for i, line in enumerate(text.splitlines(), 1):
        m = re.match(r"^\s*(?:require\s+)?([a-z0-9.\-]+\.[a-z]+/[^\s]+)\s+(v[^\s]+)(\s*//\s*indirect)?", line)
        if m:
            info.dependencies.append(Dependency(name=m.group(1), version=m.group(2), ecosystem="go", manifest=path, line=i, dev=bool(m.group(3))))
    return info


def parse_composer(path: str, text: str) -> ManifestInfo:
    info = ManifestInfo(path, "php", package_manager="composer")
    data = json.loads(text)
    for section, dev in (("require", False), ("require-dev", True)):
        for name, ver in (data.get(section, {}) or {}).items():
            if name == "php":
                info.runtime["php"] = ver
                continue
            info.dependencies.append(Dependency(name=name, version=ver, ecosystem="composer", manifest=path, line=_line_of(text, f'"{name}"'), dev=dev))
    info.scripts = {k: str(v) for k, v in (data.get("scripts", {}) or {}).items()}
    return info


def parse_gemfile(path: str, text: str) -> ManifestInfo:
    info = ManifestInfo(path, "ruby", package_manager="bundler")
    group_dev = False
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith("group") and ("test" in s or "development" in s):
            group_dev = True
        elif s == "end":
            group_dev = False
        if m := re.match(r"gem\s+['\"]([^'\"]+)['\"](?:\s*,\s*['\"]([^'\"]+)['\"])?", s):
            info.dependencies.append(Dependency(name=m.group(1), version=m.group(2), ecosystem="rubygems", manifest=path, line=i, dev=group_dev))
        if m := re.match(r"ruby\s+['\"]([^'\"]+)['\"]", s):
            info.runtime["ruby"] = m.group(1)
    return info


def parse_pubspec(path: str, text: str) -> ManifestInfo:
    info = ManifestInfo(path, "dart", package_manager="pub")
    data = yaml.safe_load(text) or {}
    info.name = data.get("name")
    for section, dev in (("dependencies", False), ("dev_dependencies", True)):
        for name, ver in (data.get(section, {}) or {}).items():
            info.dependencies.append(Dependency(name=name, version=ver if isinstance(ver, str) else None, ecosystem="pub", manifest=path, line=_line_of(text, f"{name}:"), dev=dev))
    return info


PARSERS = {
    "package.json": "package_json",
    "pyproject.toml": parse_pyproject,
    "Pipfile": parse_pipfile,
    "setup.py": parse_setup_py,
    "pom.xml": parse_pom,
    "build.gradle": parse_gradle,
    "build.gradle.kts": parse_gradle,
    "Cargo.toml": parse_cargo,
    "go.mod": parse_go_mod,
    "composer.json": parse_composer,
    "Gemfile": parse_gemfile,
    "pubspec.yaml": parse_pubspec,
}


def parse_manifests(root: Path, manifest_paths: list[str], all_paths: set[str]) -> tuple[list[ManifestInfo], list[str]]:
    infos: list[ManifestInfo] = []
    warnings: list[str] = []
    for rel in manifest_paths:
        name = PurePosixPath(rel).name
        parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
        siblings = {p.rsplit("/", 1)[-1] for p in all_paths if (p.rsplit("/", 1)[0] if "/" in p else "") == parent}
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
            if name == "package.json":
                infos.append(parse_package_json(rel, text, siblings))
            elif name.startswith("requirements") or name.endswith("requirements.txt"):
                infos.append(parse_requirements_txt(rel, text))
            elif name in PARSERS and callable(PARSERS[name]):
                infos.append(PARSERS[name](rel, text))  # type: ignore[operator]
        except Exception as exc:  # malformed manifest must not kill analysis
            warnings.append(f"Could not parse manifest {rel}: {exc}")
    return infos, warnings
