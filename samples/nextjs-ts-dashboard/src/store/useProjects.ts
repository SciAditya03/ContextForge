import { create } from "zustand";
import type { Project } from "@/types/project";
import { fetchProjects } from "@/lib/api";

interface ProjectState {
  projects: Project[];
  loading: boolean;
  load: () => Promise<void>;
}

export const useProjects = create<ProjectState>((set) => ({
  projects: [],
  loading: false,
  load: async () => {
    set({ loading: true });
    try {
      const projects = await fetchProjects();
      set({ projects, loading: false });
    } catch (e) {}
  },
}));
