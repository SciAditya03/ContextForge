"use client";
import GithubSlugger from "github-slugger";
import { BookOpenText, Braces, Download, FileText, Layers, Search, Star, X } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { CopyButton, EmptyState, ErrorBox, Skeleton, Spinner } from "@/components/ui/misc";
import { Markdown } from "@/features/markdown";
import { useProject } from "@/features/project-context";
import { useAsync } from "@/hooks/use-async";
import { api, apiUrl } from "@/lib/api";
import { cn, extractHeadings, formatBytes } from "@/lib/utils";
import type { DocumentEntry, SearchResult } from "@/types/api";

const GROUPS: { key: DocumentEntry["group"]; label: string; Icon: typeof Star }[] = [
  { key: "master", label: "Master context", Icon: Star },
  { key: "modular", label: "Modular documents", Icon: FileText },
  { key: "layer", label: "Analysis layers", Icon: Layers },
  { key: "data", label: "Data & manifest", Icon: Braces },
];

function Explorer() {
  const { id } = useProject();
  const router = useRouter();
  const params = useSearchParams();
  const docs = useAsync(() => api.documents(id), [id]);
  const current = params.get("doc") || "CONTEXTFORGE_PROJECT_CONTEXT.md";
  const pendingAnchor = useRef<string | null>(null);
  const content = useAsync(() => api.document(id, current), [id, current]);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [filter, setFilter] = useState("");

  const isMarkdown = current.endsWith(".md");
  const text = content.data ?? "";
  const headings = useMemo(() => (isMarkdown ? extractHeadings(text, new GithubSlugger(), 3) : []), [text, isMarkdown]);
  const doc = docs.data?.find((d) => d.path === current);

  useEffect(() => {
    if (!content.data || !pendingAnchor.current) return;
    const anchor = pendingAnchor.current;
    pendingAnchor.current = null;
    requestAnimationFrame(() => document.getElementById(anchor)?.scrollIntoView({ block: "start" }));
  }, [content.data]);

  function open(path: string, anchor?: string) {
    pendingAnchor.current = anchor ?? null;
    if (path === current && anchor) {
      document.getElementById(anchor)?.scrollIntoView({ block: "start" });
      return;
    }
    router.replace(`?doc=${encodeURIComponent(path)}`, { scroll: false });
    if (!anchor) window.scrollTo({ top: 0 });
  }

  async function runSearch(e: React.FormEvent) {
    e.preventDefault();
    if (q.trim().length < 2) return;
    setSearching(true);
    try {
      setResults((await api.search(id, q.trim())).results);
    } finally {
      setSearching(false);
    }
  }

  const visibleDocs = (docs.data ?? []).filter((d) => !filter || d.title.toLowerCase().includes(filter.toLowerCase()) || d.path.toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)] 2xl:grid-cols-[260px_minmax(0,1fr)_220px]">
      <aside className="lg:sticky lg:top-16 lg:max-h-[calc(100vh-5rem)] lg:overflow-y-auto scrollbar-thin space-y-4">
        <form onSubmit={runSearch} className="relative">
          <Search className="pointer-events-none absolute top-2.5 left-2.5 size-4 text-subtle" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search all documents…" className="pl-8" aria-label="Search all documents" />
          {searching ? <Spinner className="absolute top-2.5 right-2.5" /> : null}
        </form>
        {results ? (
          <div className="rounded-xl border border-border bg-surface p-2">
            <div className="mb-1 flex items-center justify-between px-1.5 text-[11px] text-subtle">
              {results.length} matches for “{q}”
              <button onClick={() => setResults(null)} aria-label="Clear search" className="rounded p-0.5 hover:bg-surface-2 cursor-pointer">
                <X className="size-3.5" />
              </button>
            </div>
            <ul className="scrollbar-thin max-h-72 overflow-y-auto">
              {results.slice(0, 100).map((r, i) => (
                <li key={i}>
                  <button
                    onClick={() => open(r.path, r.heading ? new GithubSlugger().slug(r.heading.replace(/`([^`]*)`/g, "$1").replace(/\*\*([^*]*)\*\*/g, "$1")) : undefined)}
                    className="w-full rounded-md px-1.5 py-1.5 text-left hover:bg-surface-2 cursor-pointer"
                  >
                    <div className="truncate text-[11px] font-medium text-muted">
                      {r.title} · L{r.line}
                    </div>
                    <div className="line-clamp-2 font-mono text-[11px] text-foreground">{r.snippet}</div>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter documents" className="h-8 text-xs" aria-label="Filter documents" />
        {docs.error ? <ErrorBox message={docs.error} /> : null}
        {docs.loading ? <Skeleton className="h-96" /> : null}
        {GROUPS.map((g) => {
          const items = visibleDocs.filter((d) => d.group === g.key);
          if (!items.length) return null;
          return (
            <div key={g.key}>
              <div className="mb-1 flex items-center gap-1.5 px-1.5 text-[11px] font-semibold uppercase tracking-wide text-subtle">
                <g.Icon className="size-3" /> {g.label}
              </div>
              <ul>
                {items.map((d) => (
                  <li key={d.path}>
                    <button
                      onClick={() => open(d.path)}
                      className={cn(
                        "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[13px] cursor-pointer",
                        d.path === current ? "bg-primary-soft font-medium text-foreground" : "text-muted hover:bg-surface-2 hover:text-foreground",
                      )}
                      title={d.path}
                    >
                      <span className="truncate">{g.key === "modular" ? `${d.path.slice(0, 2)} · ${d.title}` : g.key === "data" ? d.path.replace("data/", "") : d.title}</span>
                      <span className="shrink-0 text-[10px] tabular-nums text-subtle">{formatBytes(d.size)}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          );
        })}
      </aside>

      <section className="min-w-0">
        <div className="sticky top-14 z-10 -mx-1 mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-surface/95 px-3 py-2 backdrop-blur lg:top-12">
          <div className="flex min-w-0 items-center gap-2">
            <BookOpenText className="size-4 shrink-0 text-primary" />
            <span className="truncate font-mono text-xs">{current}</span>
            {doc ? <span className="shrink-0 text-[11px] text-subtle">{formatBytes(doc.size)}</span> : null}
          </div>
          <div className="flex flex-wrap gap-1.5">
            <CopyButton text={() => text} label={isMarkdown ? "Copy Markdown" : "Copy JSON"} />
            <a className={buttonVariants({ variant: "secondary", size: "sm" })} href={apiUrl(`/api/projects/${id}/download/doc/${current}`)}>
              <Download /> Download
            </a>
            <a className={buttonVariants({ size: "sm" })} href={apiUrl(`/api/projects/${id}/download/package`)}>
              <Download /> Full package
            </a>
          </div>
        </div>
        <div className="rounded-xl border border-border bg-surface px-5 py-6 shadow-[var(--shadow)] sm:px-8">
          {content.error ? <ErrorBox message={content.error} /> : null}
          {content.loading ? (
            <div className="space-y-3">
              <Skeleton className="h-8 w-2/3" />
              <Skeleton className="h-4" />
              <Skeleton className="h-4 w-5/6" />
              <Skeleton className="h-40" />
            </div>
          ) : isMarkdown ? (
            <Markdown source={text} />
          ) : text ? (
            <pre className="scrollbar-thin max-h-[75vh] overflow-auto rounded-lg bg-[var(--code-bg)] p-4 font-mono text-xs">{tryPretty(text)}</pre>
          ) : (
            <EmptyState title="Empty document" />
          )}
        </div>
      </section>

      {headings.length ? (
        <nav className="hidden 2xl:block 2xl:sticky 2xl:top-16 2xl:max-h-[calc(100vh-5rem)] 2xl:overflow-y-auto scrollbar-thin" aria-label="Table of contents">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-subtle">On this page</div>
          <ul className="space-y-0.5 border-l border-border">
            {headings.map((h, i) => (
              <li key={`${h.id}-${i}`}>
                <a
                  href={`#${h.id}`}
                  onClick={(e) => {
                    e.preventDefault();
                    document.getElementById(h.id)?.scrollIntoView({ block: "start" });
                  }}
                  className={cn("-ml-px block truncate border-l border-transparent py-0.5 text-xs text-muted hover:border-primary hover:text-foreground", h.depth === 1 && "pl-2 font-medium", h.depth === 2 && "pl-3", h.depth === 3 && "pl-6 text-subtle")}
                >
                  {h.text}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      ) : null}
    </div>
  );
}

function tryPretty(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2).slice(0, 400_000);
  } catch {
    return text;
  }
}

export default function ContextPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <Explorer />
    </Suspense>
  );
}
