"use client";

import { PageHeader } from "@/components/layout/page-header";
import { EquityChart } from "@/components/charts/equity-chart";
import { LoadingBlock } from "@/components/feedback/states";
import { MockBadge, StatusPill } from "@/components/status/status-pill";
import { DataTable, type Column } from "@/components/tables/data-table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useBacktestEquity, useBacktestTrades } from "@/lib/api/queries";
import type { TradeRow } from "@/lib/api/types";
import { fmtIst, fmtNum, fmtRupees } from "@/lib/format";

const TRADE_COLUMNS: Column<TradeRow>[] = [
  { header: "Time", cell: (r) => fmtIst(r.ts) },
  { header: "Instrument", cell: (r) => <span className="font-mono text-xs">#{r.instrumentId}</span> },
  { header: "Side", cell: (r) => <StatusPill status={r.side === "BUY" ? "GREEN" : "RED"} label={r.side} /> },
  { header: "Qty", cell: (r) => r.qty, className: "text-right" },
  { header: "Price", cell: (r) => fmtNum(r.price), className: "text-right" },
  { header: "Costs", cell: (r) => fmtNum(r.costs), className: "hidden text-right sm:table-cell" },
  { header: "Tag", cell: (r) => r.tag, className: "hidden sm:table-cell" },
  {
    header: "Realized",
    cell: (r) => (
      <span className={r.realizedPnl > 0 ? "text-emerald-500" : r.realizedPnl < 0 ? "text-red-500" : ""}>
        {fmtRupees(r.realizedPnl)}
      </span>
    ),
    className: "text-right",
  },
];

export function BacktestDetailView({ runId }: { runId: string }) {
  const equity = useBacktestEquity(runId);
  const trades = useBacktestTrades(runId);

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Backtest ${runId.slice(0, 8)}`}
        description="EXPECTED-scenario equity curve with drawdown shading"
        actions={<MockBadge show={(equity.data?.isMock ?? false) || (trades.data?.isMock ?? false)} />}
      />
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Equity & drawdown</CardTitle>
        </CardHeader>
        <CardContent>
          {equity.isLoading || !equity.data ? <LoadingBlock rows={6} /> : <EquityChart data={equity.data.data} />}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Trades</CardTitle>
        </CardHeader>
        <CardContent>
          {trades.isLoading || !trades.data ? (
            <LoadingBlock rows={5} />
          ) : (
            <DataTable columns={TRADE_COLUMNS} rows={trades.data.data} rowKey={(r) => `${r.ts}-${r.instrumentId}-${r.tag}`} />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
