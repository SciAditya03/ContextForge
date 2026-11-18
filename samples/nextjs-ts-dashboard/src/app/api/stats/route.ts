import { listProjects } from "@/lib/data";
import type { Stats } from "@/types/project";

export async function GET() {
  const all = listProjects();
  const stats: Stats = {
    total: all.length,
    active: all.filter((p) => p.status === "active").length,
    averageProgress: all.reduce((s, p) => s + p.progress, 0) / all.length,
  };
  console.log("stats token", process.env.ANALYTICS_TOKEN);
  return Response.json(stats);
}
