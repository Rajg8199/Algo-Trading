"use client";

import { CheckCircle2, XCircle } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { ErrorState, LoadingCards } from "@/components/feedback/states";
import { MockBadge, StatusPill } from "@/components/status/status-pill";
import { StatCard } from "@/components/status/stat-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useExperiment } from "@/lib/api/queries";
import type { ScenarioMetrics } from "@/lib/api/types";
import { fmtNum, fmtPct, fmtRupees } from "@/lib/format";

function ScenarioPanel({ metrics }: { metrics: ScenarioMetrics | null }) {
  if (!metrics) return <p className="text-sm text-muted-foreground">No metrics recorded.</p>;
  return (
    <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">
      <StatCard label="Net PnL" value={fmtRupees(metrics.netPnl)} tone={metrics.netPnl > 0 ? "good" : "bad"} />
      <StatCard label="Sharpe" value={fmtNum(metrics.sharpe)} />
      <StatCard label="Profit factor" value={fmtNum(metrics.profitFactor)} />
      <StatCard label="Expectancy" value={fmtRupees(metrics.expectancy)} />
      <StatCard label="Max DD" value={fmtPct(metrics.maxDrawdownPct)} />
      <StatCard label="Win rate" value={metrics.winRate === null ? "—" : fmtPct(metrics.winRate * 100, 0)} />
      <StatCard label="Trades" value={metrics.nTrades} />
      <StatCard label="Costs" value={fmtRupees(metrics.totalCosts)} />
    </div>
  );
}

export function ExperimentDetailView({ runId }: { runId: string }) {
  const { data, isLoading, isError, refetch } = useExperiment(runId);

  if (isLoading) return <LoadingCards count={8} />;
  if (isError || !data) return <ErrorState message="Could not load experiment" onRetry={() => refetch()} />;
  const e = data.data;

  return (
    <div className="space-y-6">
      <PageHeader
        title={e.hypothesis}
        description={`run ${runId.slice(0, 8)} · trial #${e.trialNumber} · ${e.gitSha}`}
        actions={
          <div className="flex items-center gap-2">
            <MockBadge show={data.isMock} />
            {e.decision ? <StatusPill status={e.decision} /> : null}
          </div>
        }
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard
          label="Deflated Sharpe"
          value={fmtNum(e.dsr, 3)}
          hint="gate: ≥ 0.90"
          tone={e.dsr === null ? "default" : e.dsr >= 0.9 ? "good" : "warn"}
        />
        <StatCard
          label="Risk of ruin"
          value={e.monteCarlo ? fmtPct(e.monteCarlo.riskOfRuin * 100, 2) : "—"}
          hint="gate: ≤ 1%"
        />
        <StatCard
          label="MC drawdown p95"
          value={e.monteCarlo ? fmtRupees(e.monteCarlo.maxDdP95) : "—"}
          hint={e.monteCarlo ? `p99 ${fmtRupees(e.monteCarlo.maxDdP99)} · p99.9 ${fmtRupees(e.monteCarlo.maxDdP999)}` : undefined}
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Acceptance gates</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 sm:grid-cols-2">
          {e.gates.map((g) => (
            <div key={g.name} className="flex items-start gap-2 rounded-md border p-3">
              {g.passed ? (
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-500" />
              ) : (
                <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
              )}
              <div>
                <p className="text-sm font-medium">{g.name}</p>
                <p className="text-xs text-muted-foreground">{g.detail}</p>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Fill-scenario metrics (judged on EXPECTED)</CardTitle>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="expected">
            <TabsList>
              <TabsTrigger value="best">Best</TabsTrigger>
              <TabsTrigger value="expected">Expected</TabsTrigger>
              <TabsTrigger value="worst">Worst</TabsTrigger>
            </TabsList>
            <TabsContent value="best" className="pt-4">
              <ScenarioPanel metrics={e.metrics.best} />
            </TabsContent>
            <TabsContent value="expected" className="pt-4">
              <ScenarioPanel metrics={e.metrics.expected} />
            </TabsContent>
            <TabsContent value="worst" className="pt-4">
              <ScenarioPanel metrics={e.metrics.worst} />
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Regime Sharpes (VIX percentile buckets)</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-3">
          {Object.entries(e.regimeSharpes).map(([regime, sharpe]) => (
            <div key={regime} className="rounded-md border px-4 py-2">
              <p className="text-xs uppercase text-muted-foreground">{regime}</p>
              <p className={`text-lg font-semibold tabular-nums ${sharpe < 0 ? "text-red-500" : ""}`}>
                {fmtNum(sharpe)}
              </p>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
