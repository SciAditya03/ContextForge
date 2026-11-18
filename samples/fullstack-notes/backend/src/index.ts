import express from "express";
import cors from "cors";
import authRoutes from "./routes/auth";
import noteRoutes from "./routes/notes";
import { logger } from "./lib/logger";

const app = express();
app.use(cors());
app.use(express.json());
app.use("/api/auth", authRoutes);
app.use("/api/notes", noteRoutes);

app.get("/health", (_req, res) => res.json({ ok: true }));

const port = Number(process.env.PORT || 4000);
app.listen(port, () => logger.info(`notes api on ${port}`));
