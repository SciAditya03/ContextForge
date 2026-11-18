"use client";
import { createContext, useContext, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Intelligence, Project, Stage } from "@/types/api";

interface Ctx {
  id: string;
  project: Project | null;
  stages: Stage[];
  intel: Intelligence | null;
  intelError: string | null;
  connected: boolean;
}

const ProjectCtx = createContext<Ctx | null>(null);

export function ProjectProvider({ value, children }: { value: Omit<Ctx, "intel" | "intelError">; children: React.ReactNode }) {
  const [intel, setIntel] = useState<Intelligence | null>(null);
  const [intelError, setIntelError] = useState<string | null>(null);
  const completed = value.project?.status === "completed";
  useEffect(() => {
    if (!completed) return;
    api.intelligence(value.id).then(setIntel).catch((e) => setIntelError(e instanceof Error ? e.message : String(e)));
  }, [completed, value.id]);
  return <ProjectCtx.Provider value={{ ...value, intel, intelError }}>{children}</ProjectCtx.Provider>;
}

export function useProject() {
  const v = useContext(ProjectCtx);
  if (!v) throw new Error("useProject must be used inside ProjectProvider");
  return v;
}
