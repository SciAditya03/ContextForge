"use client";
import { KeyRound, Search } from "lucide-react";
import { useMemo, useState } from "react";
import { SourceChip } from "@/components/domain/badges";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ErrorBox, Skeleton } from "@/components/ui/misc";
import { SegmentedControl } from "@/components/ui/tabs";
import { CoverageMeter } from "@/features/charts";
import { useProject } from "@/features/project-context";
import { useAsync } from "@/hooks/use-async";
import { api } from "@/lib/api";
import { cn, formatNumber } from "@/lib/utils";

const STATUS_LABEL: Record<string, string> = {
  analysed: "AI + deterministic",
  deterministic_only: "Deterministic only",
  skipped: "Skipped",
  excluded: "Excluded",
  failed: "Failed",
};

export default function FilesPage() {
  const { id, intel } = useProject();
  const files = useAsync(() => api.files(id), [id]);
  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");
  const rows = useMemo(
    () => (files.data ?? []).filter((f) => (status === "all" || (f.analysis ?? f.status) === status) && (!q || f.path.toLowerCase().includes(q.toLowerCase()))),
    [files.data, status, q],
  );
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    (files.data ?? []).forEach((f) => (c[f.analysis ?? f.status] = (c[f.analysis ?? f.status] ?? 0) + 1));
    return c;
  }, [files.data]);
  if (!intel) return <Skeleton className="h-96" />;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Analysis manifest</CardTitle>
            <CardDescription>Every file in the archive with the reason it was or was not analysed. Also exported as data/ANALYSIS_MANIFEST.json.</CardDescription>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <CoverageMeter summary={intel.manifest_summary} />
          <div className="flex flex-wrap items-center gap-2">
            <SegmentedControl
              ariaLabel="Status filter"
              value={status}
              onChange={setStatus}
              options={[{ value: "all", label: "All", count: files.data?.length ?? 0 }, ...Object.keys(STATUS_LABEL).filter((k) => counts[k]).map((k) => ({ value: k, label: STATUS_LABEL[k], count: counts[k] }))]}
            />
            <div className="relative ml-auto w-full sm:w-72">
              <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-subtle" />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by path" className="h-8 pl-8 text-xs" aria-label="Filter files by path" />
            </div>
          </div>
          {files.error ? <ErrorBox message={files.error} /> : null}
          <div className="scrollbar-thin max-h-[60vh] overflow-auto rounded-lg border border-border">
            <table className="w-full min-w-[760px] text-xs">
              <thead className="sticky top-0 bg-surface-2">
                <tr className="text-left text-[11px] uppercase tracking-wide text-subtle">
                  <th className="px-3 py-2 font-medium">Path</th>
                  <th className="px-3 py-2 font-medium">Language</th>
                  <th className="px-3 py-2 font-medium">Category</th>
                  <th className="px-3 py-2 text-right font-medium">Lines</th>
                  <th className="px-3 py-2 font-medium">Analysis</th>
                  <th className="px-3 py-2 font-medium">Reason</th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 2000).map((f) => (
                  <tr key={f.path} className="border-t border-border">
                    <td className="px-3 py-1.5 font-mono">
                      {f.path}
                      {f.is_entry_point ? <Badge variant="primary" className="ml-2">entry</Badge> : null}
                      {f.has_secrets ? (
                        <span title="Contains a detected secret (redacted)" className="ml-2 inline-flex text-critical">
                          <KeyRound className="size-3.5" />
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-1.5 text-muted">{f.language ?? "—"}</td>
                    <td className="px-3 py-1.5 text-muted">{f.category}</td>
                    <td className="px-3 py-1.5 text-right tabular-nums">{f.lines ? formatNumber(f.lines) : "—"}</td>
                    <td className={cn("px-3 py-1.5", f.analysis === "failed" && "text-critical")}>{STATUS_LABEL[f.analysis ?? f.status] ?? f.analysis ?? f.status}</td>
                    <td className="px-3 py-1.5 text-muted">{f.analysis_reason ?? f.status_reason ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Dependencies</CardTitle>
              <CardDescription>Declared in manifests; “never imported” is a hint, not proof.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="px-0">
            <div className="scrollbar-thin max-h-96 overflow-auto">
              <table className="w-full text-xs">
                <tbody>
                  {intel.dependencies.map((d, i) => (
                    <tr key={i} className="border-t border-border">
                      <td className="px-5 py-1.5 font-mono">{d.name}</td>
                      <td className="px-3 py-1.5 font-mono text-muted">{d.version ?? ""}</td>
                      <td className="px-3 py-1.5 text-muted">{d.dev ? "dev" : "runtime"}</td>
                      <td className="px-3 py-1.5 text-muted">{d.category ?? ""}</td>
                      <td className="px-3 py-1.5">{d.used === false ? <span className="text-warning">never imported</span> : d.used ? <span className="text-[var(--success-text)]">imported</span> : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <div>
              <CardTitle>Environment variables</CardTitle>
              <CardDescription>Names only — values are never shown or stored.</CardDescription>
            </div>
          </CardHeader>
          <CardContent className="px-0">
            <div className="scrollbar-thin max-h-96 overflow-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wide text-subtle">
                    <th className="px-5 py-1.5 font-medium">Name</th>
                    <th className="px-3 py-1.5 font-medium">Documented</th>
                    <th className="px-3 py-1.5 font-medium">Read at</th>
                  </tr>
                </thead>
                <tbody>
                  {intel.env_vars.map((e) => (
                    <tr key={e.name} className="border-t border-border align-top">
                      <td className="px-5 py-1.5 font-mono">{e.name}</td>
                      <td className="px-3 py-1.5">{e.defined_in.length ? "yes" : <span className="text-warning">no</span>}</td>
                      <td className="space-y-1 px-3 py-1.5">
                        {e.used_in.slice(0, 2).map((r, i) => (
                          <div key={i}>
                            <SourceChip file={r.file} start={r.line_start} />
                          </div>
                        ))}
                        {!e.used_in.length ? <span className="text-subtle">not read in code</span> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
