"""File classification: language, category, entry-point detection."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from app.schemas.facts import FileCategory
from app.services.scanning import languages as L

_TEST_DIR = re.compile(r"(^|/)(tests?|__tests__|spec|specs|e2e|cypress|testing)(/|$)", re.I)
_TEST_FILE = re.compile(
    r"(^test_.*\.py$|.*_test\.py$|.*\.(test|spec)\.[cm]?[jt]sx?$|.*_test\.go$|.*Test\.java$|.*Tests?\.cs$|.*_spec\.rb$|.*Test\.kt$|conftest\.py$)"
)
_MIGRATION = re.compile(r"(^|/)(migrations?|alembic/versions|db/migrate|prisma/migrations|flyway|liquibase)(/|$)", re.I)

ENTRY_FILENAMES: dict[str, str] = {
    "main.py": "Python main module",
    "app.py": "Python application module",
    "wsgi.py": "WSGI entry point",
    "asgi.py": "ASGI entry point",
    "manage.py": "Django management entry point",
    "__main__.py": "Python package entry point",
    "server.js": "Node server entry",
    "server.ts": "Node server entry",
    "index.js": "JavaScript index module",
    "index.ts": "TypeScript index module",
    "main.ts": "TypeScript main module",
    "main.js": "JavaScript main module",
    "app.js": "Node application module",
    "app.ts": "Node application module",
    "main.go": "Go main package",
    "main.rs": "Rust binary entry",
    "lib.rs": "Rust library root",
    "Program.cs": "C# program entry",
    "main.dart": "Dart entry point",
    "index.php": "PHP front controller",
    "main.c": "C main",
    "main.cpp": "C++ main",
}
NEXT_ENTRY = re.compile(r"(^|/)(app|src/app)/(layout|page)\.[jt]sx?$|(^|/)(pages|src/pages)/_app\.[jt]sx?$")
VITE_ENTRY = re.compile(r"(^|/)src/(main|index)\.[jt]sx?$")


def detect_language(path: str) -> str | None:
    p = PurePosixPath(path)
    if p.name in L.FILENAME_LANGUAGES:
        return L.FILENAME_LANGUAGES[p.name]
    if p.name.startswith("Dockerfile"):
        return "Dockerfile"
    if p.name.startswith(".env"):
        return "Env"
    return L.EXTENSION_LANGUAGES.get(p.suffix.lower())


def classify(path: str, language: str | None) -> FileCategory:
    p = PurePosixPath(path)
    name = p.name
    ext = p.suffix.lower()

    if name.startswith(".env"):
        if any(t in name for t in (".example", ".sample", ".template", ".dist", ".defaults")):
            return FileCategory.ENV_TEMPLATE
        return FileCategory.ENV_FILE
    if name in L.LOCKFILES:
        return FileCategory.LOCKFILE
    if name in L.MANIFEST_FILES or (name.startswith("requirements") and ext == ".txt"):
        return FileCategory.MANIFEST
    if ext in L.BINARY_EXTS:
        return FileCategory.BINARY
    if ext in L.ASSET_EXTS:
        return FileCategory.ASSET
    if name in L.DEPLOY_FILES or name.startswith("Dockerfile") or ext == ".tf" or "/.github/workflows/" in f"/{path}" or path.startswith(".gitlab-ci") or "/k8s/" in f"/{path}" or "/helm/" in f"/{path}" or "/kubernetes/" in f"/{path}":
        return FileCategory.DEPLOY
    if _MIGRATION.search(path) and ext in {".py", ".sql", ".js", ".ts", ".rb", ".xml", ".yaml", ".yml"}:
        return FileCategory.MIGRATION
    if ext in {".prisma", ".graphql", ".gql", ".proto"} or name in {"schema.sql", "openapi.yaml", "openapi.json", "swagger.json", "swagger.yaml"}:
        return FileCategory.SCHEMA
    if _TEST_FILE.match(name) or (_TEST_DIR.search(path) and language in L.CODE_LANGUAGES):
        return FileCategory.TEST
    if name in L.BUILD_FILES or name.startswith(L.BUILD_PREFIXES):
        return FileCategory.BUILD
    if name in L.CONFIG_FILES or (ext in {".ini", ".cfg", ".conf", ".properties"}) or name.startswith(".") and ext in {"", ".json", ".yml", ".yaml", ".js", ".cjs", ".toml"}:
        return FileCategory.CONFIG
    if ext in L.DOC_EXTS or name.upper().startswith(("README", "LICENSE", "CHANGELOG", "CONTRIBUTING")):
        return FileCategory.DOCS
    if ext in L.STYLE_EXTS:
        return FileCategory.STYLE
    if ext in {".html", ".htm"}:
        return FileCategory.MARKUP
    if ext in L.DATA_EXTS:
        return FileCategory.DATA
    if ext in {".yaml", ".yml", ".json", ".toml"}:
        return FileCategory.CONFIG
    if ext == ".sql":
        return FileCategory.SCHEMA
    if language in L.CODE_LANGUAGES:
        return FileCategory.SOURCE
    return FileCategory.OTHER


def detect_entry_point(path: str, head: str) -> str | None:
    """Return a reason string when the file looks like an application entry point."""
    name = PurePosixPath(path).name
    depth = path.count("/")
    if NEXT_ENTRY.search(path):
        return "Next.js root layout/page" if "app/" in path else "Next.js custom App"
    if VITE_ENTRY.search(path) and depth <= 3:
        return "SPA bootstrap module"
    if name.endswith(".py") and re.search(r"^if\s+__name__\s*==\s*['\"]__main__['\"]", head, re.M):
        return "Python script with __main__ guard"
    if name.endswith(".py") and re.search(r"\b(FastAPI|Flask|Starlette)\s*\(", head):
        return "Python web application instance"
    if name.endswith((".js", ".ts", ".mjs")) and re.search(r"\.listen\s*\(", head) and re.search(r"express\s*\(|createServer|fastify\s*\(|new\s+Koa|new\s+Hono", head):
        return "Node HTTP server bootstrap"
    if name.endswith(".go") and re.search(r"^package\s+main\b", head, re.M) and "func main()" in head:
        return "Go main package"
    if name.endswith(".java") and "public static void main(" in head:
        return "Java main method"
    if name.endswith(".java") and "@SpringBootApplication" in head:
        return "Spring Boot application class"
    if name.endswith(".kt") and ("fun main(" in head or "@SpringBootApplication" in head):
        return "Kotlin main/application"
    if name in ENTRY_FILENAMES and depth <= 2:
        if name in {"index.js", "index.ts"} and depth > 1:
            return None
        return ENTRY_FILENAMES[name]
    return None
