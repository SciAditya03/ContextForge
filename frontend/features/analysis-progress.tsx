"use client";
import { AlertTriangle, CheckCircle2, Circle, CircleSlash, Loader2, XCircle } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, formatNumber } from "@/lib/utils";
import type { Project, Stage } from "@/types/api";

function StageIcon({ status }: { status: Stage["status"] }) {
  switch (status) {
    case "done":
      return <CheckCircle2 className="size-[18px] text-good" aria-label="done" />;
    case "running":
      return <Loader2 className="size-[18px] animate-spin text-primary" aria-label="running" />;
    case "failed":
      return <XCircle className="size-[18px] text-critical" aria-label="failed" />;
    case "skipped":
      return <CircleSlash className="size-[18px] text-subtle" aria-label="skipped" />;
    case "warning":
      return <AlertTriangle className="size-[18px] text-warning" aria-label="warning" />;
    default:
      return <Circle className="size-[18px] text-border-strong" aria-label="pending" />;
  }
}

export function AnalysisProgress({ project, stages, connected }: { project: Project; stages: Stage[]; connected: boolean }) {
  const doneCount = stages.filter((s) => ["done", "skipped", "warning"].includes(s.status)).length;
  const running = stages.find((s) => s.status === "running");
  const terminal = ["completed", "failed", "cancelled"].includes(project.status);
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>Analysis pipeline</CardTitle>
          <CardDescription>
            {doneCount} of {stages.length} stages finished
            {running ? ` · currently: ${running.label.toLowerCase()}` : ""}
            {!terminal ? (connected ? " · live" : " · reconnecting…") : ""}
          </CardDescription>
        </div>
        <div className="text-right text-xs text-subtle">Progress reflects real backend events; counts come from the pipeline.</div>
      </CardHeader>
      <CardContent>
        <ol className="relative space-y-0.5">
          {stages.map((s, i) => {
            const pct = s.status === "running" && s.total ? Math.min(100, Math.round(((s.done ?? 0) / s.total) * 100)) : null;
            return (
              <li key={s.key} className={cn("grid grid-cols-[28px_1fr] gap-3 rounded-lg px-2 py-2", s.status === "running" && "bg-primary-soft/40")} data-stage={s.key} data-status={s.status}>
                <div className="relative flex justify-center pt-0.5">
                  <StageIcon status={s.status} />
                  {i < stages.length - 1 ? <span className="absolute top-6 bottom-[-14px] w-px bg-border" aria-hidden /> : null}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <span className={cn("text-sm font-medium", s.status === "pending" && "text-subtle")}>
                      {i + 1}. {s.label}
                    </span>
                    <span className="text-xs tabular-nums text-subtle">
                      {s.total ? `${formatNumber(s.done)} / ${formatNumber(s.total)}` : s.done ? formatNumber(s.done) : ""}
                      {s.elapsed_s ? ` · ${s.elapsed_s.toFixed(1)}s` : ""}
                    </span>
                  </div>
                  {s.detail ? <p className={cn("mt-0.5 text-xs", s.status === "failed" ? "text-critical" : "text-muted")}>{s.detail}</p> : null}
                  {pct !== null ? (
                    <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-surface-3">
                      <div className="h-full rounded-full bg-primary transition-[width]" style={{ width: `${pct}%` }} />
                    </div>
                  ) : null}
                </div>
              </li>
            );
          })}
        </ol>
        {project.status === "failed" && project.error ? <p className="mt-4 rounded-lg border border-critical/40 bg-critical/5 px-3 py-2 text-sm text-critical">{project.error}</p> : null}
        {project.status === "cancelled" ? <p className="mt-4 text-sm text-muted">The analysis was cancelled. Temporary files were removed.</p> : null}
      </CardContent>
    </Card>
  );
}
