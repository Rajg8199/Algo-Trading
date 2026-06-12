"use client";

import Link from "next/link";

import { PageHeader } from "@/components/layout/page-header";
import { LoadingCards } from "@/components/feedback/states";
import { MockBadge, StatusPill } from "@/components/status/status-pill";
import { StatCard } from "@/components/status/stat-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useExperiments, useOpsSummary } from "@/lib/api/queries";
import { fmtInt, fmtIst } from "@/lib/format";

export default function DashboardPage() {
  const ops = useOpsSummary();
  const experiments = useExperiments();

  return (
    <div className="space-y-6">
      <PageHeader title="Overview" description="The console for the research factory" />
      {ops.isLoading || !ops.data ? (
        <LoadingCards count={4} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="Pipeline"
            value={Object.values(ops.data.data.services).every(Boolean) ? "HEALTHY" : "DEGRADED"}
            tone={Object.values(ops.data.data.services).every(Boolean) ? "good" : "bad"}
            hint="all services"
          />
          <StatCard
            label="Ticks today (NIFTY)"
            value={fmtInt(ops.data.data.ticksToday.NIFTY)}
            hint={`SENSEX ${fmtInt(ops.data.data.ticksToday.SENSEX)}`}
          />
          <StatCard
            label="Open data gaps"
            value={fmtInt(ops.data.data.openDataGaps)}
            tone={ops.data.data.openDataGaps === 0 ? "good" : "warn"}
          />
          <StatCard
            label="Experiments recorded"
            value={fmtInt(experiments.data?.data.length ?? 0)}
            hint="see Experiments"
          />
        </div>
      )}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-sm">Latest experiments</CardTitle>
          <MockBadge show={experiments.data?.isMock ?? false} />
        </CardHeader>
        <CardContent className="space-y-2">
          {(experiments.data?.data ?? []).slice(0, 5).map((e) => (
            <Link
              key={e.runId}
              href={`/experiments/${e.runId}`}
              className="flex items-center justify-between rounded-md border p-3 transition-colors hover:bg-muted"
            >
              <div>
                <p className="text-sm font-medium">{e.hypothesis}</p>
                <p className="text-xs text-muted-foreground">
                  trial #{e.trialNumber} · {fmtIst(e.createdAt)} · {e.gitSha}
                </p>
              </div>
              {e.decision ? <StatusPill status={e.decision} /> : <StatusPill status="PENDING" label="recorded" />}
            </Link>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
