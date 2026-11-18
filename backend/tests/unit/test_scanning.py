from pathlib import Path

from app.schemas.facts import FileCategory
from app.services.scanning.classifier import classify, detect_entry_point, detect_language
from app.services.scanning.scanner import count_lines, is_binary_bytes, scan_repository


def test_language_detection():
    cases = {
        "a.py": "Python", "b.tsx": "TypeScript", "c.mjs": "JavaScript", "Main.java": "Java", "x.go": "Go", "lib.rs": "Rust",
        "Dockerfile": "Dockerfile", "Dockerfile.prod": "Dockerfile", "schema.prisma": "Prisma", "q.sql": "SQL", "main.tf": "Terraform",
        "x.kt": "Kotlin", "y.swift": "Swift", "z.dart": "Dart", "w.cs": "C#", "v.php": "PHP", "u.rb": "Ruby", ".env": "Env", "s.sh": "Shell",
    }
    for path, lang in cases.items():
        assert detect_language(path) == lang, path


def test_categories():
    assert classify("package.json", "JSON") == FileCategory.MANIFEST
    assert classify("requirements-dev.txt", "Text") == FileCategory.MANIFEST
    assert classify("poetry.lock", None) == FileCategory.LOCKFILE
    assert classify(".env", "Env") == FileCategory.ENV_FILE
    assert classify(".env.example", "Env") == FileCategory.ENV_TEMPLATE
    assert classify("tests/test_api.py", "Python") == FileCategory.TEST
    assert classify("src/a.spec.ts", "TypeScript") == FileCategory.TEST
    assert classify("app/models.py", "Python") == FileCategory.SOURCE
    assert classify("docker-compose.yml", "YAML") == FileCategory.DEPLOY
    assert classify(".github/workflows/ci.yml", "YAML") == FileCategory.DEPLOY
    assert classify("alembic/versions/001_init.py", "Python") == FileCategory.MIGRATION
    assert classify("prisma/schema.prisma", "Prisma") == FileCategory.SCHEMA
    assert classify("README.md", "Markdown") == FileCategory.DOCS
    assert classify("logo.png", None) == FileCategory.ASSET
    assert classify("tsconfig.json", "JSON") == FileCategory.BUILD
    assert classify("vite.config.ts", "TypeScript") == FileCategory.BUILD


def test_entry_points():
    assert detect_entry_point("app/main.py", "from fastapi import FastAPI\napp = FastAPI()") is not None
    assert detect_entry_point("cli.py", "if __name__ == '__main__':\n    main()") is not None
    assert detect_entry_point("server.js", "const app = express(); app.listen(3000)") is not None
    assert detect_entry_point("src/app/layout.tsx", "") is not None
    assert detect_entry_point("cmd/main.go", "package main\nfunc main() {}") is not None
    assert detect_entry_point("src/utils/helpers.py", "def f(): pass") is None


def test_binary_detection_and_line_counting():
    assert is_binary_bytes(b"\x00\x01\x02")
    assert not is_binary_bytes("héllo wörld".encode())
    total, code = count_lines("# comment\n\nx = 1\n'''doc'''\n", "Python")
    assert total == 4 and code == 2
    total, code = count_lines("// c\n/* a\n b */\nconst x = 1;\n", "TypeScript")
    assert code == 1


def test_scan_repository(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    (tmp_path / "src" / "img.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.js").write_text("x")
    (tmp_path / "requirements.txt").write_text("fastapi\n")
    overview, files, tree = scan_repository(tmp_path, "proj", ["node_modules/"])
    by = {f.path: f for f in files}
    assert by["node_modules/x.js"].status == "excluded"
    assert by["src/img.png"].status == "skipped"
    assert by["src/main.py"].is_entry_point
    assert overview.entry_points == ["src/main.py"]
    assert overview.manifests == ["requirements.txt"]
    assert "Python" in overview.languages
    assert tree.name == "proj" and any(c.name == "src" for c in tree.children)
