import type {
  AnalysisPreferences,
  DocumentEntry,
  FileEntry,
  GraphResponse,
  Intelligence,
  Project,
  ProviderSettings,
  SearchResult,
  SettingsView,
} from "@/types/api";

declare global {
  interface Window {
    __CF_CONFIG__?: { apiUrl: string; token?: string | null };
  }
}

export function apiBase(): string {
  if (typeof window !== "undefined" && window.__CF_CONFIG__?.apiUrl) return window.__CF_CONFIG__.apiUrl.replace(/\/$/, "");
  return (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
}

function token(): string | null {
  return (typeof window !== "undefined" && window.__CF_CONFIG__?.token) || null;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const t = token();
  if (t) headers.set("Authorization", `Bearer ${t}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  let res: Response;
  try {
    res = await fetch(`${apiBase()}${path}`, { ...init, headers, cache: "no-store" });
  } catch {
    throw new ApiError(`Cannot reach the ContextForge API at ${apiBase()}. Is the backend running?`, 0);
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(detail || `HTTP ${res.status}`, res.status);
  }
  const type = res.headers.get("content-type") || "";
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

/** URL helpers for links the browser opens directly (downloads, SSE). */
export function apiUrl(path: string): string {
  const t = token();
  const url = `${apiBase()}${path}`;
  return t ? `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(t)}` : url;
}

export const api = {
  health: () => request<{ status: string; version: string; auth_required: boolean }>("/api/health"),
  projects: () => request<Project[]>("/api/projects"),
  project: (id: string) => request<Project>(`/api/projects/${id}`),
  cancel: (id: string) => request<{ cancelled: boolean }>(`/api/projects/${id}/cancel`, { method: "POST" }),
  remove: (id: string) => request<{ deleted: string }>(`/api/projects/${id}`, { method: "DELETE" }),
  intelligence: (id: string) => request<Intelligence>(`/api/projects/${id}/intelligence`),
  documents: (id: string) => request<DocumentEntry[]>(`/api/projects/${id}/documents`),
  document: (id: string, path: string) => request<string>(`/api/projects/${id}/documents/${path.split("/").map(encodeURIComponent).join("/")}`),
  search: (id: string, q: string) => request<{ query: string; results: SearchResult[]; truncated: boolean }>(`/api/projects/${id}/search?q=${encodeURIComponent(q)}`),
  graph: (id: string, view: string, limit = 300) => request<GraphResponse>(`/api/projects/${id}/graph?view=${view}&limit=${limit}`),
  files: (id: string) => request<FileEntry[]>(`/api/projects/${id}/files`),
  settings: () => request<SettingsView>("/api/settings"),
  saveProvider: (p: ProviderSettings) => request<SettingsView>("/api/settings/provider", { method: "PUT", body: JSON.stringify(p) }),
  saveAnalysis: (a: AnalysisPreferences) => request<SettingsView>("/api/settings/analysis", { method: "PUT", body: JSON.stringify(a) }),
  setKey: (provider: string, apiKey: string) =>
    request<{ provider: string; api_key_set: boolean; source: string | null }>(`/api/settings/keys/${provider}`, { method: "PUT", body: JSON.stringify({ api_key: apiKey }) }),
  deleteKey: (provider: string) => request<{ provider: string; api_key_set: boolean }>(`/api/settings/keys/${provider}`, { method: "DELETE" }),
  testProvider: (body: { provider?: string; model?: string | null; base_url?: string | null }) =>
    request<{ ok: boolean; provider: string; model: string; latency_ms?: number; error?: string; reply_preview?: string }>("/api/settings/test", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  listModels: (body: { provider?: string; base_url?: string | null }) =>
    request<{ ok: boolean; models: string[]; error?: string }>("/api/settings/models", { method: "POST", body: JSON.stringify(body) }),
};

export interface UploadOptions {
  file: File;
  name?: string;
  description?: string;
  depth?: string;
  provider?: string;
  model?: string;
  onProgress?: (loaded: number, total: number) => void;
}

/** Upload with real byte-level progress (fetch has no upload progress events, so XHR is used). */
export function uploadProject(opts: UploadOptions): Promise<{ id: string; name: string; status: string }> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", opts.file);
    if (opts.name) form.append("name", opts.name);
    if (opts.description) form.append("description", opts.description);
    if (opts.depth) form.append("depth", opts.depth);
    if (opts.provider) form.append("provider", opts.provider);
    if (opts.model) form.append("model", opts.model);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${apiBase()}/api/projects`);
    const t = token();
    if (t) xhr.setRequestHeader("Authorization", `Bearer ${t}`);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) opts.onProgress?.(e.loaded, e.total);
    };
    xhr.onload = () => {
      let body: { detail?: string } & Record<string, unknown> = {};
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* ignore */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as unknown as { id: string; name: string; status: string });
      else reject(new ApiError(typeof body.detail === "string" ? body.detail : `Upload failed (HTTP ${xhr.status})`, xhr.status));
    };
    xhr.onerror = () => reject(new ApiError(`Cannot reach the ContextForge API at ${apiBase()}`, 0));
    xhr.send(form);
  });
}
