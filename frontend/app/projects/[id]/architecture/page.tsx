"use client";
import dagre from "@dagrejs/dagre";
import {
  Background,
  Controls,
  type Edge,
  Handle,
  MarkerType,
  MiniMap,
  type Node,
  type NodeProps,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Database, FileCode2, Globe, Network, Search, X } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { SourceChip } from "@/components/domain/badges";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorBox, Skeleton } from "@/components/ui/misc";
import { SegmentedControl } from "@/components/ui/tabs";
import { useProject } from "@/features/project-context";
import { useAsync } from "@/hooks/use-async";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { GraphEdge, GraphNode, GraphResponse } from "@/types/api";

type View = "modules" | "files" | "api" | "database";

// Role → categorical slot (fixed order; colour follows the role, never its rank)
const ROLE_COLOR: Record<string, string> = {
  "api-routes": "var(--series-1)",
  controller: "var(--series-1)",
  service: "var(--series-2)",
  "data-model": "var(--series-3)",
  "data-access": "var(--series-3)",
  repository: "var(--series-3)",
  "ui-component": "var(--series-7)",
  page: "var(--series-7)",
  hook: "var(--series-7)",
  auth: "var(--series-8)",
  middleware: "var(--series-5)",
  "api-client": "var(--series-4)",
  state: "var(--series-6)",
};
const ROLE_LEGEND: [string, string][] = [
  ["API / controllers", "var(--series-1)"],
  ["Services", "var(--series-2)"],
  ["Data / models", "var(--series-3)"],
  ["API clients", "var(--series-4)"],
  ["Middleware", "var(--series-5)"],
  ["State", "var(--series-6)"],
  ["UI / pages", "var(--series-7)"],
  ["Auth", "var(--series-8)"],
];

/** SVG presentation attributes cannot use var(); resolve tokens to concrete colours (theme-aware). */
function resolveColor(c: string): string {
  if (typeof window === "undefined" || !c.startsWith("var(")) return c;
  const name = c.slice(4, -1).trim();
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

function nodeColor(n: GraphNode): string {
  if (n.type === "route") return "var(--series-1)";
  if (n.type === "model") return "var(--series-3)";
  if (n.type === "external") return "var(--series-other)";
  const roles = (n.data.roles as string[] | Record<string, number> | undefined) ?? [];
  const list = Array.isArray(roles) ? roles : Object.entries(roles).sort((a, b) => b[1] - a[1]).map(([k]) => k);
  for (const r of ["auth", "api-routes", "controller", "service", "data-model", "data-access", "repository", "middleware", "api-client", "state", "page", "ui-component", "hook"]) {
    if (list.includes(r)) return ROLE_COLOR[r];
  }
  return "var(--subtle)";
}

interface CFNodeData extends Record<string, unknown> {
  g: GraphNode;
  color: string;
  dim: boolean;
  sub: string;
}

function CFNode({ data, selected }: NodeProps<Node<CFNodeData>>) {
  const { g, color, dim, sub } = data;
  const Icon = g.type === "route" ? Globe : g.type === "model" ? Database : g.type === "module" ? Network : FileCode2;
  return (
    <div
      className={cn(
        "w-[210px] rounded-lg border bg-surface px-2.5 py-2 text-left shadow-[var(--shadow)] transition-opacity",
        selected ? "border-primary ring-2 ring-primary/30" : "border-border-strong",
        dim && "opacity-25",
      )}
      style={{ borderLeft: `3px solid ${color}` }}
    >
      <Handle type="target" position={Position.Left} className="!size-1.5 !border-0 !bg-border-strong" />
      <div className="flex items-center gap-1.5">
        <Icon className="size-3.5 shrink-0" style={{ color }} />
        <span className="truncate font-mono text-[11px] font-medium" title={g.label}>
          {g.label}
        </span>
      </div>
      {sub ? <div className="mt-0.5 truncate text-[10px] text-subtle">{sub}</div> : null}
      <Handle type="source" position={Position.Right} className="!size-1.5 !border-0 !bg-border-strong" />
    </div>
  );
}

const nodeTypes = { cf: CFNode };

function subtitle(n: GraphNode, view: View): string {
  const d = n.data;
  if (view === "modules") return `${d.files ?? 0} files · ${Object.keys((d.roles as Record<string, number>) ?? {}).slice(0, 2).join(", ")}`;
  if (n.type === "route") return `${String(d.handler ?? "")} · ${Array.isArray(d.auth) && d.auth.length ? "auth" : "no auth"}`;
  if (n.type === "model") return `${String(d.orm ?? "")} · ${(d.fields as unknown[] | undefined)?.length ?? 0} fields`;
  if (n.type === "file") return n.group ?? String(d.path ?? "");
  return "";
}

function layout(graph: GraphResponse, view: View, filter: string): { nodes: Node<CFNodeData>[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 18, ranksep: view === "database" ? 90 : 70, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));
  const ids = new Set(graph.nodes.map((n) => n.id));
  const f = filter.trim().toLowerCase();
  graph.nodes.forEach((n) => g.setNode(n.id, { width: 216, height: 50 }));
  const edges = graph.edges.filter((e) => ids.has(e.source) && ids.has(e.target) && e.source !== e.target);
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);
  const match = (n: GraphNode) => !f || n.label.toLowerCase().includes(f) || n.id.toLowerCase().includes(f);
  const nodes: Node<CFNodeData>[] = graph.nodes.map((n) => {
    const p = g.node(n.id);
    return {
      id: n.id,
      type: "cf",
      position: { x: (p?.x ?? 0) - 108, y: (p?.y ?? 0) - 25 },
      // uncontrolled flow: give the minimap dimensions without forcing node size
      initialWidth: 210,
      initialHeight: 50,
      data: { g: n, color: nodeColor(n), dim: !match(n), sub: subtitle(n, view) },
    };
  });
  const rfEdges: Edge[] = edges.map((e: GraphEdge, i) => ({
    id: `e${i}`,
    source: e.source,
    target: e.target,
    animated: e.type === "calls_api",
    label: view === "database" ? String(e.data?.field ?? e.type) : view === "modules" && e.weight > 1 ? String(e.weight) : undefined,
    labelStyle: { fontSize: 10, fill: "var(--muted)" },
    labelBgStyle: { fill: resolveColor("var(--surface)") },
    labelBgPadding: [4, 2] as [number, number],
    style: { stroke: e.type === "calls_api" ? "var(--series-4)" : "var(--border-strong)", strokeWidth: view === "modules" ? Math.min(4, 1 + Math.log2(e.weight || 1)) : 1.2 },
    markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: "var(--border-strong)" },
  }));
  return { nodes, edges: rfEdges };
}

function Inspector({ node, graph, onClose }: { node: GraphNode; graph: GraphResponse; onClose: () => void }) {
  const incoming = graph.edges.filter((e) => e.target === node.id);
  const outgoing = graph.edges.filter((e) => e.source === node.id);
  const d = node.data;
  return (
    <div className="absolute top-3 right-3 z-10 w-80 max-w-[calc(100%-1.5rem)] rounded-xl border border-border bg-surface/95 p-4 text-xs shadow-[var(--shadow)] backdrop-blur">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[10px] font-semibold uppercase tracking-wide text-subtle">{node.type}</div>
          <div className="mt-0.5 break-all font-mono text-sm font-medium">{node.id.replace(/^route:/, "")}</div>
        </div>
        <button onClick={onClose} aria-label="Close inspector" className="rounded p-1 text-subtle hover:bg-surface-2 cursor-pointer">
          <X className="size-4" />
        </button>
      </div>
      <dl className="mt-3 space-y-1.5">
        {Object.entries(d)
          .filter(([k, v]) => k !== "fields" && v !== null && v !== "" && !(Array.isArray(v) && !v.length))
          .slice(0, 10)
          .map(([k, v]) => (
            <div key={k} className="grid grid-cols-[90px_1fr] gap-2">
              <dt className="text-subtle">{k}</dt>
              <dd className="break-words font-mono text-[11px]">{typeof v === "object" ? (Array.isArray(v) ? v.join(", ") : Object.entries(v as object).map(([a, b]) => `${a}:${b}`).join(", ")) : String(v)}</dd>
            </div>
          ))}
      </dl>
      {Array.isArray(d.fields) && d.fields.length ? (
        <div className="mt-3">
          <div className="mb-1 text-subtle">Fields</div>
          <ul className="scrollbar-thin max-h-40 space-y-0.5 overflow-y-auto font-mono text-[11px]">
            {(d.fields as { name: string; type: string | null; pk: boolean; fk: string | null }[]).map((f) => (
              <li key={f.name}>
                {f.name} <span className="text-subtle">{f.type}</span> {f.pk ? <span className="text-primary">PK</span> : null} {f.fk ? <span className="text-[var(--ev-inferred)]">→ {f.fk}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {typeof d.file === "string" ? (
        <div className="mt-3">
          <SourceChip file={d.file} start={typeof d.line === "number" ? d.line : null} />
        </div>
      ) : null}
      <div className="mt-3 grid grid-cols-2 gap-3 border-t border-border pt-3">
        <div>
          <div className="mb-1 text-subtle">Incoming ({incoming.length})</div>
          <ul className="space-y-0.5 font-mono text-[11px]">
            {incoming.slice(0, 8).map((e, i) => (
              <li key={i} className="truncate" title={e.source}>
                {e.source.split("/").pop()}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <div className="mb-1 text-subtle">Outgoing ({outgoing.length})</div>
          <ul className="space-y-0.5 font-mono text-[11px]">
            {outgoing.slice(0, 8).map((e, i) => (
              <li key={i} className="truncate" title={e.target}>
                {e.target.split("/").pop()}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

function GraphCanvas({ graph, view }: { graph: GraphResponse; view: View }) {
  const [filter, setFilter] = useState("");
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const { nodes, edges } = useMemo(() => layout(graph, view, filter), [graph, view, filter]);
  const rf = useReactFlow();
  useEffect(() => {
    const t = setTimeout(() => rf.fitView({ padding: 0.15, duration: 300 }), 50);
    return () => clearTimeout(t);
  }, [graph, view, rf]);
  if (!graph.nodes.length) {
    return (
      <div className="p-8">
        <EmptyState icon={<Network />} title="Nothing to show for this view">
          {view === "database" ? "No data models were extracted." : view === "api" ? "No routes or client calls were extracted." : "No parsed source modules."}
        </EmptyState>
      </div>
    );
  }
  return (
    <div className="relative h-[calc(100vh-15rem)] min-h-[520px]">
      <div className="absolute top-3 left-3 z-10 w-64">
        <Search className="pointer-events-none absolute top-2.5 left-2.5 z-10 size-4 text-subtle" />
        <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Highlight nodes…" className="bg-surface/95 pl-8 backdrop-blur" aria-label="Highlight nodes" />
      </div>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, n) => setSelected((n.data as CFNodeData).g)}
        onPaneClick={() => setSelected(null)}
        fitView
        minZoom={0.05}
        maxZoom={2}
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
        colorMode="system"
      >
        <Background gap={24} size={1} color="var(--grid)" />
        <Controls showInteractive={false} className="!border-border !bg-surface !shadow-[var(--shadow)] [&_button]:!border-border [&_button]:!bg-surface [&_button]:!fill-[var(--muted)]" />
        <MiniMap pannable zoomable nodeColor={(n) => resolveColor((n.data as CFNodeData).color)} nodeStrokeWidth={0} maskColor="rgba(128,128,128,0.18)" className="!border !border-border !bg-surface" />
      </ReactFlow>
      {selected ? <Inspector node={selected} graph={graph} onClose={() => setSelected(null)} /> : null}
      {graph.truncated ? (
        <div className="absolute bottom-3 left-1/2 -translate-x-1/2 rounded-full border border-border bg-surface px-3 py-1 text-[11px] text-muted">
          Showing the {graph.nodes.length} most connected of {graph.total_nodes} files
        </div>
      ) : null}
    </div>
  );
}

function ArchitectureExplorer() {
  const { id, intel } = useProject();
  const router = useRouter();
  const params = useSearchParams();
  const view = (params.get("view") as View) || "modules";
  const graph = useAsync(() => api.graph(id, view, 400), [id, view]);
  const cycles = intel?.graph.cycles ?? [];
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <SegmentedControl<View>
          ariaLabel="Graph view"
          value={view}
          onChange={(v) => router.replace(`?view=${v}`, { scroll: false })}
          options={[
            { value: "modules", label: "Modules" },
            { value: "files", label: "File dependencies" },
            { value: "api", label: "API & frontend calls" },
            { value: "database", label: "Database" },
          ]}
        />
        <p className="text-xs text-muted">
          {view === "modules" && "Directories, edges weighted by import count."}
          {view === "files" && "Internal imports between files (most connected first)."}
          {view === "api" && "Routes → handler files; animated edges are client calls matched to routes."}
          {view === "database" && "Models/tables with relationships and foreign keys."}
        </p>
      </div>
      <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-[var(--shadow)]">
        {graph.error ? (
          <div className="p-6">
            <ErrorBox message={graph.error} onRetry={graph.reload} />
          </div>
        ) : graph.loading || !graph.data ? (
          <Skeleton className="h-[560px] rounded-none" />
        ) : (
          <ReactFlowProvider key={view}>
            <GraphCanvas graph={graph.data} view={view} />
          </ReactFlowProvider>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-muted" aria-label="Legend">
        {ROLE_LEGEND.map(([label, color]) => (
          <span key={label} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-1 rounded-sm" style={{ background: color }} /> {label}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-1 rounded-sm" style={{ background: "var(--subtle)" }} /> Other
        </span>
      </div>
      {cycles.length ? (
        <div className="rounded-xl border border-warning/40 bg-warning/5 p-4 text-sm">
          <div className="font-medium">Import cycles ({cycles.length})</div>
          <ul className="mt-1 space-y-1 font-mono text-xs text-muted">
            {cycles.slice(0, 6).map((c, i) => (
              <li key={i}>{c.join(" ⇄ ")}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export default function ArchitecturePage() {
  return (
    <Suspense fallback={<Skeleton className="h-[560px]" />}>
      <ArchitectureExplorer />
    </Suspense>
  );
}
