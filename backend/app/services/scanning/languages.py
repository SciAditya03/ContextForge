"""Language and file-category detection tables."""

from __future__ import annotations

EXTENSION_LANGUAGES: dict[str, str] = {
    ".py": "Python", ".pyi": "Python", ".pyw": "Python",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript", ".cts": "TypeScript",
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin", ".scala": "Scala", ".groovy": "Groovy",
    ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".cxx": "C++", ".hpp": "C++", ".hh": "C++", ".hxx": "C++",
    ".cs": "C#", ".go": "Go", ".rs": "Rust", ".php": "PHP", ".rb": "Ruby", ".swift": "Swift", ".dart": "Dart",
    ".m": "Objective-C", ".mm": "Objective-C", ".lua": "Lua", ".r": "R", ".jl": "Julia", ".ex": "Elixir",
    ".exs": "Elixir", ".erl": "Erlang", ".hs": "Haskell", ".clj": "Clojure", ".fs": "F#", ".pl": "Perl",
    ".vue": "Vue", ".svelte": "Svelte", ".astro": "Astro",
    ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "SCSS", ".sass": "SCSS", ".less": "Less",
    ".sql": "SQL", ".prisma": "Prisma", ".graphql": "GraphQL", ".gql": "GraphQL", ".proto": "Protocol Buffers",
    ".sh": "Shell", ".bash": "Shell", ".zsh": "Shell", ".ps1": "PowerShell", ".bat": "Batch",
    ".yaml": "YAML", ".yml": "YAML", ".json": "JSON", ".jsonc": "JSON", ".toml": "TOML", ".ini": "INI",
    ".xml": "XML", ".tf": "Terraform", ".tfvars": "Terraform", ".hcl": "HCL",
    ".md": "Markdown", ".mdx": "Markdown", ".rst": "reStructuredText", ".txt": "Text",
    ".ipynb": "Jupyter Notebook", ".gradle": "Groovy",
}

FILENAME_LANGUAGES: dict[str, str] = {
    "Dockerfile": "Dockerfile", "Containerfile": "Dockerfile", "Makefile": "Makefile",
    "Gemfile": "Ruby", "Rakefile": "Ruby", "Pipfile": "TOML", "Jenkinsfile": "Groovy",
    "Procfile": "Procfile", "CMakeLists.txt": "CMake", "Vagrantfile": "Ruby",
}

# languages counted as "source code" for LOC statistics
CODE_LANGUAGES = {
    "Python", "JavaScript", "TypeScript", "Java", "Kotlin", "Scala", "Groovy", "C", "C++", "C#", "Go", "Rust",
    "PHP", "Ruby", "Swift", "Dart", "Objective-C", "Lua", "R", "Julia", "Elixir", "Erlang", "Haskell",
    "Clojure", "F#", "Perl", "Vue", "Svelte", "Astro", "SQL", "Shell", "PowerShell", "Terraform", "HCL",
    "Prisma", "GraphQL", "Dockerfile", "HTML", "CSS", "SCSS", "Less", "Batch", "Protocol Buffers",
}

LINE_COMMENT: dict[str, tuple[str, ...]] = {
    "Python": ("#",), "Shell": ("#",), "Ruby": ("#",), "YAML": ("#",), "TOML": ("#",), "Dockerfile": ("#",),
    "Terraform": ("#", "//"), "R": ("#",), "Perl": ("#",), "Elixir": ("#",), "PowerShell": ("#",),
    "SQL": ("--",), "Lua": ("--",), "Haskell": ("--",),
}
DEFAULT_LINE_COMMENT = ("//",)

MANIFEST_FILES = {
    "package.json", "requirements.txt", "requirements-dev.txt", "dev-requirements.txt", "pyproject.toml",
    "Pipfile", "setup.py", "setup.cfg", "pom.xml", "build.gradle", "build.gradle.kts", "Cargo.toml",
    "go.mod", "composer.json", "Gemfile", "pubspec.yaml", "Package.swift", "environment.yml", "mix.exs",
    "deno.json",
}
LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock", "Cargo.lock",
    "go.sum", "composer.lock", "Gemfile.lock", "uv.lock", "bun.lockb", "pubspec.lock",
}
BUILD_FILES = {
    "Makefile", "CMakeLists.txt", "tsconfig.json", "jsconfig.json", "babel.config.js", ".babelrc",
    "webpack.config.js", "rollup.config.js", "esbuild.config.js", "turbo.json", "nx.json", "lerna.json",
    "Jenkinsfile", "Rakefile", "build.sh", "justfile", "Taskfile.yml",
}
BUILD_PREFIXES = ("vite.config.", "next.config.", "webpack.config.", "rollup.config.", "tsconfig.", "svelte.config.", "nuxt.config.", "astro.config.", "postcss.config.", "tailwind.config.", "metro.config.", "angular.json")
CONFIG_FILES = {
    ".eslintrc", ".eslintrc.js", ".eslintrc.json", ".eslintrc.cjs", "eslint.config.js", "eslint.config.mjs",
    ".prettierrc", ".prettierrc.json", "prettier.config.js", ".editorconfig", "setup.cfg", "tox.ini",
    "pytest.ini", ".flake8", "mypy.ini", "ruff.toml", ".pre-commit-config.yaml", "alembic.ini",
    "jest.config.js", "jest.config.ts", "vitest.config.ts", "vitest.config.js", "playwright.config.ts",
    "nginx.conf", "settings.py", "config.py", "application.properties", "application.yml",
    "application.yaml", "appsettings.json", "components.json", ".npmrc", ".nvmrc", ".python-version",
    "middleware.ts", "middleware.js",
}
DEPLOY_FILES = {
    "Dockerfile", "Containerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml",
    "Procfile", "vercel.json", "netlify.toml", "fly.toml", "render.yaml", "app.yaml", "app.json",
    "serverless.yml", "serverless.yaml", "skaffold.yaml", "railway.json", "heroku.yml", "firebase.json",
    ".dockerignore", "Chart.yaml", "cloudbuild.yaml", "amplify.yml",
}
DOC_EXTS = {".md", ".mdx", ".rst", ".txt", ".adoc"}
STYLE_EXTS = {".css", ".scss", ".sass", ".less"}
ASSET_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".webp", ".bmp", ".tiff", ".mp4", ".mp3", ".wav",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".pdf", ".avif",
}
BINARY_EXTS = {
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a", ".class", ".jar", ".war", ".pyc", ".pyo",
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".7z", ".rar", ".whl", ".egg", ".db", ".sqlite", ".sqlite3",
    ".pkl", ".npy", ".npz", ".h5", ".onnx", ".pt", ".ckpt", ".parquet", ".lockb", ".wasm",
}
DATA_EXTS = {".csv", ".tsv", ".jsonl", ".ndjson", ".xml"}
