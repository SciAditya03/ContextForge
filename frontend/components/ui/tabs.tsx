"use client";
import { cn } from "@/lib/utils";

export function SegmentedControl<T extends string>({ value, onChange, options, className, ariaLabel }: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: React.ReactNode; count?: number }[];
  className?: string;
  ariaLabel?: string;
}) {
  return (
    <div role="tablist" aria-label={ariaLabel} className={cn("inline-flex rounded-lg border border-border bg-surface-2 p-0.5", className)}>
      {options.map((o) => (
        <button
          key={o.value}
          role="tab"
          aria-selected={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "inline-flex h-7 items-center gap-1.5 rounded-md px-3 text-xs font-medium transition-colors cursor-pointer",
            value === o.value ? "bg-surface text-foreground shadow-sm" : "text-muted hover:text-foreground",
          )}
        >
          {o.label}
          {o.count !== undefined ? <span className="tabular-nums text-subtle">{o.count}</span> : null}
        </button>
      ))}
    </div>
  );
}
