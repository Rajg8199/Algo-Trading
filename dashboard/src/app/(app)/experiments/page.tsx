"use client";

import { useRouter } from "next/navigation";

import { PageHeader } from "@/components/layout/page-header";
import { EmptyState, LoadingBlock } from "@/components/feedback/states";
import { MockBadge, StatusPill } from "@/components/status/status-pill";
import { DataTable, type Column } from "@/components/tables/data-table";
import { useExperiments } from "@/lib/api/queries";
import type { ExperimentSummary } from "@/lib/api/types";
import { fmtIst, fmtNum } from "@/lib/format";

const COLUMNS: Column<ExperimentSummary>[] = [
  { header: "Hypothesis", cell: (r) => <span className="font-medium">{r.hypothesis}</span> },
  { header: "Strategy", cell: (r) => r.strategy ?? "—", className: "hidden sm:table-cell" },
  { header: "Trial", cell: (r) => `#${r.trialNumber}` },
  {
    header: "Decision",
    cell: (r) => (r.decision ? <StatusPill status={r.decision} /> : "—"),
  },
  { header: "DSR", cell: (r) => fmtNum(r.dsr, 3), className: "hidden md:table-cell" },
  { header: "When", cell: (r) => fmtIst(r.createdAt), className: "hidden lg:table-cell" },
  { header: "Git", cell: (r) => <span className="font-mono text-xs">{r.gitSha}</span>, className: "hidden lg:table-cell" },
];

export default function ExperimentsPage() {
  const router = useRouter();
  const { data, isLoading } = useExperiments();
  return (
    <div className="space-y-4">
      <PageHeader
        title="Experiments"
        description="Every registered trial — the deflated-Sharpe denominator lives here"
        actions={<MockBadge show={data?.isMock ?? false} />}
      />
      {isLoading || !data ? (
        <LoadingBlock rows={6} />
      ) : data.data.length === 0 ? (
        <EmptyState
          title="No experiments yet"
          hint="The first row appears when scripts/run_vrp_experiment.py completes its preflight and runs."
        />
      ) : (
        <DataTable
          columns={COLUMNS}
          rows={data.data}
          rowKey={(r) => r.runId}
          onRowClick={(r) => router.push(`/experiments/${r.runId}`)}
        />
      )}
    </div>
  );
}
