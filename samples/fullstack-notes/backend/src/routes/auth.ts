import { Router } from "express";
import { login, register } from "../services/authService";

const router = Router();

router.post("/register", async (req, res) => {
  const user = await register(req.body.email, req.body.password);
  res.status(201).json({ id: user.id });
});

router.post("/login", async (req, res) => {
  const token = await login(req.body.email, req.body.password);
  if (!token) return res.status(401).json({ error: "bad credentials" });
  res.json({ token });
});

export default router;
