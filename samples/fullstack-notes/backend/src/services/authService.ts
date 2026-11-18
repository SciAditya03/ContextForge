import bcrypt from "bcryptjs";
import jwt from "jsonwebtoken";
import { prisma } from "../lib/prisma";

export async function register(email: string, password: string) {
  const hash = await bcrypt.hash(password, 10);
  return prisma.user.create({ data: { email, password: hash } });
}

export async function login(email: string, password: string): Promise<string | null> {
  const user = await prisma.user.findUnique({ where: { email } });
  if (!user) return null;
  const ok = await bcrypt.compare(password, user.password);
  if (!ok) return null;
  return jwt.sign({ sub: user.id }, process.env.JWT_SECRET as string, { expiresIn: "1h" });
}
