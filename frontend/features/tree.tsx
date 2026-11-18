"use client";
import { ChevronRight, Folder, FolderOpen } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import type { DirectoryNode } from "@/types/api";

function count(n: DirectoryNode): number {
  return n.files + n.children.reduce((s, c) => s + count(c), 0);
}

function Node({ node, depth }: { node: DirectoryNode; depth: number }) {
  const [open, setOpen] = useState(depth < 1);
  const has = node.children.length > 0;
  return (
    <li>
      <button
        type="button"
        onClick={() => has && setOpen(!open)}
        className={cn("flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-xs hover:bg-surface-2", has ? "cursor-pointer" : "cursor-default")}
        style={{ paddingLeft: depth * 14 + 6 }}
        aria-expanded={has ? open : undefined}
      >
        <ChevronRight className={cn("size-3 shrink-0 text-subtle transition-transform", open && "rotate-90", !has && "invisible")} />
        {open ? <FolderOpen className="size-3.5 shrink-0 text-primary" /> : <Folder className="size-3.5 shrink-0 text-subtle" />}
        <span className="truncate font-mono">{node.name}</span>
        <span className="ml-auto pl-2 tabular-nums text-subtle">{count(node)}</span>
      </button>
      {open && has ? (
        <ul>
          {[...node.children].sort((a, b) => a.name.localeCompare(b.name)).map((c) => (
            <Node key={c.path} node={c} depth={depth + 1} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function DirectoryTree({ root }: { root: DirectoryNode }) {
  return (
    <ul className="scrollbar-thin max-h-80 overflow-auto">
      <Node node={root} depth={0} />
    </ul>
  );
}
