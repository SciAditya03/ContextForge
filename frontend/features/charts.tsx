"use client";
import { useState } from "react";
import { SEVERITY } from "@/components/domain/badges";
import { cn, compactNumber, formatNumber } from "@/lib/utils";
import type { Severity } from "@/types/api";

const SERIES = Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`);

interface Segment {
  key: string;
  label: string;
  value: number;
  color: string;
  detail?: string;
}

/** Horizontal part-to-whole bar: 2px surface gaps between segments, rounded outer ends, hover tooltip, legend with values. */
export function SegmentedBar({ segments, height = 12, unit = "", ariaLabel }: { segments: Segment[]; height?: number; unit?: string; ariaLabel: string }) {
  const [hover, setHover] = useState<{ seg: Segment; x: number } | null>(null);
  const total = segments.reduce((s, x) => s + x.value, 0);
  if (!total) return <p className="text-xs text-subtle">No data.</p>;
  return (
    <div className="relative" onMouseLeave={() => setHover(null)}>
      <div role="img" aria-label={ariaLabel} className="flex w-full gap-[2px] overflow-hidden rounded" style={{ height }}>
        {segments
          .filter((s) => s.value > 0)
          .map((s) => (
            <div
              key={s.key}
              className="h-full min-w-[3px] transition-opacity first:rounded-l last:rounded-r"
              style={{ flexGrow: s.value, flexBasis: 0, background: s.color, opacity: hover && hover.seg.key !== s.key ? 0.45 : 1 }}
              onMouseMove={(e) => {
                const box = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect();
                setHover({ seg: s, x: e.clientX - box.left });
              }}
            />
          ))}
      </div>
      {hover ? (
        <div
          className="pointer-events-none absolute z-20 -translate-x-1/2 rounded-lg border border-border bg-surface px-2.5 py-1.5 text-xs shadow-[var(--shadow)]"
          style={{ left: hover.x, top: height + 8 }}
        >
          <div className="flex items-center gap-1.5 font-medium">
            <span className="size-2 rounded-sm" style={{ background: hover.seg.color }} />
            {hover.seg.label}
          </div>
          <div className="mt-0.5 tabular-nums text-muted">
            {formatNumber(hover.seg.value)}
            {unit} · {((hover.seg.value / total) * 100).toFixed(1)}%{hover.seg.detail ? ` · ${hover.seg.detail}` : ""}
          </div>
        </div>
      ) : null}
      <ul className="mt-3 grid grid-cols-1 gap-y-1.5 text-xs">
        {segments.map((s) => (
          <li key={s.key} className="flex min-w-0 items-center gap-2">
            <span className="size-2.5 shrink-0 rounded-sm" style={{ background: s.color }} aria-hidden />
            <span className="min-w-0 truncate text-muted" title={s.label}>{s.label}</span>
            <span className="ml-auto tabular-nums text-foreground">
              {compactNumber(s.value)}
              <span className="text-subtle"> · {((s.value / total) * 100).toFixed(0)}%</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function LanguageBar({ languages }: { languages: Record<string, { files: number; code_lines: number }> }) {
  const code = Object.entries(languages)
    .filter(([name, v]) => v.code_lines > 0 && !["Markdown", "Text", "JSON", "YAML", "TOML", "INI", "XML", "Env", "reStructuredText"].includes(name))
    .sort((a, b) => b[1].code_lines - a[1].code_lines);
  const top = code.slice(0, 7);
  const rest = code.slice(7);
  const segments: Segment[] = top.map(([name, v], i) => ({ key: name, label: name, value: v.code_lines, color: SERIES[i], detail: `${v.files} files` }));
  if (rest.length) {
    segments.push({
      key: "other",
      label: `Other (${rest.length})`,
      value: rest.reduce((s, [, v]) => s + v.code_lines, 0),
      color: "var(--series-other)",
      detail: rest.map(([n]) => n).join(", "),
    });
  }
  return <SegmentedBar segments={segments} unit=" lines" ariaLabel="Lines of code by language" />;
}

export function CoverageMeter({ summary }: { summary: Record<string, number> }) {
  const order: [string, string, string][] = [
    ["analysed", "AI + deterministic", "var(--status-good)"],
    ["deterministic_only", "Deterministic only", "var(--series-1)"],
    ["skipped", "Skipped", "var(--series-other)"],
    ["excluded", "Excluded", "var(--subtle)"],
    ["failed", "Failed", "var(--status-critical)"],
  ];
  const segments = order.filter(([k]) => summary[k]).map(([k, label, color]) => ({ key: k, label, value: summary[k], color }));
  return <SegmentedBar segments={segments} unit=" files" ariaLabel="Analysis coverage by file status" height={10} />;
}

export function SeverityBars({ counts, onSelect, selected }: { counts: Partial<Record<Severity, number>>; onSelect?: (s: Severity | null) => void; selected?: Severity | null }) {
  const levels: Severity[] = ["critical", "high", "medium", "low", "info"];
  const max = Math.max(1, ...levels.map((l) => counts[l] ?? 0));
  return (
    <ul className="space-y-2">
      {levels.map((l) => {
        const n = counts[l] ?? 0;
        const s = SEVERITY[l];
        const active = selected === l;
        return (
          <li key={l}>
            <button
              type="button"
              disabled={!onSelect}
              onClick={() => onSelect?.(active ? null : l)}
              className={cn("group grid w-full grid-cols-[92px_1fr_40px] items-center gap-3 rounded-md px-1 py-0.5 text-left text-xs", onSelect && "cursor-pointer hover:bg-surface-2", active && "bg-surface-2")}
              title={`${s.label}: ${n} findings`}
            >
              <span className="flex items-center gap-1.5 font-medium">
                <s.Icon className="size-3.5" style={{ color: s.color }} aria-hidden />
                {s.label}
              </span>
              <span className="h-2 w-full rounded-sm bg-surface-3">
                <span className="block h-full rounded-sm" style={{ width: `${n ? Math.max(3, (n / max) * 100) : 0}%`, background: s.color }} />
              </span>
              <span className="text-right tabular-nums text-foreground">{n}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

export function StatTile({ label, value, sub, icon }: { label: string; value: React.ReactNode; sub?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface px-4 py-3.5 shadow-[var(--shadow)]">
      <div className="flex items-center justify-between text-xs font-medium text-muted">
        {label}
        {icon ? <span className="text-subtle [&_svg]:size-4">{icon}</span> : null}
      </div>
      <div className="mt-1.5 text-2xl font-semibold tracking-tight tabular-nums">{value}</div>
      {sub ? <div className="mt-0.5 truncate text-xs text-subtle">{sub}</div> : null}
    </div>
  );
}
