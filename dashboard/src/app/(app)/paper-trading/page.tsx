"use client";

import { FlaskConical } from "lucide-react";

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
    cell: (r) => (
      <span className={r.qty < 0 ? "text-red-500" : "text-emerald-500"}>{r.qty}</span>
    ),
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
      <span className={(r.net_pnl ?? 0) >= 0 ? "text-emerald-500" : "text-red-500"}>
        {fmtRupees(r.net_pnl)}
      </span>
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
          {(leaderboard.data?.data ?? []).map((row, i) => (
            <div key={row.strategy} className="flex items-center justify-between rounded-md border p-3">
              <span className="text-sm font-medium">
                #{i + 1} {row.strategy}
              </span>
              <div className="flex items-center gap-4 text-sm tabular-nums">
                <span className={row.netPnl >= 0 ? "text-emerald-500" : "text-red-500"}>
                  {fmtRupees(row.netPnl)}
                </span>
                <span className="text-xs text-muted-foreground">
                  {row.days}d · {row.trades} orders
                </span>
              </div>
            </div>
          ))}
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
