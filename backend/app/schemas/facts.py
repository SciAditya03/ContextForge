"""Core data model for extracted project facts.

Everything in here is produced deterministically (Layers 0-5, 7) or by the AI
orchestrator (Layer 6 / synthesis) and is the single source the context
compiler renders from.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EvidenceClass(StrEnum):
    DETECTED = "DETECTED"
    INFERRED = "INFERRED"
    AI_INTERPRETED = "AI_INTERPRETED"
    UNKNOWN = "UNKNOWN"


class SourceRef(BaseModel):
    file: str
    line_start: int | None = None
    line_end: int | None = None

    def label(self) -> str:
        if self.line_start is None:
            return f"`{self.file}`"
        if self.line_end and self.line_end != self.line_start:
            return f"`{self.file}:{self.line_start}-{self.line_end}`"
        return f"`{self.file}:{self.line_start}`"


class Claim(BaseModel):
    text: str
    classification: EvidenceClass = EvidenceClass.AI_INTERPRETED
    sources: list[SourceRef] = Field(default_factory=list)
    layer: str = ""
    confidence: float = 0.5
    evidence_type: str = ""  # e.g. "ast", "manifest", "regex", "llm"
    verified: bool = True  # false when consistency validation could not confirm sources


# ---------------------------------------------------------------- Layer 0
class FileCategory(StrEnum):
    SOURCE = "source"
    TEST = "test"
    CONFIG = "config"
    DOCS = "docs"
    BUILD = "build"
    MANIFEST = "manifest"
    LOCKFILE = "lockfile"
    ENV_TEMPLATE = "env_template"
    ENV_FILE = "env_file"
    DEPLOY = "deploy"
    MIGRATION = "migration"
    SCHEMA = "schema"
    STYLE = "style"
    MARKUP = "markup"
    DATA = "data"
    ASSET = "asset"
    BINARY = "binary"
    OTHER = "other"


class FileRecord(BaseModel):
    path: str
    size: int
    language: str | None = None
    category: FileCategory = FileCategory.OTHER
    lines: int = 0
    code_lines: int = 0
    sha256: str = ""
    is_binary: bool = False
    is_entry_point: bool = False
    entry_point_reason: str | None = None
    status: str = "included"  # included | excluded | skipped | failed
    status_reason: str | None = None
    has_secrets: bool = False
    generated: bool = False  # machine-generated code (codegen headers / *.gen.* / _pb2.py ...)


class DirectoryNode(BaseModel):
    name: str
    path: str
    files: int = 0
    children: list[DirectoryNode] = Field(default_factory=list)


class RepositoryOverview(BaseModel):
    root_name: str
    total_files: int = 0
    included_files: int = 0
    excluded_files: int = 0
    source_files: int = 0
    test_files: int = 0
    total_lines: int = 0
    code_lines: int = 0
    total_bytes: int = 0
    languages: dict[str, dict[str, int]] = Field(default_factory=dict)  # lang -> {files, lines, bytes}
    categories: dict[str, int] = Field(default_factory=dict)
    entry_points: list[str] = Field(default_factory=list)
    config_files: list[str] = Field(default_factory=list)
    docs_files: list[str] = Field(default_factory=list)
    test_paths: list[str] = Field(default_factory=list)
    build_files: list[str] = Field(default_factory=list)
    env_templates: list[str] = Field(default_factory=list)
    manifests: list[str] = Field(default_factory=list)
    deploy_files: list[str] = Field(default_factory=list)
    subprojects: list[str] = Field(default_factory=list)  # directories containing their own manifest


# ---------------------------------------------------------------- Layer 1
class Dependency(BaseModel):
    name: str
    version: str | None = None
    ecosystem: str
    manifest: str
    line: int | None = None
    dev: bool = False
    category: str | None = None  # framework, orm, testing, ...
    used: bool | None = None  # None = unknown


class Technology(BaseModel):
    name: str
    category: str  # language, framework, database, auth, cloud, testing, build, deploy, integration, runtime, package_manager, state, styling, queue, cache, logging
    classification: EvidenceClass = EvidenceClass.DETECTED
    version: str | None = None
    evidence: list[SourceRef] = Field(default_factory=list)
    note: str | None = None


class EnvVar(BaseModel):
    name: str
    defined_in: list[SourceRef] = Field(default_factory=list)  # .env.example etc.
    used_in: list[SourceRef] = Field(default_factory=list)
    has_default: bool = False


class ConfigFile(BaseModel):
    path: str
    kind: str
    summary: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------- Layer 2
class Symbol(BaseModel):
    name: str
    kind: str  # class, function, method, interface, type, enum, constant, variable, component, hook
    file: str
    line_start: int
    line_end: int
    parent: str | None = None
    signature: str | None = None
    decorators: list[str] = Field(default_factory=list)
    bases: list[str] = Field(default_factory=list)
    docstring: str | None = None
    exported: bool = False
    is_async: bool = False
    calls: list[str] = Field(default_factory=list)
    raises: list[str] = Field(default_factory=list)
    handles_exceptions: bool = False


class ImportRef(BaseModel):
    file: str
    module: str
    names: list[str] = Field(default_factory=list)
    line: int
    resolved: str | None = None  # internal file path if resolved
    also_resolved: list[str] = Field(default_factory=list)  # extra submodules for `from pkg import a, b`
    external: bool = False
    package: str | None = None  # top-level external package name


class ModuleInfo(BaseModel):
    path: str
    language: str
    parser: str  # python-ast, tree-sitter-ts, heuristic-*
    parse_ok: bool = True
    parse_error: str | None = None
    docstring: str | None = None
    symbols: list[Symbol] = Field(default_factory=list)
    imports: list[ImportRef] = Field(default_factory=list)
    exports: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)  # controller, service, model, middleware, ...
    env_vars: list[tuple[str, int]] = Field(default_factory=list)
    http_calls: list[dict[str, Any]] = Field(default_factory=list)  # {method, url, line}
    string_literals_sql: list[tuple[str, int]] = Field(default_factory=list)


# ---------------------------------------------------------------- Layer 3/4
class Route(BaseModel):
    method: str
    path: str
    handler: str | None = None
    file: str
    line: int
    framework: str
    kind: str = "http"  # http, graphql, websocket, rpc
    params: list[str] = Field(default_factory=list)
    body_model: str | None = None
    response_model: str | None = None
    auth: list[str] = Field(default_factory=list)  # dependency / middleware hints
    middleware: list[str] = Field(default_factory=list)
    calls: list[str] = Field(default_factory=list)
    status_codes: list[int] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    router_var: str | None = None  # variable the route was declared on (for prefix resolution)
    param_annotations: dict[str, str] = Field(default_factory=dict)
    resolved_prefix: bool = False


class ClientCall(BaseModel):
    file: str
    line: int
    method: str
    url: str
    matched_route: str | None = None  # "METHOD path" if resolved


class GraphNode(BaseModel):
    id: str
    label: str
    type: str  # file, module, external, route, model, layer
    group: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str  # imports, calls_api, uses_model, inherits, depends_on
    weight: int = 1
    data: dict[str, Any] = Field(default_factory=dict)


class DependencyGraph(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    module_nodes: list[GraphNode] = Field(default_factory=list)
    module_edges: list[GraphEdge] = Field(default_factory=list)
    cycles: list[list[str]] = Field(default_factory=list)


class ArchitectureComponent(BaseModel):
    layer: str  # frontend, api, service, data, auth, middleware, worker, integration, config, state, storage, cache, logging, deploy, test
    files: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    classification: EvidenceClass = EvidenceClass.INFERRED


# ---------------------------------------------------------------- Layer 5
class DbField(BaseModel):
    name: str
    type: str | None = None
    primary_key: bool = False
    foreign_key: str | None = None
    nullable: bool | None = None
    unique: bool = False
    index: bool = False
    default: str | None = None
    line: int | None = None


class DbModel(BaseModel):
    name: str
    table: str | None = None
    orm: str
    file: str
    line: int
    fields: list[DbField] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)  # {name, target, kind, line}
    indexes: list[str] = Field(default_factory=list)
    also_defined_in: list[str] = Field(default_factory=list)  # e.g. migration DDL describing the same table


class DbOperation(BaseModel):
    file: str
    line: int
    operation: str  # select, insert, update, delete, raw_sql, orm_query, transaction
    target: str | None = None
    snippet: str | None = None
    raw_sql: bool = False


# ---------------------------------------------------------------- Layer 7 / issues
class Finding(BaseModel):
    id: str
    title: str
    severity: str  # critical, high, medium, low, info
    category: str
    file: str | None = None
    line_start: int | None = None
    line_end: int | None = None
    explanation: str
    evidence: str = ""
    impact: str = ""
    suggestion: str = ""
    confidence: float = 0.5
    status: str = "suspicious"  # confirmed | suspicious | manual_verification
    source: str = "static"  # static | ai
    group: str = "issue"  # security | reliability | issue


class SecretHit(BaseModel):
    file: str
    line: int
    kind: str
    redacted: str
    weak: bool = False  # low-entropy value (e.g. dev default password)


# ---------------------------------------------------------------- AI layer
class FileSummary(BaseModel):
    path: str
    purpose: str
    responsibilities: list[str] = Field(default_factory=list)
    key_symbols: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    classification: EvidenceClass = EvidenceClass.AI_INTERPRETED


class ModuleSummary(BaseModel):
    module: str
    purpose: str
    files: list[str] = Field(default_factory=list)
    responsibilities: list[str] = Field(default_factory=list)
    interactions: list[str] = Field(default_factory=list)


class Workflow(BaseModel):
    name: str
    trigger: str = ""
    handler: str = ""
    steps: list[str] = Field(default_factory=list)
    input_data: str = ""
    transformations: str = ""
    output: str = ""
    dependencies: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    classification: EvidenceClass = EvidenceClass.AI_INTERPRETED
    verified: bool = True


class SystemSynthesis(BaseModel):
    purpose: Claim | None = None
    executive_summary: list[Claim] = Field(default_factory=list)
    architecture: list[Claim] = Field(default_factory=list)
    frontend_backend: list[Claim] = Field(default_factory=list)
    authentication: list[Claim] = Field(default_factory=list)
    business_logic: list[Claim] = Field(default_factory=list)
    core_functionality: list[Claim] = Field(default_factory=list)
    data_flow: list[Claim] = Field(default_factory=list)
    integrations: list[Claim] = Field(default_factory=list)
    architectural_decisions: list[Claim] = Field(default_factory=list)
    technical_debt: list[Claim] = Field(default_factory=list)
    debugging_entry_points: list[Claim] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    workflows: list[Workflow] = Field(default_factory=list)
    module_interactions: list[Claim] = Field(default_factory=list)


class ManifestEntry(BaseModel):
    path: str
    status: str  # analysed | deterministic_only | skipped | excluded | failed
    reason: str | None = None
    stages: list[str] = Field(default_factory=list)
    tokens: int = 0


class AIRunInfo(BaseModel):
    provider: str
    model: str | None = None
    enabled: bool = False
    requests: int = 0
    failed_requests: int = 0
    cached_responses: int = 0
    input_tokens_est: int = 0
    output_tokens_est: int = 0
    token_budget: int = 0
    stages: dict[str, str] = Field(default_factory=dict)  # stage -> ok|partial|failed|skipped
    errors: list[str] = Field(default_factory=list)
    validation: dict[str, int] = Field(default_factory=dict)


class ProjectFacts(BaseModel):
    project_id: str
    project_name: str
    description: str | None = None
    fingerprint: str = ""
    generated_at: str = ""
    analysis_version: str = ""
    overview: RepositoryOverview
    files: list[FileRecord] = Field(default_factory=list)
    tree: DirectoryNode | None = None
    dependencies: list[Dependency] = Field(default_factory=list)
    technologies: list[Technology] = Field(default_factory=list)
    env_vars: list[EnvVar] = Field(default_factory=list)
    config_files: list[ConfigFile] = Field(default_factory=list)
    modules: list[ModuleInfo] = Field(default_factory=list)
    routes: list[Route] = Field(default_factory=list)
    client_calls: list[ClientCall] = Field(default_factory=list)
    graph: DependencyGraph = Field(default_factory=DependencyGraph)
    components: list[ArchitectureComponent] = Field(default_factory=list)
    db_models: list[DbModel] = Field(default_factory=list)
    db_operations: list[DbOperation] = Field(default_factory=list)
    migrations: list[str] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    secrets: list[SecretHit] = Field(default_factory=list)
    file_summaries: list[FileSummary] = Field(default_factory=list)
    module_summaries: list[ModuleSummary] = Field(default_factory=list)
    synthesis: SystemSynthesis = Field(default_factory=SystemSynthesis)
    manifest: list[ManifestEntry] = Field(default_factory=list)
    ai: AIRunInfo = Field(default_factory=lambda: AIRunInfo(provider="none"))
    build_commands: list[dict[str, str]] = Field(default_factory=list)  # {source, name, command}
    test_info: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    readme_excerpt: str | None = None
    depth: str = "standard"
    output_validation: dict[str, Any] = Field(default_factory=dict)

    def file(self, path: str) -> FileRecord | None:
        for f in self.files:
            if f.path == path:
                return f
        return None
