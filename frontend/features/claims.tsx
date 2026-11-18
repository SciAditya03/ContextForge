import { AlertTriangle } from "lucide-react";
import { EvidenceBadge, SourceChip } from "@/components/domain/badges";
import type { Claim } from "@/types/api";

export function ClaimList({ claims, empty }: { claims: Claim[]; empty: React.ReactNode }) {
  if (!claims?.length) return <div className="text-sm text-muted">{empty}</div>;
  return (
    <ul className="space-y-3">
      {claims.map((c, i) => (
        <li key={i} className="text-sm leading-relaxed">
          <div className="flex items-start gap-2">
            <EvidenceBadge value={c.classification} className="mt-0.5" />
            <p className="min-w-0 [overflow-wrap:anywhere]">{c.text}</p>
          </div>
          <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5 pl-2 sm:pl-[3.25rem]">
            {c.sources.slice(0, 4).map((s, j) => (
              <SourceChip key={j} file={s.file} start={s.line_start} end={s.line_end} />
            ))}
            <span className="text-[11px] text-subtle">confidence {c.confidence.toFixed(2)}</span>
            {!c.verified ? (
              <span className="inline-flex items-center gap-1 text-[11px] text-warning">
                <AlertTriangle className="size-3" /> unverified
              </span>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  );
}
