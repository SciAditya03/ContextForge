"use client";
import { ChevronDown, Search, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { FindingStatusBadge, SeverityBadge, SourceChip } from "@/components/domain/badges";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { EmptyState, Skeleton } from "@/components/ui/misc";
import { SegmentedControl } from "@/components/ui/tabs";
import { SeverityBars } from "@/features/charts";
import { useProject } from "@/features/project-context";
import { cn } from "@/lib/utils";
import type { Finding, Severity } from "@/types/api";

const RANK: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
type Group = "all" | "security" | "reliability" | "issue";

function FindingRow({ f }: { f: Finding }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="border-b border-border last:border-0">
      <button onClick={() => setOpen(!open)} className="grid w-full grid-cols-[1fr_auto] items-start gap-x-3 gap-y-1 px-4 py-3 text-left hover:bg-surface-2/50 cursor-pointer sm:grid-cols-[96px_1fr_auto]" aria-expanded={open}>
        <SeverityBadge value={f.severity} className="col-span-2 pt-0.5 sm:col-span-1" />
        <div className="min-w-0">
          <div className="text-sm font-medium [overflow-wrap:anywhere]">{f.title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {f.file ? <SourceChip file={f.file} start={f.line_start} end={f.line_end} /> : null}
            <Badge>{f.category}</Badge>
            {f.source === "ai" ? <Badge variant="primary">AI review</Badge> : null}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <FindingStatusBadge value={f.status} />
          <ChevronDown className={cn("size-4 text-subtle transition-transform", open && "rotate-180")} />
        </div>
      </button>
      {open ? (
        <div className="space-y-2 px-4 pb-4 text-sm sm:pl-[124px]">
          <p>{f.explanation}</p>
          {f.evidence ? (
            <div>
              <div className="text-[11px] font-medium uppercase tracking-wide text-subtle">Evidence</div>
              <pre className="mt-1 overflow-x-auto rounded-lg border border-border bg-[var(--code-bg)] px-3 py-2 font-mono text-xs">{f.evidence}</pre>
            </div>
          ) : null}
          {f.impact ? (
            <p className="text-muted">
              <span className="font-medium text-foreground">Potential impact:</span> {f.impact}
            </p>
          ) : null}
          {f.suggestion ? (
            <p className="text-muted">
              <span className="font-medium text-foreground">Suggested fix / investigation:</span> {f.suggestion}
            </p>
          ) : null}
          <p className="text-xs text-subtle">
            Confidence {f.confidence.toFixed(2)} · {f.source === "ai" ? "proposed by AI review — verify before acting" : "static analysis"}
          </p>
        </div>
      ) : null}
    </li>
  );
}

export default function IssuesPage() {
  const { intel } = useProject();
  const [group, setGroup] = useState<Group>("all");
  const [sev, setSev] = useState<Severity | null>(null);
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const findings = useMemo(() => intel?.findings ?? [], [intel]);
  const filtered = useMemo(
    () =>
      findings
        .filter((f) => (group === "all" || f.group === group) && (!sev || f.severity === sev) && (!status || f.status === status))
        .filter((f) => !q || `${f.title} ${f.file} ${f.category} ${f.explanation}`.toLowerCase().includes(q.toLowerCase()))
        .sort((a, b) => RANK[a.severity] - RANK[b.severity] || b.confidence - a.confidence),
    [findings, group, sev, status, q],
  );
  if (!intel) return <Skeleton className="h-96" />;
  const counts: Partial<Record<Severity, number>> = {};
  findings.filter((f) => group === "all" || f.group === group).forEach((f) => (counts[f.severity] = (counts[f.severity] ?? 0) + 1));
  const g = (k: Group) => findings.filter((f) => k === "all" || f.group === k).length;

  return (
    <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
      <div className="space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>Severity</CardTitle>
          </CardHeader>
          <CardContent>
            <SeverityBars counts={counts} onSelect={setSev} selected={sev} />
            <p className="mt-3 text-[11px] text-subtle">Click a bar to filter. Status colours are always paired with an icon and label.</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="space-y-2 pt-5 text-xs text-muted">
            <p>
              <span className="font-medium text-foreground">Confirmed</span> — directly evidenced in code or configuration.
            </p>
            <p>
              <span className="font-medium text-foreground">Suspicious</span> — pattern match that needs context.
            </p>
            <p>
              <span className="font-medium text-foreground">Verify manually</span> — cannot be decided statically, or proposed by AI.
            </p>
            <p className="pt-1">Secret values are always redacted; they were never sent to an AI provider.</p>
          </CardContent>
        </Card>
      </div>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <SegmentedControl<Group>
            ariaLabel="Finding group"
            value={group}
            onChange={setGroup}
            options={[
              { value: "all", label: "All", count: g("all") },
              { value: "security", label: "Security", count: g("security") },
              { value: "reliability", label: "Reliability", count: g("reliability") },
              { value: "issue", label: "Bugs & code", count: g("issue") },
            ]}
          />
          <Select value={status} onChange={(e) => setStatus(e.target.value)} className="h-8 w-44 text-xs" aria-label="Status filter">
            <option value="">All statuses</option>
            <option value="confirmed">Confirmed</option>
            <option value="suspicious">Suspicious</option>
            <option value="manual_verification">Verify manually</option>
          </Select>
          <div className="relative ml-auto w-full sm:w-64">
            <Search className="pointer-events-none absolute top-2 left-2.5 size-4 text-subtle" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search findings" className="h-8 pl-8 text-xs" aria-label="Search findings" />
          </div>
        </div>
        <Card>
          {filtered.length ? (
            <ul>
              {filtered.map((f) => (
                <FindingRow key={f.id} f={f} />
              ))}
            </ul>
          ) : (
            <div className="p-5">
              <EmptyState icon={<ShieldCheck />} title="No findings match">
                Adjust the filters, or this category is clean for the analysed files.
              </EmptyState>
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
