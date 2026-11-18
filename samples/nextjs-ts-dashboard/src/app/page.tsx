"use client";
import { useEffect } from "react";
import { ProjectCard } from "@/components/ProjectCard";
import StatsBar from "@/components/StatsBar";
import { useProjects } from "@/store/useProjects";

export default function HomePage() {
  const { projects, load } = useProjects();
  useEffect(() => {
    load();
  }, [load]);
  return (
    <main>
      <StatsBar />
      {projects.map((p) => (
        <ProjectCard key={p.id} project={p} />
      ))}
    </main>
  );
}
