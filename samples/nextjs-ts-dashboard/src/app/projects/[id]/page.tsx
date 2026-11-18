import { fetchProject } from "@/lib/api";
import { ProjectCard } from "@/components/ProjectCard";

export default async function ProjectPage({ params }: { params: { id: string } }) {
  const project = await fetchProject(params.id);
  return <ProjectCard project={project} />;
}
