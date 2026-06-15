"use client";

import type { FunnelStage } from "@/lib/api/types";

/** Entry-filter funnel: how the candidate universe collapses stage by stage.
 * Makes a zero-trade screen explain itself — the stage that drops to a thin /
 * empty bar is the binding filter. */
export function EntryFunnel({ stages }: { stages: FunnelStage[] }) {
  if (!stages.length) return null;
  const max = Math.max(...stages.map((s) => s.days), 1);
  return (
    <div className="space-y-2">
      {stages.map((s, i) => {
        const prev = i === 0 ? null : stages[i - 1].days;
        const drop = prev === null ? null : prev - s.days;
        const pct = (s.days / max) * 100;
        const dead = s.days === 0;
        return (
          <div key={s.label} className="flex items-center gap-3">
            <div className="w-40 shrink-0 truncate text-right text-xs text-muted-foreground sm:w-48">
              {s.label}
            </div>
            <div className="relative h-7 flex-1 overflow-hidden rounded-md bg-muted">
              <div
                className={`h-full rounded-md transition-all ${dead ? "bg-red-500/25" : "bg-primary/70"}`}
                style={{ width: `${dead ? 100 : Math.max(pct, 3)}%` }}
              />
              <span className="absolute inset-y-0 left-2.5 flex items-center text-xs font-semibold tabular-nums">
                {s.days}
                {dead ? <span className="ml-2 font-normal text-red-500">no entries</span> : null}
              </span>
            </div>
            <div className="w-14 shrink-0 text-right text-xs tabular-nums">
              {drop !== null && drop > 0 ? (
                <span className="text-red-500">−{drop}</span>
              ) : (
                <span className="text-muted-foreground">—</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
