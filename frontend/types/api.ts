// Types mirroring the ContextForge backend schemas (backend/app/schemas/facts.py and API routes).

export type EvidenceClass = "DETECTED" | "INFERRED" | "AI_INTERPRETED" | "UNKNOWN";
export type ProjectStatus = "queued" | "running" | "completed" | "failed" | "cancelled";
export type Severity = "critical" | "high" | "medium" | "low" | "info";
export type StageStatus = "pending" | "running" | "done" | "skipped" | "failed" | "warning";

export interface SourceRef {
  file: string;
  line_start: number | null;
  line_end: number | null;
}

export interface Claim {
  text: string;
  classification: EvidenceClass;
  sources: SourceRef[];
  layer: string;
  confidence: number;
  verified: boolean;
}

export interface Stage {
  key: string;
  label: string;
  status: StageStatus;
  done: number | null;
  total: number | null;
  detail: string;
  elapsed_s: number | null;
}

export interface ProjectStats {
  duration_s: number;
  fingerprint: string;
  files: number;
  included_files: number;
  source_files: number;
  code_lines: number;
  languages: Record<string, number>;
  frameworks: string[];
  routes: number;
  db_models: number;
  dependencies: number;
  symbols: number;
  findings: number;
  severity: Partial<Record<Severity, number>>;
  secrets: number;
  coverage: Record<string, number>;
  ai: {
    enabled: boolean;
    provider: string;
    model: string | null;
    requests: number;
    failed_requests: number;
    cached: number;
    input_tokens: number;
    output_tokens: number;
    stages: Record<string, string>;
    errors: string[];
  };
  documents: number;
  output_valid: boolean | null;
}

export interface Project {
  id: string;
  name: string;
  description: string | null;
  status: ProjectStatus;
  created_at: string;
  updated_at: string;
  archive_name: string | null;
  archive_size: number | null;
  options: { depth?: string; provider?: string; model?: string | null; token_budget?: number; send_source_to_ai?: boolean };
  stats: Partial<ProjectStats>;
  error: string | null;
  fingerprint: string | null;
  stages?: Stage[];
  running?: boolean;
}

export interface Technology {
  name: string;
  category: string;
  classification: EvidenceClass;
  version: string | null;
  evidence: SourceRef[];
  note: string | null;
}

export interface Route {
  method: string;
  path: string;
  handler: string | null;
  file: string;
  line: number;
  framework: string;
  kind: string;
  params: string[];
  body_model: string | null;
  response_model: string | null;
  auth: string[];
  middleware: string[];
  calls: string[];
  status_codes: number[];
  errors: string[];
}

export interface ClientCall {
  file: string;
  line: number;
  method: string;
  url: string;
  matched_route: string | null;
}

export interface DbField {
  name: string;
  type: string | null;
  primary_key: boolean;
  foreign_key: string | null;
  nullable: boolean | null;
  unique: boolean;
  index: boolean;
  default: string | null;
  line: number | null;
}

export interface DbModel {
  name: string;
  table: string | null;
  orm: string;
  file: string;
  line: number;
  fields: DbField[];
  relationships: { name: string; target: string; kind: string; line?: number }[];
  indexes: string[];
  also_defined_in: string[];
}

export interface Finding {
  id: string;
  title: string;
  severity: Severity;
  category: string;
  file: string | null;
  line_start: number | null;
  line_end: number | null;
  explanation: string;
  evidence: string;
  impact: string;
  suggestion: string;
  confidence: number;
  status: "confirmed" | "suspicious" | "manual_verification";
  source: "static" | "ai";
  group: "security" | "reliability" | "issue";
}

export interface Component {
  layer: string;
  files: string[];
  evidence: string[];
  classification: EvidenceClass;
}

export interface DirectoryNode {
  name: string;
  path: string;
  files: number;
  children: DirectoryNode[];
}

export interface Workflow {
  name: string;
  trigger: string;
  handler: string;
  steps: string[];
  input_data: string;
  transformations: string;
  output: string;
  dependencies: string[];
  errors: string[];
  sources: SourceRef[];
  verified: boolean;
}

export interface Intelligence {
  project: Project;
  generated_at: string;
  fingerprint: string;
  analysis_version: string;
  depth: string;
  overview: {
    root_name: string;
    total_files: number;
    included_files: number;
    excluded_files: number;
    source_files: number;
    test_files: number;
    total_lines: number;
    code_lines: number;
    total_bytes: number;
    languages: Record<string, { files: number; lines: number; code_lines: number; bytes: number }>;
    categories: Record<string, number>;
    entry_points: string[];
    manifests: string[];
    subprojects: string[];
  };
  readme_excerpt: string | null;
  technologies: Technology[];
  components: Component[];
  routes: Route[];
  client_calls: ClientCall[];
  db_models: DbModel[];
  db_operations_count: number;
  findings: Finding[];
  secrets: { file: string; line: number; kind: string; redacted: string }[];
  env_vars: { name: string; defined_in: SourceRef[]; used_in: SourceRef[]; has_default: boolean }[];
  dependencies: { name: string; version: string | null; ecosystem: string; manifest: string; dev: boolean; category: string | null; used: boolean | null }[];
  manifest_summary: Record<string, number>;
  ai: {
    provider: string;
    model: string | null;
    enabled: boolean;
    requests: number;
    failed_requests: number;
    cached_responses: number;
    input_tokens_est: number;
    output_tokens_est: number;
    token_budget: number;
    stages: Record<string, string>;
    errors: string[];
    validation: Record<string, number>;
  };
  synthesis: {
    purpose: Claim | null;
    executive_summary: Claim[];
    architecture: Claim[];
    authentication: Claim[];
    workflows: Workflow[];
    open_questions: string[];
  };
  module_summaries: { module: string; purpose: string; files: string[]; responsibilities: string[]; interactions: string[] }[];
  graph: { files: number; edges: number; modules: number; cycles: string[][] };
  tree: DirectoryNode | null;
  output_validation: { ok?: boolean; source_references_checked?: number; invalid_source_references?: string[]; documents_missing?: string[] };
  warnings: string[];
  test_info: { test_files?: number; frameworks?: string[] };
}

export interface DocumentEntry {
  path: string;
  title: string;
  group: "master" | "modular" | "layer" | "data";
  size: number;
  kind: "markdown" | "json";
}

export interface SearchResult {
  path: string;
  title: string;
  line: number;
  heading: string;
  snippet: string;
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  group?: string | null;
  data: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  weight: number;
  data?: Record<string, unknown>;
}

export interface GraphResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
  total_nodes?: number;
}

export interface FileEntry {
  path: string;
  language: string | null;
  category: string;
  lines: number;
  size: number;
  status: string;
  status_reason: string | null;
  is_entry_point: boolean;
  has_secrets: boolean;
  analysis: string | null;
  analysis_reason: string | null;
}

export interface ProviderInfo {
  label: string;
  default_model: string | null;
  needs_key: boolean;
  needs_base_url: boolean;
  notes: string;
}

export interface ProviderSettings {
  provider: string;
  model: string | null;
  base_url: string | null;
  temperature: number;
  max_output_tokens: number;
  timeout_s: number;
  retries: number;
}

export interface AnalysisPreferences {
  depth: "quick" | "standard" | "deep";
  token_budget: number;
  max_file_kb: number;
  max_concurrency: number;
  exclusions: string[];
  send_source_to_ai: boolean;
  cache_ai_responses: boolean;
  keep_uploaded_archive: boolean;
}

export interface SettingsView {
  provider: ProviderSettings;
  keys: Record<string, { api_key_set: boolean; source: "environment" | "stored" | null }>;
  analysis: AnalysisPreferences;
  providers: Record<string, ProviderInfo>;
  default_exclusions: string[];
  allow_provider_base_url_override: boolean;
  limits: { max_upload_mb: number; max_extracted_mb: number; max_file_count: number; max_single_file_mb: number };
}

export interface StreamEvent {
  id: number;
  type: "stage" | "status";
  stage?: string;
  status: string;
  done?: number | null;
  total?: number | null;
  detail?: string;
  elapsed_s?: number;
  error?: string | null;
  stats?: ProjectStats | null;
}
