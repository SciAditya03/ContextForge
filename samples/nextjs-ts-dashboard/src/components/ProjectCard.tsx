import type { Project } from "@/types/project";

export function ProjectCard({ project }: { project: Project }) {
  return (
    <div className="rounded border p-4">
      <h3>{project.name}</h3>
      <p>{project.owner}</p>
      <progress value={project.progress} max={100} />
    </div>
  );
}
