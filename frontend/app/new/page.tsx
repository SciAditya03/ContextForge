"use client";
import { FileArchive, FolderUp, Gauge, Loader2, Microscope, Rocket, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { PageHeader } from "@/components/layout/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { ErrorBox } from "@/components/ui/misc";
import { useAsync } from "@/hooks/use-async";
import { api, uploadProject } from "@/lib/api";
import { cn, formatBytes } from "@/lib/utils";

const DEPTHS = [
  { value: "quick", label: "Quick", Icon: Gauge, text: "Top ~40 files to the LLM, small batches, low effort. Fast overview." },
  { value: "standard", label: "Standard", Icon: Rocket, text: "Top ~160 files, balanced batches. Recommended for most projects." },
  { value: "deep", label: "Deep", Icon: Microscope, text: "Up to ~700 files including tests, larger context per file, high effort." },
] as const;

export default function NewAnalysisPage() {
  const router = useRouter();
  const settings = useAsync(() => api.settings(), []);
  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [depthChoice, setDepth] = useState<string | null>(null);
  const [providerChoice, setProvider] = useState<string | null>(null);
  const [modelChoice, setModel] = useState<string | null>(null);
  const [drag, setDrag] = useState(false);
  const [progress, setProgress] = useState<{ loaded: number; total: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const limitMb = settings.data?.limits.max_upload_mb ?? 200;

  // user choices override the server defaults once made
  const depth = depthChoice ?? settings.data?.analysis.depth ?? "standard";
  const provider = providerChoice ?? settings.data?.provider.provider ?? "";
  const model = modelChoice ?? (provider === settings.data?.provider.provider ? settings.data?.provider.model ?? "" : "");

  function pick(f: File | undefined | null) {
    setError(null);
    if (!f) return;
    if (!f.name.toLowerCase().endsWith(".zip")) return setError("Please choose a .zip archive.");
    if (f.size > limitMb * 1024 * 1024) return setError(`The archive is ${formatBytes(f.size)}; the server accepts up to ${limitMb} MB.`);
    setFile(f);
    if (!name) setName(f.name.replace(/\.zip$/i, ""));
  }

  async function start() {
    if (!file) return;
    setError(null);
    setProgress({ loaded: 0, total: file.size });
    try {
      const res = await uploadProject({
        file,
        name: name.trim() || undefined,
        description: description.trim() || undefined,
        depth,
        provider: provider || undefined,
        model: provider && provider !== "none" ? model.trim() || undefined : undefined,
        onProgress: (loaded, total) => setProgress({ loaded, total }),
      });
      router.push(`/projects/${res.id}`);
    } catch (e) {
      setProgress(null);
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const providers = settings.data?.providers ?? {};
  const keys = settings.data?.keys ?? {};
  const info = providers[provider];
  const keyMissing = provider && provider !== "none" && info?.needs_key && !keys[provider]?.api_key_set;
  const uploading = progress !== null;
  const pct = progress && progress.total ? Math.round((progress.loaded / progress.total) * 100) : 0;

  return (
    <div>
      <PageHeader eyebrow="New analysis" title="Upload a project" description="A ZIP of a repository or project folder. Dependency folders and build output are excluded automatically." />
      <div className="grid gap-6 px-4 pb-12 sm:px-8 xl:grid-cols-[1fr_360px]">
        <div className="space-y-6">
          <Card>
            <CardContent className="pt-5">
              <div
                role="button"
                tabIndex={0}
                aria-label="Choose a ZIP archive"
                onClick={() => !uploading && inputRef.current?.click()}
                onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault();
                  setDrag(true);
                }}
                onDragLeave={() => setDrag(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setDrag(false);
                  pick(e.dataTransfer.files?.[0]);
                }}
                className={cn(
                  "relative flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors",
                  drag ? "border-primary bg-primary-soft/50" : "border-border-strong hover:border-primary/60 hover:bg-surface-2/50",
                )}
              >
                <input ref={inputRef} type="file" accept=".zip,application/zip" className="hidden" onChange={(e) => pick(e.target.files?.[0])} data-testid="file-input" />
                {file ? (
                  <div className="flex items-center gap-3 rounded-lg border border-border bg-surface px-4 py-3 text-left">
                    <FileArchive className="size-8 text-primary" />
                    <div>
                      <div className="text-sm font-medium">{file.name}</div>
                      <div className="text-xs text-muted">{formatBytes(file.size)}</div>
                    </div>
                    {!uploading ? (
                      <button
                        type="button"
                        aria-label="Remove file"
                        className="ml-3 rounded p-1 text-subtle hover:bg-surface-2 hover:text-foreground cursor-pointer"
                        onClick={(e) => {
                          e.stopPropagation();
                          setFile(null);
                        }}
                      >
                        <X className="size-4" />
                      </button>
                    ) : null}
                  </div>
                ) : (
                  <>
                    <div className="mb-3 flex size-12 items-center justify-center rounded-full bg-primary-soft text-primary">
                      <FolderUp className="size-6" />
                    </div>
                    <p className="text-sm font-medium">Drop a .zip here or click to browse</p>
                    <p className="mt-1 text-xs text-muted">Up to {limitMb} MB · path traversal, symlinks and ZIP bombs are rejected</p>
                  </>
                )}
              </div>
              {uploading ? (
                <div className="mt-4">
                  <div className="mb-1.5 flex justify-between text-xs text-muted">
                    <span className="flex items-center gap-1.5">
                      <Loader2 className="size-3.5 animate-spin" />
                      {pct < 100 ? "Uploading archive…" : "Upload complete — starting analysis…"}
                    </span>
                    <span className="tabular-nums">
                      {formatBytes(progress!.loaded)} / {formatBytes(progress!.total)} · {pct}%
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-surface-3">
                    <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              ) : null}
              {error ? (
                <div className="mt-4">
                  <ErrorBox title="Cannot start analysis" message={error} />
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Project details</CardTitle>
                <CardDescription>Used in document titles and passed to the AI as context.</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <Field label="Project name" htmlFor="name">
                <Input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="my-service" maxLength={120} />
              </Field>
              <div className="sm:col-span-2">
                <Field label="Description (optional)" htmlFor="desc" hint="E.g. what the product does. Treated as a hint, not as evidence.">
                  <Textarea id="desc" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} placeholder="Internal billing API used by the web dashboard…" />
                </Field>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <div>
                <CardTitle>Analysis depth</CardTitle>
                <CardDescription>Controls how many files the LLM reads and how much context each request carries. Deterministic layers always cover every file.</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="grid gap-3 sm:grid-cols-3">
              {DEPTHS.map(({ value, label, Icon, text }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setDepth(value)}
                  aria-pressed={depth === value}
                  className={cn(
                    "rounded-xl border p-4 text-left transition-colors cursor-pointer",
                    depth === value ? "border-primary bg-primary-soft/40 ring-1 ring-primary/40" : "border-border hover:bg-surface-2",
                  )}
                >
                  <Icon className={cn("mb-2 size-5", depth === value ? "text-primary" : "text-subtle")} />
                  <div className="text-sm font-medium">{label}</div>
                  <p className="mt-1 text-xs text-muted">{text}</p>
                </button>
              ))}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>AI provider for this run</CardTitle>
                <CardDescription>Defaults come from Settings. Keys never leave the server.</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <Field label="Provider" htmlFor="provider">
                <Select id="provider" value={provider} onChange={(e) => {
                  setProvider(e.target.value);
                  setModel(null);
                }}>
                  {Object.entries(providers).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v.label}
                    </option>
                  ))}
                </Select>
              </Field>
              {provider && provider !== "none" ? (
                <Field label="Model" htmlFor="model" hint={info?.default_model ? `Leave empty for ${info.default_model}` : "Required for this provider"}>
                  <Input id="model" value={model} onChange={(e) => setModel(e.target.value)} placeholder={info?.default_model ?? "model-name"} />
                </Field>
              ) : null}
              {keyMissing ? (
                <p className="rounded-lg border border-warning/50 bg-warning/10 px-3 py-2 text-xs">
                  No API key is configured for {info?.label}. The run will fall back to deterministic analysis and report the provider error. Add a key in Settings.
                </p>
              ) : null}
              <Button size="lg" className="w-full" disabled={!file || uploading} onClick={start} data-testid="start-analysis">
                {uploading ? <Loader2 className="animate-spin" /> : <Rocket />}
                {uploading ? "Uploading…" : "Start analysis"}
              </Button>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>What gets excluded</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex flex-wrap gap-1.5">
                {(settings.data?.analysis.exclusions ?? []).slice(0, 24).map((p) => (
                  <code key={p} className="rounded border border-border bg-surface-2 px-1.5 py-0.5 font-mono text-[11px] text-muted">
                    {p}
                  </code>
                ))}
              </div>
              <p className="mt-3 text-xs text-subtle">Excluded and skipped files are still listed in the analysis manifest with the reason.</p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
