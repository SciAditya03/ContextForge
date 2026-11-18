import { AlertOctagon, AlertTriangle, CheckCircle2, CircleDot, Info, Loader2, OctagonX, ShieldAlert, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import type { EvidenceClass, ProjectStatus, Severity } from "@/types/api";

const EV: Record<EvidenceClass, { label: string; fg: string; bg: string; title: string }> = {
  DETECTED: { label: "Detected", fg: "var(--ev-detected)", bg: "var(--ev-detected-bg)", title: "Extracted directly from source code, manifests or configuration" },
  INFERRED: { label: "Inferred", fg: "var(--ev-inferred)", bg: "var(--ev-inferred-bg)", title: "Derived from code relationships or conventions" },
  AI_INTERPRETED: { label: "AI", fg: "var(--ev-ai)", bg: "var(--ev-ai-bg)", title: "Model interpretation with validated source references" },
  UNKNOWN: { label: "Unknown", fg: "var(--ev-unknown)", bg: "var(--ev-unknown-bg)", title: "Insufficient evidence" },
};

export function EvidenceBadge({ value, className }: { value: EvidenceClass; className?: string }) {
  const e = EV[value] ?? EV.UNKNOWN;
  return (
    <span title={e.title} className={cn("inline-flex items-center rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wide", className)} style={{ color: e.fg, background: e.bg }}>
      {e.label}
    </span>
  );
}

export const SEVERITY: Record<Severity, { label: string; color: string; Icon: typeof AlertOctagon }> = {
  critical: { label: "Critical", color: "var(--status-critical)", Icon: OctagonX },
  high: { label: "High", color: "var(--status-serious)", Icon: AlertOctagon },
  medium: { label: "Medium", color: "var(--status-warning)", Icon: AlertTriangle },
  low: { label: "Low", color: "var(--series-1)", Icon: CircleDot },
  info: { label: "Info", color: "var(--status-info)", Icon: Info },
};

export function SeverityBadge({ value, className }: { value: Severity; className?: string }) {
  const s = SEVERITY[value] ?? SEVERITY.info;
  return (
    <span className={cn("inline-flex items-center gap-1 text-xs font-medium text-foreground", className)}>
      <s.Icon className="size-3.5" style={{ color: s.color }} aria-hidden />
      {s.label}
    </span>
  );
}

const FINDING_STATUS: Record<string, { label: string; cls: string }> = {
  confirmed: { label: "Confirmed", cls: "text-foreground border-border-strong" },
  suspicious: { label: "Suspicious", cls: "text-muted border-border" },
  manual_verification: { label: "Verify manually", cls: "text-muted border-dashed border-border-strong" },
};

export function FindingStatusBadge({ value }: { value: string }) {
  const s = FINDING_STATUS[value] ?? { label: value, cls: "text-muted border-border" };
  return <span className={cn("inline-flex rounded-md border px-1.5 py-0.5 text-[11px] font-medium", s.cls)}>{s.label}</span>;
}

export function ProjectStatusPill({ status }: { status: ProjectStatus | string }) {
  const map: Record<string, { label: string; Icon: typeof CheckCircle2; color: string; spin?: boolean }> = {
    completed: { label: "Completed", Icon: CheckCircle2, color: "var(--status-good)" },
    running: { label: "Analysing", Icon: Loader2, color: "var(--primary)", spin: true },
    queued: { label: "Queued", Icon: Loader2, color: "var(--subtle)", spin: true },
    failed: { label: "Failed", Icon: XCircle, color: "var(--status-critical)" },
    cancelled: { label: "Cancelled", Icon: ShieldAlert, color: "var(--subtle)" },
  };
  const s = map[status] ?? map.queued;
  return (
    <span className="inline-flex items-center gap-1.5 text-xs font-medium">
      <s.Icon className={cn("size-3.5", s.spin && "animate-spin")} style={{ color: s.color }} aria-hidden />
      {s.label}
    </span>
  );
}

export function SourceChip({ file, start, end }: { file: string; start?: number | null; end?: number | null }) {
  const label = start ? (end && end !== start ? `${file}:${start}-${end}` : `${file}:${start}`) : file;
  return (
    <code title={label} className="inline-block max-w-full truncate rounded border border-border bg-surface-2 px-1.5 py-0.5 align-middle font-mono text-[11px] text-muted">
      {label}
    </code>
  );
}
