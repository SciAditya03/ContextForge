from pathlib import Path

import pytest

from app.services.dependency.knowledge import lookup_image, lookup_package
from app.services.dependency.manifests import (
    parse_cargo,
    parse_go_mod,
    parse_gradle,
    parse_manifests,
    parse_package_json,
    parse_pom,
    parse_pyproject,
    parse_requirements_txt,
)
from app.services.dependency.techstack import detect_stack
from app.services.scanning.scanner import scan_repository


def test_requirements_txt():
    info = parse_requirements_txt("requirements.txt", "fastapi==0.110.0\n# comment\nuvicorn[standard]>=0.29\n-r other.txt\nSQLAlchemy\n")
    names = {d.name: d for d in info.dependencies}
    assert names["fastapi"].version == "==0.110.0" and names["fastapi"].line == 1
    assert names["uvicorn"].version == ">=0.29"
    assert "sqlalchemy" in names


def test_pyproject_pep621_and_poetry():
    text = """
[project]
name = "svc"
requires-python = ">=3.11"
dependencies = ["httpx>=0.27", "pydantic"]
[project.optional-dependencies]
dev = ["pytest"]
"""
    info = parse_pyproject("pyproject.toml", text)
    assert info.runtime["python"] == ">=3.11"
    assert {d.name for d in info.dependencies} == {"httpx", "pydantic", "pytest"}
    assert next(d for d in info.dependencies if d.name == "pytest").dev
    poetry = parse_pyproject("pyproject.toml", '[tool.poetry]\nname="x"\n[tool.poetry.dependencies]\npython="^3.10"\ndjango="^5.0"\n')
    assert poetry.package_manager == "poetry" and poetry.dependencies[0].name == "django"


def test_package_json_and_package_manager():
    text = '{"name":"web","scripts":{"dev":"next dev"},"dependencies":{"next":"14.0.0"},"devDependencies":{"vitest":"1.0.0"},"engines":{"node":">=20"}}'
    info = parse_package_json("package.json", text, {"pnpm-lock.yaml"})
    assert info.package_manager == "pnpm"
    assert info.scripts == {"dev": "next dev"}
    assert info.runtime["node"] == ">=20"
    assert next(d for d in info.dependencies if d.name == "vitest").dev


def test_go_cargo_gradle():
    go = parse_go_mod("go.mod", "module example.com/svc\n\ngo 1.22\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.9.1\n\tgolang.org/x/text v0.14.0 // indirect\n)\n")
    assert go.name == "example.com/svc" and go.runtime["go"] == "1.22"
    assert [d.name for d in go.dependencies] == ["github.com/gin-gonic/gin", "golang.org/x/text"]
    cargo = parse_cargo("Cargo.toml", '[package]\nname="x"\nedition="2021"\n[dependencies]\naxum="0.7"\ntokio={version="1",features=["full"]}\n')
    assert {d.name: d.version for d in cargo.dependencies} == {"axum": "0.7", "tokio": "1"}
    gradle = parse_gradle("build.gradle", "dependencies {\n  implementation 'org.springframework.boot:spring-boot-starter-web:3.2.0'\n  testImplementation 'junit:junit:4.13'\n}")
    assert gradle.dependencies[0].name == "org.springframework.boot:spring-boot-starter-web"
    assert gradle.dependencies[1].dev


def test_pom_and_xxe_rejected():
    pom = """<project xmlns="http://maven.apache.org/POM/4.0.0"><dependencies><dependency><groupId>org.postgresql</groupId>
    <artifactId>postgresql</artifactId><version>42.7.0</version></dependency></dependencies></project>"""
    info = parse_pom("pom.xml", pom)
    assert info.dependencies[0].name == "org.postgresql:postgresql"
    with pytest.raises(ValueError, match="XXE"):
        parse_pom("pom.xml", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><project>&e;</project>')


def test_malformed_manifest_becomes_warning(tmp_path: Path):
    (tmp_path / "package.json").write_text("{not json")
    infos, warnings = parse_manifests(tmp_path, ["package.json"], {"package.json"})
    assert infos == [] and "package.json" in warnings[0]


def test_knowledge_lookup():
    assert lookup_package("FastAPI") == ("FastAPI", "framework")
    assert lookup_package("@aws-sdk/client-s3") == ("AWS SDK", "cloud")
    assert lookup_image("postgres:16-alpine") == ("PostgreSQL", "database")
    assert lookup_image("docker.io/library/redis:7") == ("Redis", "cache")


def test_detect_stack_detected_vs_inferred(tmp_path: Path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "page.tsx").write_text("export default function P(){return <div/>}")
    (tmp_path / "package.json").write_text('{"dependencies":{"next":"14.0.0","@prisma/client":"5.0.0"}}')
    (tmp_path / "docker-compose.yml").write_text("services:\n  db:\n    image: postgres:16\n  api:\n    environment:\n      KEY: ${API_SECRET}\n")
    (tmp_path / ".env.example").write_text("API_SECRET=\nDATABASE_URL=postgres://x\n")
    overview, files, _ = scan_repository(tmp_path, "p", [])
    infos, _ = parse_manifests(tmp_path, overview.manifests, {f.path for f in files})
    techs, deps, configs, envs, cmds, warns = detect_stack(tmp_path, overview, files, infos)
    by = {(t.name, t.category): t for t in techs}
    assert by[("Next.js", "framework")].classification.value == "DETECTED"
    assert by[("Next.js App Router", "framework")].classification.value == "INFERRED"
    assert ("PostgreSQL", "database") in by
    env = {e.name: e for e in envs}
    assert env["API_SECRET"].defined_in and env["API_SECRET"].used_in  # template + compose ${} reference
    assert any(c.kind == "docker-compose" for c in configs)
