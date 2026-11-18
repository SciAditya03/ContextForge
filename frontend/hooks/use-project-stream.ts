"use client";
import { useEffect, useRef, useState } from "react";
import { api, apiUrl } from "@/lib/api";
import type { Project, Stage, StreamEvent } from "@/types/api";

const TERMINAL = new Set(["completed", "failed", "cancelled"]);

/**
 * Loads a project and, while it is running, subscribes to its Server-Sent Events stream.
 * Stage state comes only from backend events (no simulated progress).
 */
export function useProjectStream(id: string) {
  const [project, setProject] = useState<Project | null>(null);
  const [stages, setStages] = useState<Stage[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const p = await api.project(id);
        if (cancelled) return;
        setProject(p);
        setStages(p.stages ?? []);
        if (!TERMINAL.has(p.status)) subscribe();
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    }
    function subscribe() {
      esRef.current?.close();
      const es = new EventSource(apiUrl(`/api/projects/${id}/events`));
      esRef.current = es;
      es.onopen = () => setConnected(true);
      const onEvent = (msg: MessageEvent) => {
        const e: StreamEvent = JSON.parse(msg.data);
        if (e.type === "stage" && e.stage) {
          setStages((prev) => prev.map((s) => (s.key === e.stage ? { ...s, status: e.status as Stage["status"], done: e.done ?? null, total: e.total ?? null, detail: e.detail ?? "", elapsed_s: e.elapsed_s ?? null } : s)));
        } else if (e.type === "status") {
          setProject((p) => (p ? { ...p, status: e.status as Project["status"], error: e.error ?? p.error } : p));
          if (TERMINAL.has(e.status)) {
            es.close();
            setConnected(false);
            api.project(id).then((p) => !cancelled && (setProject(p), setStages(p.stages ?? []))).catch(() => undefined);
          }
        }
      };
      es.addEventListener("stage", onEvent);
      es.addEventListener("status", onEvent);
      es.onerror = () => setConnected(false); // EventSource reconnects automatically with Last-Event-ID
    }
    void load();
    return () => {
      cancelled = true;
      esRef.current?.close();
    };
  }, [id]);

  return { project, stages, error, connected, setProject };
}
