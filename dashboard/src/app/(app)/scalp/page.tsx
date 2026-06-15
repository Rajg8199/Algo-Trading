"use client";

import { PageHeader } from "@/components/layout/page-header";
import { LoadingCards } from "@/components/feedback/states";
import { MockBadge, StatusPill } from "@/components/status/status-pill";
import { StatCard } from "@/components/status/stat-card";
import { DataTable, type Column } from "@/components/tables/data-table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useScalpReview } from "@/lib/api/queries";
import type { ScalpReviewRow } from "@/lib/api/types";
import { fmtIst, fmtNum, fmtPct } from "@/lib/format";

const COLUMNS: Column<ScalpReviewRow>[] = [
  { header: "Time", cell: (r) => fmtIst(r.ts) },
  { header: "Symbol", cell: (r) => r.underlying },
  { header: "TF", cell: (r) => r.timeframe },
  { header: "Side", cell: (r) => <StatusPill status={r.side === "LONG" ? "up" : "down"} label={r.side} /> },
  { header: "Entry", cell: (r) => <span className="tabular-nums">{fmtNum(r.entry, 1)}</span>, className: "text-right" },
  {
    header: "Outcome",
    cell: (r) =>
      r.outcome === null ? (
        "—"
      ) : (
        <StatusPill
          status={r.outcome === "WIN" ? "GREEN" : r.outcome === "LOSS" ? "RED" : "PENDING"}
          label={r.outcome}
        />
      ),
  },
  {
    header: "R",
    cell: (r) =>
      r.rMultiple === null ? (
        "—"
      ) : (
        <span className={`tabular-nums ${r.rMultiple >= 0 ? "text-gain" : "text-loss"}`}>
          {r.rMultiple >= 0 ? "+" : ""}
          {fmtNum(r.rMultiple, 2)}
        </span>
      ),
    className: "text-right",
  },
];

export default function ScalpPage() {
  const q = useScalpReview();
  const data = q.data?.data;
  const o = data?.overall;
  const negative = o?.expectancyR != null && o.expectancyR <= 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Scalp forward-test"
        description="Live grading of the (UNVALIDATED) intraday scalp cues against actual price. Evidence before you trade."
        actions={<MockBadge show={q.data?.isMock ?? false} />}
      />

      {/* Verdict banner — the whole point of the scorecard. */}
      {o ? (
        <div
          className={`rounded-lg border p-4 text-sm ${
            negative
              ? "border-amber-500/30 bg-amber-500/10"
              : "border-emerald-500/30 bg-emerald-500/10"
          }`}
        >
          {o.n === 0 ? (
            <span className="text-muted-foreground">
              No graded signals yet — the scanner logs cues during market hours; outcomes are graded
              at 15:45 IST. Come back after a session or two.
            </span>
          ) : negative ? (
            <span>
              <span className="font-medium text-amber-500">Negative expectancy so far</span> — these
              cues are not profitable on the evidence. Do <span className="font-medium">not</span>{" "}
              trade them live.
            </span>
          ) : (
            <span>
              <span className="font-medium text-emerald-500">Positive so far</span> — promising, but
              this is a small forward-test sample. Backtest with full costs before sizing up.
            </span>
          )}
        </div>
      ) : null}

      {q.isLoading || !o ? (
        <LoadingCards count={4} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="Expectancy"
            value={o.expectancyR === null ? "—" : `${o.expectancyR >= 0 ? "+" : ""}${fmtNum(o.expectancyR, 2)} R`}
            tone={o.expectancyR === null ? "default" : o.expectancyR > 0 ? "good" : "bad"}
            hint={`${o.n} signals (${data?.days}d)`}
          />
          <StatCard
            label="Hit rate"
            value={o.hitRate === null ? "—" : fmtPct(o.hitRate * 100, 0)}
            hint={`${o.wins}W / ${o.losses}L`}
          />
          <StatCard label="Open" value={o.open} hint="not yet resolved" />
          <StatCard label="Graded" value={o.wins + o.losses} hint="win+loss" />
        </div>
      )}

      {data?.byTimeframe.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">By timeframe</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {data.byTimeframe.map((tf) => (
              <div key={tf.timeframe} className="flex items-center justify-between rounded-md border p-3 text-sm">
                <span className="font-medium">{tf.timeframe}</span>
                <div className="flex items-center gap-4 tabular-nums">
                  <span className="text-muted-foreground">{tf.n} signals</span>
                  <span>hit {tf.hitRate === null ? "—" : fmtPct(tf.hitRate * 100, 0)}</span>
                  <span className={(tf.expectancyR ?? 0) >= 0 ? "text-gain" : "text-loss"}>
                    exp {tf.expectancyR === null ? "—" : `${fmtNum(tf.expectancyR, 2)}R`}
                  </span>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Recent signals</CardTitle>
        </CardHeader>
        <CardContent>
          {q.isLoading || !data ? null : data.recent.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">No scalp signals logged yet.</p>
          ) : (
            <DataTable columns={COLUMNS} rows={data.recent} rowKey={(r) => `${r.ts}-${r.underlying}-${r.timeframe}`} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
