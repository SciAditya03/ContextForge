"use client";
import { ArrowRight, Bot, Boxes, Database, FileCode2, Network, ShieldAlert, Waypoints } from "lucide-react";
import Link from "next/link";
import { EvidenceBadge, FindingStatusBadge, SeverityBadge, SourceChip } from "@/components/domain/badges";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorBox, Skeleton } from "@/components/ui/misc";
import { CoverageMeter, LanguageBar, SeverityBars, StatTile } from "@/features/charts";
import { ClaimList } from "@/features/claims";
import { useProject } from "@/features/project-context";
import { DirectoryTree } from "@/features/tree";
import { compactNumber, formatNumber } from "@/lib/utils";
import type { Severity } from "@/types/api";

const SEV_RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
const LAYER_LABEL: Record<string, string> = {
  frontend: "Frontend / UI", api: "API layer", "api-client": "API client", service: "Service layer", data: "Data access & models",
  schema: "Schemas & types", auth: "Authentication", middleware: "Middleware", worker: "Background workers", state: "State management",
  config: "Configuration", utility: "Utilities", test: "Tests", deploy: "Deployment", cache: "Caching", logging: "Logging",
  storage: "File storage", integration: "External integrations",
};

export default function IntelligencePage() {
  const { id, intel, intelError } = useProject();
  if (intelError) return <ErrorBox message={intelError} />;
  if (!intel) {
    return (
      <div className="grid gap-4 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-40 rounded-xl" />
        ))}
      </div>
    );
  }
  const o = intel.overview;
  const sev: Partial<Record<Severity, number>> = {};
  intel.findings.forEach((f) => (sev[f.severity] = (sev[f.severity] ?? 0) + 1));
  const topFindings = [...intel.findings].sort((a, b) => SEV_RANK[a.severity] - SEV_RANK[b.severity] || b.confidence - a.confidence).slice(0, 6);
  const byCat = intel.technologies.reduce<Record<string, typeof intel.technologies>>((acc, t) => {
    (acc[t.category] ??= []).push(t);
    return acc;
  }, {});
  const ai = intel.ai;
  const syn = intel.synthesis;
  const base = `/projects/${id}`;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <StatTile label="Files" value={formatNumber(o.included_files)} sub={`${o.total_files} in archive · ${o.excluded_files} excluded`} icon={<FileCode2 />} />
        <StatTile label="Lines of code" value={compactNumber(o.code_lines)} sub={`${Object.keys(o.languages).length} languages`} icon={<Boxes />} />
        <StatTile label="API endpoints" value={intel.routes.length} sub={`${intel.client_calls.length} client calls`} icon={<Waypoints />} />
        <StatTile label="Data models" value={intel.db_models.length} sub={`${intel.db_operations_count} DB operations`} icon={<Database />} />
        <StatTile label="Findings" value={intel.findings.length} sub={`${(sev.critical ?? 0) + (sev.high ?? 0)} critical/high`} icon={<ShieldAlert />} />
        <StatTile label="Dependency graph" value={intel.graph.files} sub={`${intel.graph.edges} edges · ${intel.graph.cycles.length} cycles`} icon={<Network />} />
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <div>
              <CardTitle>Project overview</CardTitle>
              <CardDescription>Purpose and executive summary. AI statements carry validated source references.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="space-y-5">
            {syn.purpose ? <ClaimList claims={[syn.purpose]} empty={null} /> : null}
            {intel.readme_excerpt ? (
              <div className="rounded-lg border border-border bg-surface-2/60 px-4 py-3">
                <div className="mb-1 flex items-center gap-2 text-[11px] font-medium text-subtle">
                  <EvidenceBadge value="DETECTED" /> README excerpt
                </div>
                <p className="whitespace-pre-line text-sm text-muted [overflow-wrap:anywhere]">{intel.readme_excerpt.replace(/\*\*(.*?)\*\*/g, "$1")}</p>
              </div>
            ) : null}
            <ClaimList
              claims={syn.executive_summary}
              empty={ai.enabled ? "The AI synthesis stage returned no executive summary." : "AI interpretation was not run for this analysis (deterministic mode). All structural facts below are still available."}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Languages</CardTitle>
              <CardDescription>Code lines per language (comments and blanks excluded).</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <LanguageBar languages={o.languages} />
            {o.entry_points.length ? (
              <div className="mt-5">
                <div className="mb-1.5 text-xs font-medium text-muted">Entry points</div>
                <div className="flex flex-wrap gap-1.5">
                  {o.entry_points.slice(0, 8).map((p) => (
                    <SourceChip key={p} file={p} />
                  ))}
                </div>
              </div>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <div>
              <CardTitle>Technology stack</CardTitle>
              <CardDescription>Detected from manifests, configs and imports; inferred items are labelled.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
            {Object.entries(byCat).map(([cat, items]) => (
              <div key={cat}>
                <div className="mb-1.5 text-[11px] font-medium uppercase tracking-wide text-subtle">{cat.replace("_", " ")}</div>
                <div className="flex flex-wrap gap-1.5">
                  {items.map((t) => (
                    <span
                      key={t.name}
                      title={[t.version ? `version ${t.version}` : "", ...t.evidence.slice(0, 3).map((e) => (e.line_start ? `${e.file}:${e.line_start}` : e.file))].filter(Boolean).join("\n")}
                      className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-2 px-2 py-1 text-xs"
                    >
                      {t.name}
                      {t.version ? <span className="font-mono text-[10px] text-subtle">{t.version.replace(/^[=^~>]+/, "")}</span> : null}
                      {t.classification !== "DETECTED" ? <EvidenceBadge value={t.classification} /> : null}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Analysis coverage</CardTitle>
              <CardDescription>Every file is accounted for — nothing is silently omitted.</CardDescription>
            </div>
            <Link href={`${base}/files`} className="text-xs font-medium text-primary hover:underline">
              Manifest
            </Link>
          </CardHeader>
          <CardContent className="space-y-4">
            <CoverageMeter summary={intel.manifest_summary} />
            <div className="rounded-lg border border-border bg-surface-2/50 p-3 text-xs">
              <div className="mb-2 flex items-center gap-2 font-medium">
                <Bot className="size-3.5 text-primary" />
                {ai.enabled ? `${ai.provider} · ${ai.model}` : "AI disabled (deterministic only)"}
              </div>
              {ai.enabled ? (
                <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-muted">
                  <dt>Requests</dt>
                  <dd className="text-right tabular-nums text-foreground">
                    {ai.requests} ({ai.failed_requests} failed, {ai.cached_responses} cached)
                  </dd>
                  <dt>Tokens in / out</dt>
                  <dd className="text-right tabular-nums text-foreground">
                    {compactNumber(ai.input_tokens_est)} / {compactNumber(ai.output_tokens_est)}
                  </dd>
                  <dt>Stages</dt>
                  <dd className="text-right text-foreground">{Object.entries(ai.stages).map(([k, v]) => `${k}:${v}`).join(" ")}</dd>
                  <dt>References validated</dt>
                  <dd className="text-right tabular-nums text-foreground">
                    {ai.validation.refs_valid ?? 0} ok · {ai.validation.refs_dropped ?? 0} dropped
                  </dd>
                </dl>
              ) : (
                <p className="text-muted">Configure a provider in Settings to add file, module and system-level interpretation.</p>
              )}
              {ai.errors.length ? (
                <details className="mt-2">
                  <summary className="cursor-pointer text-warning">{ai.errors.length} AI notices</summary>
                  <ul className="mt-1 space-y-1 text-muted">
                    {ai.errors.slice(0, 8).map((e, i) => (
                      <li key={i}>• {e}</li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <div>
              <CardTitle>API inventory</CardTitle>
              <CardDescription>{intel.routes.length} endpoints with resolved router prefixes.</CardDescription>
            </div>
            <Link href={`${base}/architecture?view=api`} className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">
              API graph <ArrowRight className="size-3" />
            </Link>
          </CardHeader>
          <CardContent className="px-0">
            {intel.routes.length ? (
              <div className="scrollbar-thin max-h-80 overflow-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 bg-surface">
                    <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-subtle">
                      <th className="px-5 py-2 font-medium">Method</th>
                      <th className="px-3 py-2 font-medium">Path</th>
                      <th className="px-3 py-2 font-medium">Handler</th>
                      <th className="px-3 py-2 font-medium">Auth</th>
                      <th className="px-3 py-2 font-medium">Location</th>
                    </tr>
                  </thead>
                  <tbody>
                    {intel.routes.map((r, i) => (
                      <tr key={i} className="border-b border-border last:border-0">
                        <td className="px-5 py-1.5 font-mono font-semibold">{r.method}</td>
                        <td className="px-3 py-1.5 font-mono">{r.path}</td>
                        <td className="px-3 py-1.5 font-mono text-muted">{r.handler ?? "—"}</td>
                        <td className="px-3 py-1.5">{r.auth.length ? <Badge variant="primary">{r.auth[0]}</Badge> : <span className="text-subtle">none</span>}</td>
                        <td className="px-3 py-1.5">
                          <SourceChip file={r.file} start={r.line} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="px-5">
                <EmptyState title="No API routes detected">The repository contains no route definitions in a supported framework.</EmptyState>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Potential issues</CardTitle>
              <CardDescription>Static detectors{ai.enabled ? " + AI review (marked for verification)" : ""}.</CardDescription>
            </div>
            <Link href={`${base}/issues`} className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">
              All <ArrowRight className="size-3" />
            </Link>
          </CardHeader>
          <CardContent className="space-y-4">
            <SeverityBars counts={sev} />
            <ul className="space-y-2 border-t border-border pt-3">
              {topFindings.map((f) => (
                <li key={f.id} className="text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <SeverityBadge value={f.severity} />
                    <FindingStatusBadge value={f.status} />
                  </div>
                  <p className="mt-0.5 line-clamp-2 font-medium">{f.title}</p>
                  {f.file ? <SourceChip file={f.file} start={f.line_start} /> : null}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-3">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Architecture layers</CardTitle>
              <CardDescription>From file roles (AST) and path conventions.</CardDescription>
            </div>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {intel.components.map((c) => (
                <li key={c.layer} className="flex items-center justify-between gap-2 text-sm">
                  <span className="flex items-center gap-2">
                    <span className="font-medium">{LAYER_LABEL[c.layer] ?? c.layer}</span>
                    <EvidenceBadge value={c.classification} />
                  </span>
                  <span className="text-xs tabular-nums text-muted">{c.files.length ? `${c.files.length} files` : c.evidence[0]?.replace("technologies: ", "")}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Data model</CardTitle>
              <CardDescription>{intel.db_models.length} models / tables.</CardDescription>
            </div>
            <Link href={`${base}/architecture?view=database`} className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">
              ER graph <ArrowRight className="size-3" />
            </Link>
          </CardHeader>
          <CardContent>
            {intel.db_models.length ? (
              <ul className="space-y-2">
                {intel.db_models.slice(0, 12).map((m) => (
                  <li key={`${m.file}:${m.name}`} className="flex items-center justify-between gap-2 text-sm">
                    <span className="min-w-0 truncate">
                      <span className="font-medium">{m.name}</span> <span className="text-xs text-subtle">{m.orm}</span>
                    </span>
                    <span className="shrink-0 text-xs tabular-nums text-muted">
                      {m.fields.length} fields · {m.relationships.length} rel
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-muted">No ORM models, Prisma schemas or SQL DDL were found.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div>
              <CardTitle>Repository structure</CardTitle>
              <CardDescription>File counts per directory (excluded paths omitted).</CardDescription>
            </div>
          </CardHeader>
          <CardContent>{intel.tree ? <DirectoryTree root={intel.tree} /> : null}</CardContent>
        </Card>
      </div>

      {syn.workflows.length || syn.architecture.length ? (
        <div className="grid gap-6 xl:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Architecture interpretation</CardTitle>
            </CardHeader>
            <CardContent>
              <ClaimList claims={[...syn.architecture, ...syn.authentication]} empty="No architecture interpretation." />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <div>
                <CardTitle>Core workflows</CardTitle>
                <CardDescription>Traced by the AI from routes, call lists and database operations.</CardDescription>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {syn.workflows.map((w, i) => (
                <div key={i} className="rounded-lg border border-border p-3">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">{w.name}</span>
                    <EvidenceBadge value="AI_INTERPRETED" />
                  </div>
                  <p className="mt-1 text-xs text-muted">
                    <span className="font-medium text-foreground">Trigger:</span> {w.trigger} · <span className="font-medium text-foreground">Handler:</span> {w.handler}
                  </p>
                  <ol className="mt-2 list-decimal space-y-0.5 pl-5 text-xs text-muted">
                    {w.steps.slice(0, 6).map((s, j) => (
                      <li key={j}>{s}</li>
                    ))}
                  </ol>
                </div>
              ))}
            </CardContent>
          </Card>
        </div>
      ) : null}
    </div>
  );
}
