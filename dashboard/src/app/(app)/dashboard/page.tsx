"use client";

import { Activity, AlertTriangle, BarChart3, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useMemo } from "react";

import { LoadingCards } from "@/components/feedback/states";
import { PageHeader } from "@/components/layout/page-header";
import { TickerTape } from "@/components/market/ticker-tape";
import { MockBadge, StatusPill } from "@/components/status/status-pill";
import { StatCard } from "@/components/status/stat-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useDqChecks, useExperiments, useOpsSummary } from "@/lib/api/queries";
import { fmtInt, fmtIst, fmtNum } from "@/lib/format";

/** Daily DQ pass-rate (%) as a real series for the sparkline — grouped from
 * the raw per-check rows, ascending by date. */
function useDqPassSeries() {
  const dq = useDqChecks(14);
  return useMemo(() => {
    const byDate = new Map<string, { pass: number; total: number }>();
    for (const c of dq.data?.data ?? []) {
      const slot = byDate.get(c.checkDate) ?? { pass: 0, total: 0 };
      slot.total += 1;
      if (c.passed) slot.pass += 1;
      byDate.set(c.checkDate, slot);
    }
    const dates = [...byDate.keys()].sort();
    const series = dates.map((d) => {
      const s = byDate.get(d)!;
      return (s.pass / s.total) * 100;
    });
    const latest = series.at(-1) ?? null;
    return { series, latest, isMock: dq.data?.isMock ?? false };
  }, [dq.data]);
}

export default function DashboardPage() {
  const ops = useOpsSummary();
  const experiments = useExperiments();
  const dq = useDqPassSeries();

  const allHealthy = ops.data ? Object.values(ops.data.data.services).every(Boolean) : false;

  return (
    <div className="space-y-6">
      <PageHeader title="Overview" description="The console for the research factory" />

      <TickerTape />

      {ops.isLoading || !ops.data ? (
        <LoadingCards count={4} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="Pipeline"
            value={allHealthy ? "HEALTHY" : "DEGRADED"}
            tone={allHealthy ? "good" : "bad"}
            icon={Activity}
            hint={`${Object.values(ops.data.data.services).filter(Boolean).length}/${
              Object.keys(ops.data.data.services).length
            } services up`}
          />
          <StatCard
            label="Ticks today (NIFTY)"
            value={fmtInt(ops.data.data.ticksToday.NIFTY)}
            hint={`SENSEX ${fmtInt(ops.data.data.ticksToday.SENSEX)}`}
            icon={BarChart3}
          />
          <StatCard
            label="Open data gaps"
            value={fmtInt(ops.data.data.openDataGaps)}
            tone={ops.data.data.openDataGaps === 0 ? "good" : "warn"}
            icon={AlertTriangle}
          />
          <StatCard
            label="Data quality (14d)"
            value={dq.latest === null ? "—" : `${fmtNum(dq.latest, 0)}%`}
            tone={dq.latest === null ? "default" : dq.latest >= 95 ? "good" : dq.latest >= 80 ? "warn" : "bad"}
            icon={ShieldCheck}
            spark={dq.series}
            hint="daily checks passing"
          />
        </div>
      )}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <div className="flex items-center gap-2">
            <CardTitle className="text-sm">Latest experiments</CardTitle>
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs tabular-nums text-muted-foreground">
              {experiments.data?.data.length ?? 0}
            </span>
          </div>
          <MockBadge show={experiments.data?.isMock ?? false} />
        </CardHeader>
        <CardContent className="space-y-2">
          {(experiments.data?.data ?? []).slice(0, 6).map((e) => (
            <Link
              key={e.runId}
              href={`/experiments/${e.runId}`}
              className="flex items-center justify-between gap-3 rounded-md border p-3 transition-colors hover:bg-muted"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">{e.hypothesis}</p>
                <p className="truncate text-xs text-muted-foreground">
                  trial #{e.trialNumber} · {fmtIst(e.createdAt)}
                  {e.dsr !== null ? ` · DSR ${fmtNum(e.dsr, 2)}` : ""} · {e.gitSha}
                </p>
              </div>
              {e.decision ? <StatusPill status={e.decision} /> : <StatusPill status="PENDING" label="recorded" />}
            </Link>
          ))}
          {(experiments.data?.data ?? []).length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">No experiments recorded yet.</p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
