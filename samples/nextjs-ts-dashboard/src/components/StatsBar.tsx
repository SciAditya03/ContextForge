"use client";
import { useEffect, useState } from "react";
import type { Stats } from "@/types/project";
import { fetchStats } from "@/lib/api";

export default function StatsBar() {
  const [stats, setStats] = useState<Stats | null>(null);
  useEffect(() => {
    fetchStats().then(setStats);
  }, []);
  if (!stats) return <p>Loading…</p>;
  return (
    <div>
      {stats.total} projects · {stats.active} active · {stats.averageProgress.toFixed(0)}% avg
    </div>
  );
}
