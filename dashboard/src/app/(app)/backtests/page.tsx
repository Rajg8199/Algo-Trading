"use client";

import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/layout/page-header";
import { EmptyState, LoadingBlock } from "@/components/feedback/states";
import { MockBadge, StatusPill } from "@/components/status/status-pill";
import { DataTable, type Column } from "@/components/tables/data-table";
import { useExperiments } from "@/lib/api/queries";
import type { ExperimentSummary } from "@/lib/api/types";
import { fmtIst } from "@/lib/format";

const COLUMNS: Column<ExperimentSummary>[] = [
  { header: "Run", cell: (r) => <span className="font-mono text-xs">{r.runId.slice(0, 8)}</span> },
  { header: "Hypothesis", cell: (r) => r.hypothesis },
  { header: "Strategy", cell: (r) => r.strategy ?? "—", className: "hidden sm:table-cell" },
  { header: "Decision", cell: (r) => (r.decision ? <StatusPill status={r.decision} /> : "—") },
  { header: "When", cell: (r) => fmtIst(r.createdAt), className: "hidden lg:table-cell" },
];

export default function BacktestsPage() {
  const router = useRouter();
  const { data, isLoading } = useExperiments();
  const backtests = (data?.data ?? []).filter((e) => e.kind === "BACKTEST");
  return (
    <div className="space-y-4">
      <PageHeader
        title="Backtests"
        description="Equity, drawdown, and trades per registered run"
        actions={<MockBadge show={data?.isMock ?? false} />}
      />
      {isLoading ? (
        <LoadingBlock rows={5} />
      ) : backtests.length === 0 ? (
        <EmptyState title="No backtests yet" hint="Backtest runs appear here once experiments execute." />
      ) : (
        <DataTable
          columns={COLUMNS}
          rows={backtests}
          rowKey={(r) => r.runId}
          onRowClick={(r) => router.push(`/backtests/${r.runId}`)}
        />
      )}
    </div>
  );
}
