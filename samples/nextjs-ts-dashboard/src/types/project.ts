export type ProjectStatus = "active" | "paused" | "done";

export interface Project {
  id: string;
  name: string;
  owner: string;
  status: ProjectStatus;
  progress: number;
}

export interface Stats {
  total: number;
  active: number;
  averageProgress: number;
}
