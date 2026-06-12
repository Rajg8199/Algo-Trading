"use client";

import { PageHeader } from "@/components/layout/page-header";
import { EmptyState, ErrorState, LoadingBlock, LoadingCards } from "@/components/feedback/states";
import { MockBadge, StatusPill } from "@/components/status/status-pill";
import { StatCard } from "@/components/status/stat-card";
import { DataTable, type Column } from "@/components/tables/data-table";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useBurnIn, useDqChecks, useOpsSummary } from "@/lib/api/queries";
import type { BurnInDay, DQCheck, ServiceName } from "@/lib/api/types";
import { agoMinutes, fmtInt, fmtIst } from "@/lib/format";

const SERVICE_LABELS: Record<ServiceName, string> = {
  recorder: "Recorder",
  scheduler: "Scheduler",
  api: "API",
  telegram: "Telegram",
  db: "TimescaleDB",
  redis: "Redis",
};

function ServiceHealth() {
  const { data, isLoading, isError, refetch } = useOpsSummary();
  if (isLoading) return <LoadingCards count={6} />;
  if (isError || !data) return <ErrorState message="Could not load service health" onRetry={() => refetch()} />;
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold">Service health</h2>
        <MockBadge show={data.isMock} />
      </div>
      <div className="grid gap-3 grid-cols-2 sm:grid-cols-3 xl:grid-cols-6">
        {(Object.keys(SERVICE_LABELS) as ServiceName[]).map((name) => {
          const up = data.data.services[name];
          return (
            <Card key={name}>
              <CardContent className="flex items-center justify-between p-4">
                <span className="text-sm font-medium">{SERVICE_LABELS[name]}</span>
                <StatusPill status={up ? "up" : "down"} label={up ? "UP" : "DOWN"} />
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

function RecorderStats() {
  const { data, isLoading } = useOpsSummary();
  if (isLoading || !data) return <LoadingCards count={4} />;
  const s = data.data;
  const snapshotMins = agoMinutes(s.lastChainSnapshot);
  return (
    <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <StatCard
        label="Last chain snapshot"
        value={snapshotMins === null ? "—" : `${snapshotMins}m ago`}
        hint={fmtIst(s.lastChainSnapshot)}
        tone={snapshotMins === null ? "bad" : snapshotMins <= 3 ? "good" : snapshotMins <= 10 ? "warn" : "bad"}
      />
      <StatCard
        label="Upstox token"
        value={s.upstoxToken === "valid" ? "VALID" : "EXPIRED"}
        tone={s.upstoxToken === "valid" ? "good" : "bad"}
        hint="rotates daily ~03:30 IST"
      />
      <StatCard
        label="Ticks (5m)"
        value={fmtInt(s.ticksLast5m)}
        hint={`today: NIFTY ${fmtInt(s.ticksToday.NIFTY)} · SENSEX ${fmtInt(s.ticksToday.SENSEX)}`}
        tone={s.ticksLast5m > 1000 ? "good" : "warn"}
      />
      <StatCard
        label="Chain rows (5m)"
        value={fmtInt(s.chainRowsLast5m)}
        hint={`today: NIFTY ${fmtInt(s.chainRowsToday.NIFTY)} · SENSEX ${fmtInt(s.chainRowsToday.SENSEX)}`}
        tone={s.chainRowsLast5m > 500 ? "good" : "warn"}
      />
    </div>
  );
}

const DQ_COLUMNS: Column<DQCheck>[] = [
  { header: "Check", cell: (r) => <span className="font-mono text-xs">{r.checkName}</span> },
  { header: "Date", cell: (r) => r.checkDate },
  {
    header: "Result",
    cell: (r) => <StatusPill status={r.passed ? "GREEN" : "RED"} label={r.passed ? "PASS" : "FAIL"} />,
  },
  {
    header: "Details",
    cell: (r) => <span className="font-mono text-xs text-muted-foreground">{JSON.stringify(r.details)}</span>,
    className: "hidden md:table-cell",
  },
];

function DqPanel() {
  const { data, isLoading, isError, refetch } = useDqChecks();
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-sm">Data quality checks</CardTitle>
        <MockBadge show={data?.isMock ?? false} />
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <LoadingBlock />
        ) : isError || !data ? (
          <ErrorState message="Could not load DQ checks" onRetry={() => refetch()} />
        ) : data.data.length === 0 ? (
          <EmptyState title="No DQ results yet" hint="The validation job runs at 21:00 IST." />
        ) : (
          <DataTable columns={DQ_COLUMNS} rows={data.data} rowKey={(r) => `${r.checkDate}-${r.checkName}`} />
        )}
      </CardContent>
    </Card>
  );
}

function BurnInBoard() {
  const { data, isLoading } = useBurnIn();
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle className="text-sm">10-day burn-in</CardTitle>
        <MockBadge show={data?.isMock ?? false} />
      </CardHeader>
      <CardContent>
        {isLoading || !data ? (
          <LoadingBlock rows={2} />
        ) : (
          <div className="grid grid-cols-5 gap-2 sm:grid-cols-10">
            {data.data.map((d: BurnInDay) => (
              <div key={d.day} className="flex flex-col items-center gap-1 rounded-md border p-2">
                <span className="text-xs text-muted-foreground">D{d.day}</span>
                <StatusPill status={d.status} label={d.status === "PENDING" ? "—" : d.status[0]} />
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function OperationsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Operations"
        description="Recorder, pipeline health, data quality, and burn-in progress"
      />
      <ServiceHealth />
      <RecorderStats />
      <div className="grid gap-6 xl:grid-cols-2">
        <DqPanel />
        <BurnInBoard />
      </div>
    </div>
  );
}
