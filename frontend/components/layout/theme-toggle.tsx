"use client";
import { Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

function subscribe(cb: () => void) {
  const obs = new MutationObserver(cb);
  obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
  return () => obs.disconnect();
}

export function ThemeToggle() {
  const dark = useSyncExternalStore(subscribe, () => document.documentElement.classList.contains("dark"), () => null);
  function toggle() {
    const next = !document.documentElement.classList.contains("dark");
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem("cf-theme", next ? "dark" : "light");
    } catch {
      /* storage unavailable */
    }
  }
  return (
    <button onClick={toggle} aria-label="Toggle colour theme" className="inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted hover:bg-surface-2 hover:text-foreground cursor-pointer">
      {dark === false ? <Moon className="size-4" /> : <Sun className="size-4" />}
    </button>
  );
}

/** Inline script (runs before paint) so the stored/OS theme applies without a flash. */
export const themeInitScript = `(()=>{try{var t=localStorage.getItem('cf-theme');var d=t?t==='dark':!window.matchMedia('(prefers-color-scheme: light)').matches;document.documentElement.classList.toggle('dark',d)}catch(e){document.documentElement.classList.add('dark')}})()`;
