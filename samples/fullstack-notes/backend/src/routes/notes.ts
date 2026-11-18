import { Router } from "express";
import { requireAuth, AuthedRequest } from "../middleware/auth";
import { createNote, listNotes, shareNote } from "../services/noteService";

const router = Router();

router.get("/", requireAuth, async (req: AuthedRequest, res) => {
  res.json(await listNotes(req.userId!));
});

router.post("/", requireAuth, async (req: AuthedRequest, res) => {
  const note = await createNote(req.userId!, req.body.notebookId, req.body.body);
  res.status(201).json(note);
});

router.post("/:id/share", async (req, res) => {
  res.json(await shareNote(Number(req.params.id)));
});

export default router;
