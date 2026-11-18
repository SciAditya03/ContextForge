"use client";
import { ArrowRight, Bot, FileStack, FolderUp, Layers3, ShieldCheck, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { ProjectStatusPill } from "@/components/domain/badges";
import { PageHeader } from "@/components/layout/app-shell";
import { Button, buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorBox, Skeleton } from "@/components/ui/misc";
import { StatTile } from "@/features/charts";
import { useAsync } from "@/hooks/use-async";
import { api } from "@/lib/api";
import { cn, compactNumber, formatBytes, timeAgo } from "@/lib/utils";

export default function WorkspacePage() {
  const projects = useAsync(() => api.projects(), []);
  const settings = useAsync(() => api.settings(), []);
  const list = projects.data ?? [];
  const completed = list.filter((p) => p.status === "completed");
  const totals = completed.reduce(
    (acc, p) => ({
      files: acc.files + (p.stats.files ?? 0),
      lines: acc.lines + (p.stats.code_lines ?? 0),
      findings: acc.findings + (p.stats.findings ?? 0),
      routes: acc.routes + (p.stats.routes ?? 0),
      tokens: acc.tokens + (p.stats.ai?.input_tokens ?? 0) + (p.stats.ai?.output_tokens ?? 0),
      requests: acc.requests + (p.stats.ai?.requests ?? 0),
    }),
    { files: 0, lines: 0, findings: 0, routes: 0, tokens: 0, requests: 0 },
  );
  const provider = settings.data?.provider;
  const providerInfo = provider ? settings.data?.providers[provider.provider] : null;
  const keyState = provider && provider.provider !== "none" ? settings.data?.keys[provider.provider] : null;

  async function remove(id: string) {
    if (!confirm("Delete this analysis and its generated context package?")) return;
    await api.remove(id);
    void projects.reload();
  }

  return (
    <div>
      <section className="relative overflow-hidden border-b border-border">
        <div className="forge-grid pointer-events-none absolute inset-0" />
        <div className="ember-glow pointer-events-none absolute inset-0" />
        <div className="relative px-4 pt-10 pb-9 sm:px-8 sm:pt-14">
          <p className="mb-3 inline-flex items-center gap-1.5 rounded-full border border-border bg-surface/80 px-2.5 py-1 text-[11px] font-medium text-muted">
            <Sparkles className="size-3 text-primary" /> Deterministic extraction · structural code intelligence · AI semantic analysis
          </p>
          <h1 className="max-w-3xl text-3xl font-semibold tracking-tight sm:text-4xl">
            Forge a complete, source-referenced knowledge base from any codebase.
          </h1>
          <p className="mt-3 max-w-2xl text-[15px] text-muted">
            Upload a ZIP. ContextForge maps the architecture, APIs, data model, workflows and risks, then compiles Markdown context that any LLM can use to debug,
            extend and review the project — without the original code.
          </p>
          <div className="mt-6 flex flex-wrap gap-2">
            <Link href="/new" className={buttonVariants({ size: "lg" })}>
              <FolderUp /> Analyse a project
            </Link>
            <Link href="/settings" className={buttonVariants({ variant: "secondary", size: "lg" })}>
              <Bot /> Configure AI provider
            </Link>
          </div>
          <ol className="mt-8 grid max-w-3xl gap-3 text-xs text-muted sm:grid-cols-3">
            {[
              ["1", "Safe extraction", "Hardened ZIP handling, exclusions, secret redaction. Nothing is executed."],
              ["2", "Multi-layer analysis", "AST & tree-sitter parsing, dependency graph, routes, schemas, issues, then LLM synthesis."],
              ["3", "Context package", "Master document + 20 modular docs + layer docs + JSON graph & manifest."],
            ].map(([n, t, d]) => (
              <li key={n} className="rounded-lg border border-border bg-surface/70 px-3 py-2.5 backdrop-blur">
                <div className="flex items-center gap-2 font-medium text-foreground">
                  <span className="flex size-5 items-center justify-center rounded-full bg-primary-soft text-[10px] font-semibold text-primary">{n}</span>
                  {t}
                </div>
                <p className="mt-1">{d}</p>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <PageHeader title="Workspace" description="Analyses stored on this ContextForge server." />

      <div className="space-y-6 px-4 pb-12 sm:px-8">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {projects.loading ? (
            Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[92px] rounded-xl" />)
          ) : (
            <>
              <StatTile label="Completed analyses" value={completed.length} sub={`${list.length} total`} icon={<FileStack />} />
              <StatTile label="Files analysed" value={compactNumber(totals.files)} sub={`${compactNumber(totals.lines)} lines of code`} icon={<Layers3 />} />
              <StatTile label="Findings reported" value={compactNumber(totals.findings)} sub={`${compactNumber(totals.routes)} API endpoints mapped`} icon={<ShieldCheck />} />
              <StatTile label="LLM usage" value={compactNumber(totals.tokens)} sub={`tokens · ${totals.requests} requests (provider-reported or estimated)`} icon={<Bot />} />
            </>
          )}
        </div>

        <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Recent analyses</CardTitle>
                <CardDescription>Open a project to explore its intelligence dashboard and context documents.</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="px-0 pb-1">
              {projects.error ? (
                <div className="px-5 pb-4">
                  <ErrorBox message={projects.error} onRetry={projects.reload} />
                </div>
              ) : projects.loading ? (
                <div className="space-y-2 px-5 pb-4">
                  {Array.from({ length: 3 }).map((_, i) => (
                    <Skeleton key={i} className="h-12" />
                  ))}
                </div>
              ) : list.length === 0 ? (
                <div className="px-5 pb-5">
                  <EmptyState icon={<FolderUp />} title="No analyses yet" action={<Link href="/new" className={buttonVariants()}>Upload a ZIP</Link>}>
                    Upload a project archive to generate its first context package.
                  </EmptyState>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[720px] text-sm">
                    <thead>
                      <tr className="border-y border-border bg-surface-2/60 text-left text-[11px] uppercase tracking-wide text-subtle">
                        <th className="px-5 py-2 font-medium">Project</th>
                        <th className="px-3 py-2 font-medium">Status</th>
                        <th className="px-3 py-2 font-medium">Stack</th>
                        <th className="px-3 py-2 text-right font-medium">Files</th>
                        <th className="px-3 py-2 text-right font-medium">Findings</th>
                        <th className="px-3 py-2 font-medium">AI</th>
                        <th className="px-3 py-2 font-medium">Created</th>
                        <th className="px-3 py-2" />
                      </tr>
                    </thead>
                    <tbody>
                      {list.map((p) => {
                        const langs = Object.keys(p.stats.languages ?? {}).slice(0, 3);
                        return (
                          <tr key={p.id} className="group border-b border-border last:border-0 hover:bg-surface-2/50">
                            <td className="px-5 py-3">
                              <Link href={`/projects/${p.id}`} className="font-medium hover:text-primary">
                                {p.name}
                              </Link>
                              <div className="text-xs text-subtle">
                                {p.archive_name} · {formatBytes(p.archive_size)} · {p.options.depth ?? "standard"}
                              </div>
                            </td>
                            <td className="px-3 py-3">
                              <ProjectStatusPill status={p.status} />
                            </td>
                            <td className="px-3 py-3 text-xs text-muted">{[...(p.stats.frameworks ?? []).slice(0, 2), ...langs].slice(0, 4).join(" · ") || "—"}</td>
                            <td className="px-3 py-3 text-right tabular-nums">{p.stats.files ?? "—"}</td>
                            <td className="px-3 py-3 text-right tabular-nums">{p.stats.findings ?? "—"}</td>
                            <td className="px-3 py-3 text-xs text-muted">{p.options.provider && p.options.provider !== "none" ? p.options.model ?? p.options.provider : "Deterministic"}</td>
                            <td className="px-3 py-3 text-xs text-muted">{timeAgo(p.created_at)}</td>
                            <td className="px-3 py-3 text-right">
                              <div className="flex justify-end gap-1">
                                <Link href={`/projects/${p.id}`} className={cn(buttonVariants({ variant: "ghost", size: "sm" }))} aria-label={`Open ${p.name}`}>
                                  Open <ArrowRight />
                                </Link>
                                {p.status !== "running" && p.status !== "queued" ? (
                                  <Button variant="ghost" size="icon" onClick={() => remove(p.id)} aria-label={`Delete ${p.name}`}>
                                    <Trash2 />
                                  </Button>
                                ) : null}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </CardContent>
          </Card>

          <div className="space-y-6">
            <Card>
              <CardHeader>
                <div>
                  <CardTitle>AI provider</CardTitle>
                  <CardDescription>Used for semantic layers (file, module, system synthesis).</CardDescription>
                </div>
              </CardHeader>
              <CardContent>
                {settings.loading ? (
                  <Skeleton className="h-16" />
                ) : settings.error ? (
                  <ErrorBox message={settings.error} />
                ) : provider ? (
                  <div className="space-y-3 text-sm">
                    <div className="flex items-center justify-between">
                      <span className="text-muted">Provider</span>
                      <span className="font-medium">{providerInfo?.label ?? provider.provider}</span>
                    </div>
                    {provider.provider !== "none" ? (
                      <>
                        <div className="flex items-center justify-between">
                          <span className="text-muted">Model</span>
                          <code className="font-mono text-xs">{provider.model || providerInfo?.default_model || "—"}</code>
                        </div>
                        <div className="flex items-center justify-between">
                          <span className="text-muted">API key</span>
                          <span className={cn("text-xs font-medium", keyState?.api_key_set ? "text-[var(--success-text)]" : "text-critical")}>
                            {keyState?.api_key_set ? `Configured (${keyState.source})` : providerInfo?.needs_key ? "Missing" : "Not required"}
                          </span>
                        </div>
                      </>
                    ) : (
                      <p className="text-xs text-muted">Deterministic-only mode: every structural layer runs; AI-interpreted sections are marked as not generated.</p>
                    )}
                    <Link href="/settings" className={cn(buttonVariants({ variant: "secondary", size: "sm" }), "w-full")}>
                      Manage settings
                    </Link>
                  </div>
                ) : null}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>Privacy guarantees</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 text-xs text-muted">
                <p>• Archives are treated as untrusted input; code, scripts and installers are never executed.</p>
                <p>• Detected secrets are redacted before any text is sent to an AI provider or written to output.</p>
                <p>• API keys stay on the server (environment or encrypted storage) and are never returned to the browser.</p>
                <p>• Extracted sources are deleted after analysis.</p>
              </CardContent>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
