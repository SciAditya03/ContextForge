import { findProject, removeProject, upsertProject } from "@/lib/data";

export async function GET(_req: Request, { params }: { params: { id: string } }) {
  const project = findProject(params.id);
  if (!project) return new Response("Not found", { status: 404 });
  return Response.json(project);
}

export async function PUT(req: Request, { params }: { params: { id: string } }) {
  const body = await req.json();
  return Response.json(upsertProject({ ...body, id: params.id }));
}

export async function DELETE(_req: Request, { params }: { params: { id: string } }) {
  return Response.json({ removed: removeProject(params.id) });
}
