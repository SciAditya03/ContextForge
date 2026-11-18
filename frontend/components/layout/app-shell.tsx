"use client";
import { Boxes, FolderGit2, LayoutDashboard, Plus, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Logo } from "./logo";
import { ThemeToggle } from "./theme-toggle";

const NAV = [
  { href: "/", label: "Workspace", Icon: LayoutDashboard },
  { href: "/new", label: "New analysis", Icon: Plus },
  { href: "/settings", label: "Settings", Icon: Settings },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [backend, setBackend] = useState<"unknown" | "up" | "down">("unknown");
  const [version, setVersion] = useState<string | null>(null);
  useEffect(() => {
    api
      .health()
      .then((h) => {
        setBackend("up");
        setVersion(h.version);
      })
      .catch(() => setBackend("down"));
  }, []);
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[232px_1fr]">
      <aside className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-background/90 px-4 backdrop-blur lg:h-screen lg:flex-col lg:items-stretch lg:border-r lg:border-b-0 lg:px-3 lg:py-4">
        <Link href="/" className="flex items-center gap-2.5 px-1 lg:mb-6">
          <Logo />
          <div className="leading-tight">
            <div className="text-[15px] font-semibold tracking-tight">ContextForge</div>
            <div className="hidden text-[11px] text-subtle lg:block">Codebase intelligence</div>
          </div>
        </Link>
        <nav className="ml-auto flex gap-1 lg:ml-0 lg:flex-col" aria-label="Main">
          {NAV.map(({ href, label, Icon }) => {
            const active = href === "/" ? pathname === "/" || pathname.startsWith("/projects") : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm font-medium transition-colors",
                  active ? "bg-surface-2 text-foreground" : "text-muted hover:bg-surface-2/70 hover:text-foreground",
                )}
              >
                <Icon className="size-4" />
                <span className="hidden sm:inline">{label}</span>
              </Link>
            );
          })}
        </nav>
        <div className="hidden lg:mt-auto lg:block">
          <div className="rounded-lg border border-border bg-surface px-3 py-2.5 text-[11px] text-muted">
            <div className="flex items-center gap-2">
              <span className={cn("size-1.5 rounded-full", backend === "up" ? "bg-good" : backend === "down" ? "bg-critical" : "bg-subtle")} />
              {backend === "up" ? `API connected · v${version}` : backend === "down" ? "API unreachable" : "Checking API…"}
            </div>
            <div className="mt-1.5 flex items-center gap-2 text-subtle">
              <FolderGit2 className="size-3" /> Uploaded code is never executed
            </div>
          </div>
          <div className="mt-2 flex items-center justify-between px-1">
            <span className="flex items-center gap-1.5 text-[11px] text-subtle">
              <Boxes className="size-3" /> Local-first
            </span>
            <ThemeToggle />
          </div>
        </div>
        <div className="lg:hidden">
          <ThemeToggle />
        </div>
      </aside>
      <main className="min-w-0">{children}</main>
    </div>
  );
}

export function PageHeader({ title, description, actions, eyebrow }: { title: React.ReactNode; description?: React.ReactNode; actions?: React.ReactNode; eyebrow?: React.ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 px-4 pt-6 pb-5 sm:px-8 sm:pt-8">
      <div className="min-w-0">
        {eyebrow ? <div className="mb-1.5 text-xs font-medium text-subtle">{eyebrow}</div> : null}
        <h1 className="truncate text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
        {description ? <p className="mt-1 max-w-2xl text-sm text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
