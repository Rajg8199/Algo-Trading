"use client";

import { CheckCircle2, XCircle } from "lucide-react";

import { EntryFunnel } from "@/components/charts/entry-funnel";
import { EquityChart } from "@/components/charts/equity-chart";
import { PageHeader } from "@/components/layout/page-header";
import { ErrorState, LoadingBlock, LoadingCards } from "@/components/feedback/states";
import { MockBadge, StatusPill } from "@/components/status/status-pill";
import { StatCard } from "@/components/status/stat-card";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useBacktestEquity, useExperiment } from "@/lib/api/queries";
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

/** Equity curve preview — only meaningful for real backtests. EOD SCREEN runs
 * have no equity artifact, so the caller renders this only when !e.screen. */
function EquityPreview({ runId }: { runId: string }) {
  const { data, isLoading } = useBacktestEquity(runId);
  if (isLoading) return <LoadingBlock rows={3} />;
  if (!data || data.data.length < 2) {
    return <p className="text-sm text-muted-foreground">No equity curve recorded for this run.</p>;
  }
  const last = data.data.at(-1)?.equity ?? 0;
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <MockBadge show={data.isMock} />
        <span className={`text-sm font-semibold tabular-nums ${last >= 0 ? "text-gain" : "text-loss"}`}>
          {fmtRupees(last)}
        </span>
      </div>
      <EquityChart data={data.data} height={240} />
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
            {e.screen ? <Badge variant="outline">SCREEN</Badge> : null}
            {e.decision ? <StatusPill status={e.decision} /> : null}
          </div>
        }
      />

      {(e.reasons?.length ?? 0) > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Verdict — {e.decision ?? "—"}</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1.5">
              {e.reasons.map((r) => (
                <li key={r} className="flex gap-2 text-sm text-muted-foreground">
                  <span className="text-muted-foreground/50">•</span>
                  {r}
                </li>
              ))}
            </ul>
            {e.screen ? (
              <p className="mt-3 text-xs text-muted-foreground">
                This is a coarse free-data SCREEN — a pass only justifies acquiring intraday data;
                it never advances a strategy toward paper or live.
              </p>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {e.entryFunnel?.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Entry-filter funnel</CardTitle>
            <p className="text-xs text-muted-foreground">
              Candidate days surviving each registered filter (least-restrictive thresholds). The
              stage that collapses is the binding constraint.
            </p>
          </CardHeader>
          <CardContent>
            <EntryFunnel stages={e.entryFunnel} />
          </CardContent>
        </Card>
      ) : null}

      {!e.screen ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Equity curve (EXPECTED scenario)</CardTitle>
          </CardHeader>
          <CardContent>
            <EquityPreview runId={runId} />
          </CardContent>
        </Card>
      ) : null}

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

      {e.gates.length ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Acceptance gates</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-2 sm:grid-cols-2">
            {e.gates.map((g) => (
              <div key={g.name} className="flex items-start gap-2 rounded-md border p-3">
                {g.passed ? (
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-gain" />
                ) : (
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-loss" />
                )}
                <div>
                  <p className="text-sm font-medium">{g.name}</p>
                  <p className="text-xs text-muted-foreground">{g.detail}</p>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}

      {e.metrics.expected || e.metrics.best || e.metrics.worst ? (
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
      ) : null}

      {Object.keys(e.regimeSharpes).length ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Regime Sharpes (IV-percentile buckets)</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-3">
            {Object.entries(e.regimeSharpes).map(([regime, sharpe]) => (
              <div key={regime} className="rounded-md border px-4 py-2">
                <p className="text-xs uppercase text-muted-foreground">{regime}</p>
                <p className={`text-lg font-semibold tabular-nums ${sharpe < 0 ? "text-loss" : "text-gain"}`}>
                  {fmtNum(sharpe)}
                </p>
              </div>
            ))}
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
