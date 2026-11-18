import Redis from "ioredis";

export const redis = new Redis(process.env.REDIS_URL || "redis://localhost:6379");

export async function cached<T>(key: string, ttl: number, fn: () => Promise<T>): Promise<T> {
  const hit = await redis.get(key);
  if (hit) return JSON.parse(hit) as T;
  const value = await fn();
  await redis.set(key, JSON.stringify(value), "EX", ttl);
  return value;
}
