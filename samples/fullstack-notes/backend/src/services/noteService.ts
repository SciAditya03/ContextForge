import { prisma } from "../lib/prisma";
import { cached } from "../lib/cache";

export async function listNotes(userId: number) {
  return cached(`notes:${userId}`, 30, () => prisma.note.findMany({ where: { authorId: userId } }));
}

export async function createNote(userId: number, notebookId: number, body: string) {
  const notebook = await prisma.notebook.findUnique({ where: { id: notebookId } });
  if (notebook.ownerId !== userId) throw new Error("forbidden");
  return prisma.note.create({ data: { body, notebookId, authorId: userId } });
}

export async function shareNote(noteId: number) {
  return prisma.note.update({ where: { id: noteId }, data: { shared: true } });
}

export async function purgeNotes() {
  return prisma.note.deleteMany();
}
