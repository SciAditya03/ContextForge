"use client";
import { Download, FileDown, Loader2, Square } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { ProjectStatusPill } from "@/components/domain/badges";
import { PageHeader } from "@/components/layout/app-shell";
import { Button, buttonVariants } from "@/components/ui/button";
import { ErrorBox, Skeleton } from "@/components/ui/misc";
import { AnalysisProgress } from "@/features/analysis-progress";
import { ProjectProvider } from "@/features/project-context";
import { useProjectStream } from "@/hooks/use-project-stream";
import { api, apiUrl } from "@/lib/api";
import { cn, formatBytes, timeAgo } from "@/lib/utils";

const TABS = [
  { href: "", label: "Intelligence" },
  { href: "/context", label: "Context explorer" },
  { href: "/architecture", label: "Architecture" },
  { href: "/issues", label: "Issues" },
  { href: "/files", label: "Files & coverage" },
];

export default function ProjectLayout({ children }: { children: React.ReactNode }) {
  const { id } = useParams<{ id: string }>();
  const pathname = usePathname();
  const { project, stages, error, connected } = useProjectStream(id);

  if (error) {
    return (
      <div className="p-8">
        <ErrorBox title="Project unavailable" message={error} />
      </div>
    );
  }
  if (!project) {
    return (
      <div className="space-y-4 p-8">
        <Skeleton className="h-10 w-72" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  const completed = project.status === "completed";
  const active = project.status === "running" || project.status === "queued";
  const base = `/projects/${id}`;
  return (
    <ProjectProvider value={{ id, project, stages, connected }}>
      <PageHeader
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            <Link href="/" className="hover:text-foreground">
              Workspace
            </Link>
            <span>/</span>
            <ProjectStatusPill status={project.status} />
            <span>·</span>
            <span>
              {project.archive_name} ({formatBytes(project.archive_size)}) · {project.options.depth} depth · {timeAgo(project.created_at)}
            </span>
          </span>
        }
        title={project.name}
        description={project.description ?? undefined}
        actions={
          completed ? (
            <>
              <a className={buttonVariants({ variant: "secondary" })} href={apiUrl(`/api/projects/${id}/download/master`)} data-testid="download-master">
                <FileDown /> Master .md
              </a>
              <a className={buttonVariants()} href={apiUrl(`/api/projects/${id}/download/package`)} data-testid="download-package">
                <Download /> Context package
              </a>
            </>
          ) : active ? (
            <Button variant="secondary" onClick={() => api.cancel(id).catch(() => undefined)}>
              <Square /> Cancel analysis
            </Button>
          ) : null
        }
      />
      {completed ? (
        <nav className="sticky top-14 z-20 border-b border-border bg-background/90 px-4 backdrop-blur sm:px-8 lg:top-0" aria-label="Project sections">
          <div className="scrollbar-thin -mb-px flex gap-1 overflow-x-auto">
            {TABS.map((t) => {
              const href = base + t.href;
              const isActive = t.href === "" ? pathname === base : pathname.startsWith(href);
              return (
                <Link
                  key={t.href}
                  href={href}
                  className={cn(
                    "whitespace-nowrap border-b-2 px-3 py-2.5 text-sm font-medium transition-colors",
                    isActive ? "border-primary text-foreground" : "border-transparent text-muted hover:text-foreground",
                  )}
                >
                  {t.label}
                </Link>
              );
            })}
          </div>
        </nav>
      ) : null}
      <div className="px-4 pt-6 pb-12 sm:px-8">
        {completed ? (
          children
        ) : (
          <div className="mx-auto max-w-3xl">
            {active ? (
              <p className="mb-4 flex items-center gap-2 text-sm text-muted">
                <Loader2 className="size-4 animate-spin text-primary" /> Analysing — you can leave this page; the analysis continues on the server.
              </p>
            ) : null}
            <AnalysisProgress project={project} stages={stages} connected={connected} />
          </div>
        )}
      </div>
    </ProjectProvider>
  );
}
