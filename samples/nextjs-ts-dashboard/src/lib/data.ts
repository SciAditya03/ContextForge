import type { Project } from "@/types/project";

// In-memory store standing in for a database
const projects: Project[] = [
  { id: "p1", name: "Website redesign", owner: "ana", status: "active", progress: 40 },
  { id: "p2", name: "Mobile app", owner: "li", status: "paused", progress: 10 },
];

export function listProjects(): Project[] {
  return projects;
}

export function findProject(id: string): Project | undefined {
  return projects.find((p) => p.id === id);
}

export function upsertProject(p: Project): Project {
  const idx = projects.findIndex((x) => x.id === p.id);
  if (idx >= 0) projects[idx] = p;
  else projects.push(p);
  return p;
}

export function removeProject(id: string): boolean {
  const idx = projects.findIndex((x) => x.id === id);
  if (idx < 0) return false;
  projects.splice(idx, 1);
  return true;
}
