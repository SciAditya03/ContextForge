import type { Project, Stats } from "@/types/project";

const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

export async function fetchProjects(): Promise<Project[]> {
  const res = await fetch(`${BASE}/api/projects`);
  if (!res.ok) throw new Error("Failed to load projects");
  return res.json();
}

export async function fetchProject(id: string): Promise<Project> {
  const res = await fetch(`${BASE}/api/projects/${id}`);
  return res.json();
}

export async function saveProject(p: Project): Promise<Project> {
  const res = await fetch(`${BASE}/api/projects/${p.id}`, { method: "PUT", body: JSON.stringify(p) });
  return res.json();
}

export async function fetchStats(): Promise<Stats> {
  const res = await fetch(`${BASE}/api/stats`);
  return res.json();
}

export async function archiveProject(id: string): Promise<void> {
  await fetch(`${BASE}/api/projects/${id}/archive`, { method: "POST" });
}
