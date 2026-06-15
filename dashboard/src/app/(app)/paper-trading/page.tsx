"use client";

import { FlaskConical } from "lucide-react";
import { useMemo } from "react";

import { Sparkline } from "@/components/charts/sparkline";
import { TimeSeriesChart } from "@/components/charts/time-series-chart";
import { PageHeader } from "@/components/layout/page-header";
import { EmptyState, LoadingBlock } from "@/components/feedback/states";
import { MockBadge, StatusPill } from "@/components/status/status-pill";
import { StatCard } from "@/components/status/stat-card";
import { DataTable, type Column } from "@/components/tables/data-table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  usePaperLeaderboard,
  usePaperPnl,
  usePaperPositions,
  usePaperSignals,
} from "@/lib/api/queries";
import type { PaperPnlRow, PaperPositionRow, PaperSignalRow } from "@/lib/api/types";
import { fmtIst, fmtNum, fmtRupees } from "@/lib/format";

const POSITION_COLUMNS: Column<PaperPositionRow>[] = [
  { header: "Strategy", cell: (r) => r.strategy },
  { header: "Instrument", cell: (r) => <span className="font-mono text-xs">#{r.instrument_id}</span> },
  {
    header: "Qty",
    cell: (r) => <span className={r.qty < 0 ? "text-loss" : "text-gain"}>{r.qty}</span>,
    className: "text-right",
  },
  { header: "Avg", cell: (r) => fmtNum(r.avg_price), className: "text-right" },
  { header: "Realized", cell: (r) => fmtRupees(r.realized_pnl), className: "text-right" },
];

const PNL_COLUMNS: Column<PaperPnlRow>[] = [
  { header: "Date", cell: (r) => r.trade_date },
  { header: "Strategy", cell: (r) => r.strategy, className: "hidden sm:table-cell" },
  {
    header: "Net PnL",
    cell: (r) => (
      <span className={(r.net_pnl ?? 0) >= 0 ? "text-gain" : "text-loss"}>{fmtRupees(r.net_pnl)}</span>
    ),
    className: "text-right",
  },
  { header: "Trades", cell: (r) => r.n_trades ?? "—", className: "text-right" },
];

const SIGNAL_COLUMNS: Column<PaperSignalRow>[] = [
  { header: "Time", cell: (r) => fmtIst(r.createdAt) },
  { header: "Side", cell: (r) => <StatusPill status={r.side === "BUY" ? "GREEN" : "RED"} label={r.side} /> },
  { header: "Qty", cell: (r) => r.qty, className: "text-right" },
  { header: "Fill", cell: (r) => fmtNum(r.price), className: "text-right" },
  { header: "Slip", cell: (r) => fmtNum(r.slippage), className: "hidden text-right sm:table-cell" },
  {
    header: "Context",
    cell: (r) => (
      <span className="font-mono text-xs text-muted-foreground">
        {JSON.stringify(r.snapshot).slice(0, 60)}
      </span>
    ),
    className: "hidden lg:table-cell",
  },
];

export default function PaperTradingPage() {
  const leaderboard = usePaperLeaderboard();
  const positions = usePaperPositions();
  const pnl = usePaperPnl();
  const signals = usePaperSignals();
  const anyMock =
    (leaderboard.data?.isMock ?? false) ||
    (positions.data?.isMock ?? false) ||
    (pnl.data?.isMock ?? false);
  const top = leaderboard.data?.data[0];

  /** Real cumulative-PnL series built from the daily PnL rows. Overall curve
   * (all strategies summed per day) + a per-strategy curve for sparklines. */
  const { overall, byStrategy } = useMemo(() => {
    const rows = [...(pnl.data?.data ?? [])].sort((a, b) => a.trade_date.localeCompare(b.trade_date));
    const perDate = new Map<string, number>();
    const perStrat = new Map<string, number[]>();
    for (const r of rows) {
      const v = r.net_pnl ?? 0;
      perDate.set(r.trade_date, (perDate.get(r.trade_date) ?? 0) + v);
      const arr = perStrat.get(r.strategy) ?? [];
      arr.push((arr.at(-1) ?? 0) + v);
      perStrat.set(r.strategy, arr);
    }
    let running = 0;
    const overallSeries = [...perDate.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([ts, v]) => {
        running += v;
        return { ts, value: running };
      });
    return { overall: overallSeries, byStrategy: perStrat };
  }, [pnl.data]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Paper Trading Lab"
        description="Forward-test execution on real recorded quotes — UNVALIDATED strategies, evidence collection only, no real money, no broker connectivity"
        actions={<MockBadge show={anyMock} />}
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <StatCard
          label="Lab total PnL (paper)"
          value={fmtRupees(top?.netPnl ?? 0)}
          tone={(top?.netPnl ?? 0) >= 0 ? "good" : "bad"}
          hint="simulated fills, EXPECTED scenario"
        />
        <StatCard
          label="Day win rate"
          value={top?.dayWinRate != null ? `${Math.round(top.dayWinRate * 100)}%` : "—"}
          hint={`${top?.days ?? 0} trading days`}
        />
        <StatCard label="Total orders" value={top?.trades ?? 0} hint="all strategies" />
      </div>

      {overall.length > 1 ? (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-sm">Cumulative paper PnL</CardTitle>
            <span className={`text-sm font-semibold tabular-nums ${(overall.at(-1)?.value ?? 0) >= 0 ? "text-gain" : "text-loss"}`}>
              {fmtRupees(overall.at(-1)?.value ?? 0)}
            </span>
          </CardHeader>
          <CardContent>
            <TimeSeriesChart
              data={overall}
              height={200}
              color={(overall.at(-1)?.value ?? 0) >= 0 ? "var(--gain)" : "var(--loss)"}
              valueFormatter={(v) => fmtRupees(v)}
            />
          </CardContent>
        </Card>
      ) : null}

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-center gap-2">
            <FlaskConical className="h-4 w-4 text-muted-foreground" />
            <CardTitle className="text-sm">Open positions</CardTitle>
          </CardHeader>
          <CardContent>
            {positions.isLoading || !positions.data ? (
              <LoadingBlock rows={3} />
            ) : positions.data.data.length === 0 ? (
              <EmptyState title="Flat" hint="No open paper positions." />
            ) : (
              <DataTable
                columns={POSITION_COLUMNS}
                rows={positions.data.data}
                rowKey={(r) => `${r.strategy}-${r.instrument_id}`}
              />
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-sm">Daily PnL</CardTitle>
          </CardHeader>
          <CardContent>
            {pnl.isLoading || !pnl.data ? (
              <LoadingBlock rows={3} />
            ) : pnl.data.data.length === 0 ? (
              <EmptyState title="No closed days yet" />
            ) : (
              <DataTable
                columns={PNL_COLUMNS}
                rows={pnl.data.data}
                rowKey={(r) => `${r.trade_date}-${r.strategy}`}
              />
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Strategy leaderboard</CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {(leaderboard.data?.data ?? []).map((row, i) => {
            const curve = byStrategy.get(row.strategy) ?? [];
            return (
              <div key={row.strategy} className="flex items-center justify-between gap-3 rounded-md border p-3">
                <span className="min-w-0 truncate text-sm font-medium">
                  #{i + 1} {row.strategy}
                </span>
                <div className="flex items-center gap-4 text-sm tabular-nums">
                  {curve.length > 1 ? <Sparkline data={curve} /> : null}
                  <span className={row.netPnl >= 0 ? "text-gain" : "text-loss"}>{fmtRupees(row.netPnl)}</span>
                  <span className="hidden text-xs text-muted-foreground sm:inline">
                    {row.days}d · {row.trades} orders
                  </span>
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Signal / fill history (mirrors Telegram)</CardTitle>
        </CardHeader>
        <CardContent>
          {signals.isLoading || !signals.data ? (
            <LoadingBlock rows={4} />
          ) : signals.data.data.length === 0 ? (
            <EmptyState title="No signals yet" hint="Signals appear when entry filters fire during market hours." />
          ) : (
            <DataTable columns={SIGNAL_COLUMNS} rows={signals.data.data} rowKey={(r) => r.orderId} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
