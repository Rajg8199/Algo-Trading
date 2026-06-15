"use client";

import { AlertTriangle, ShieldCheck } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { EmptyState, LoadingBlock, LoadingCards } from "@/components/feedback/states";
import { MockBadge } from "@/components/status/status-pill";
import { StatCard } from "@/components/status/stat-card";
import { DataTable, type Column } from "@/components/tables/data-table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useBreakoutScan } from "@/lib/api/queries";
import type { BreakoutSignalRow } from "@/lib/api/types";
import { fmtInt, fmtNum, fmtPct } from "@/lib/format";

const SIGNAL_COLUMNS: Column<BreakoutSignalRow>[] = [
  { header: "Symbol", cell: (r) => <span className="font-medium">{r.symbol.replace(/^[A-Z]+:/, "")}</span> },
  { header: "Entry", cell: (r) => <span className="tabular-nums">{fmtNum(r.entry)}</span>, className: "text-right" },
  {
    header: "Stop",
    cell: (r) => <span className="tabular-nums text-loss">{fmtNum(r.stop)}</span>,
    className: "text-right",
  },
  {
    header: "Target",
    cell: (r) =>
      r.target === null ? (
        <span className="text-muted-foreground">trail</span>
      ) : (
        <span className="tabular-nums text-gain">{fmtNum(r.target)}</span>
      ),
    className: "text-right",
  },
  { header: "Risk/sh", cell: (r) => fmtNum(r.riskPerShare), className: "hidden text-right sm:table-cell" },
  {
    header: "Vol×",
    cell: (r) => <span className="tabular-nums">{fmtNum(r.volumeRatio, 1)}×</span>,
    className: "text-right",
  },
  {
    header: "Qty",
    cell: (r) => <span className="tabular-nums">{fmtInt(r.suggestedQty)}</span>,
    className: "hidden text-right md:table-cell",
  },
];

export default function SignalsPage() {
  const scan = useBreakoutScan();
  const data = scan.data?.data;
  const bt = data?.backtest;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Breakout signals"
        description="Objective Donchian/Turtle long breakouts (trend + volume filtered, ATR-stopped). Swing, EOD. A signal is a rule match — not a recommendation, never a guarantee."
        actions={<MockBadge show={scan.data?.isMock ?? false} />}
      />

      {/* Validation banner — the whole point of the validate-first design. */}
      {data ? (
        data.validated ? (
          <div className="flex items-start gap-3 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-4">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-emerald-500" />
            <div className="text-sm">
              <p className="font-medium text-emerald-500">VALIDATED</p>
              <p className="text-muted-foreground">
                The strategy has cleared the acceptance gate on backtest. Signals still require your
                own risk management and position sizing.
              </p>
            </div>
          </div>
        ) : (
          <div className="flex items-start gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 p-4">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-500" />
            <div className="text-sm">
              <p className="font-medium text-amber-500">UNVALIDATED — do not trade blindly</p>
              <p className="text-muted-foreground">
                These are rule matches collected for evidence. The strategy has{" "}
                <span className="font-medium text-foreground">not</span> cleared the acceptance gate
                (≥30 trades, expectancy &gt; 0.1R, profit factor &gt; 1.3, max drawdown &lt; 25%), so
                no edge is proven. There is no &ldquo;sure shot&rdquo; — size for being wrong.
              </p>
            </div>
          </div>
        )
      ) : null}

      {/* Backtest scorecard — what earns (or denies) trust. */}
      {scan.isLoading ? (
        <LoadingCards count={4} />
      ) : bt ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="Expectancy"
            value={bt.expectancyR === null ? "—" : `${fmtNum(bt.expectancyR, 2)} R`}
            tone={bt.expectancyR !== null && bt.expectancyR > 0.1 ? "good" : "warn"}
            hint={`${fmtInt(bt.nTrades)} trades`}
          />
          <StatCard
            label="Profit factor"
            value={fmtNum(bt.profitFactor)}
            tone={bt.profitFactor !== null && bt.profitFactor > 1.3 ? "good" : "warn"}
            hint="gate: > 1.3"
          />
          <StatCard
            label="Win rate"
            value={bt.winRate === null ? "—" : fmtPct(bt.winRate * 100, 0)}
            hint={bt.avgHoldingDays ? `avg hold ${fmtNum(bt.avgHoldingDays, 0)}d` : undefined}
          />
          <StatCard
            label="Max drawdown"
            value={fmtPct(bt.maxDrawdownPct)}
            tone={bt.maxDrawdownPct < 25 ? "good" : "bad"}
            hint={`total ${fmtPct(bt.totalReturnPct)}`}
          />
        </div>
      ) : null}

      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-sm">
            Today&rsquo;s candidates{data?.asOf ? ` · ${data.asOf}` : ""}
          </CardTitle>
          {data ? (
            <span className="text-xs text-muted-foreground">
              sized at {fmtPct(data.riskPct * 100, 0)} risk · ₹{fmtInt(data.capital)} capital
            </span>
          ) : null}
        </CardHeader>
        <CardContent>
          {scan.isLoading || !data ? (
            <LoadingBlock rows={3} />
          ) : data.signals.length === 0 ? (
            <EmptyState
              title="No breakouts today"
              hint="The EOD scan runs after market close. Most days produce nothing — that is the filter working, not a failure."
            />
          ) : (
            <DataTable
              columns={SIGNAL_COLUMNS}
              rows={data.signals}
              rowKey={(r) => r.symbol}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
