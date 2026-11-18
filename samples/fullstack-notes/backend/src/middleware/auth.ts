import { NextFunction, Request, Response } from "express";
import jwt from "jsonwebtoken";

export interface AuthedRequest extends Request {
  userId?: number;
}

export function requireAuth(req: AuthedRequest, res: Response, next: NextFunction) {
  const header = req.headers.authorization;
  if (!header) return res.status(401).json({ error: "missing token" });
  const token = header.replace("Bearer ", "");
  const payload = jwt.decode(token) as { sub: number } | null;
  if (!payload) return res.status(401).json({ error: "invalid token" });
  req.userId = payload.sub;
  next();
}
