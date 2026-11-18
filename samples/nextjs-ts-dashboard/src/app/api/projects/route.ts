import { z } from "zod";
import { listProjects, upsertProject } from "@/lib/data";

const ProjectSchema = z.object({ id: z.string(), name: z.string(), owner: z.string(), status: z.enum(["active", "paused", "done"]), progress: z.number() });

export async function GET() {
  return Response.json(listProjects());
}

export async function POST(req: Request) {
  const body = ProjectSchema.parse(await req.json());
  return Response.json(upsertProject(body), { status: 201 });
}
