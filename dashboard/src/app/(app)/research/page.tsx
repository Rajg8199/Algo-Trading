"use client";

import { useState } from "react";

import { PageHeader } from "@/components/layout/page-header";
import { TimeSeriesChart } from "@/components/charts/time-series-chart";
import { LoadingBlock } from "@/components/feedback/states";
import { MockBadge } from "@/components/status/status-pill";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useFeatureSeries } from "@/lib/api/queries";
import { useUiStore } from "@/stores/ui";

const FEATURES = [
  { name: "atm_iv_front", label: "ATM IV (front)" },
  { name: "har_rv_forecast_1d", label: "HAR-RV forecast" },
  { name: "vov_20d", label: "Vol-of-Vol" },
  { name: "iv_percentile_1y", label: "IV percentile" },
  { name: "iv_rank_1y", label: "IV rank" },
  { name: "term_slope", label: "Term slope" },
  { name: "put_skew_25d", label: "Put skew 25Δ" },
  { name: "call_skew_25d", label: "Call skew 25Δ" },
];

function FeaturePanel({ feature, entity }: { feature: string; entity: string }) {
  const { data, isLoading } = useFeatureSeries(feature, entity);
  if (isLoading || !data) return <LoadingBlock rows={5} />;
  return (
    <>
      <div className="mb-2 flex justify-end">
        <MockBadge show={data.isMock} />
      </div>
      <TimeSeriesChart data={data.data.points} />
    </>
  );
}

export default function ResearchPage() {
  const { entity, setEntity } = useUiStore();
  const [feature, setFeature] = useState(FEATURES[0].name);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Research"
        description="Feature store time series — history-dependent features populate as recording accumulates"
        actions={
          <Tabs value={entity} onValueChange={(v) => setEntity(v as "NIFTY" | "SENSEX")}>
            <TabsList>
              <TabsTrigger value="NIFTY">NIFTY</TabsTrigger>
              <TabsTrigger value="SENSEX">SENSEX</TabsTrigger>
            </TabsList>
          </Tabs>
        }
      />
      <div className="flex flex-wrap gap-2">
        {FEATURES.map((f) => (
          <button
            key={f.name}
            onClick={() => setFeature(f.name)}
            className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
              feature === f.name ? "border-primary bg-primary/10 text-primary" : "text-muted-foreground hover:bg-muted"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">
            {FEATURES.find((f) => f.name === feature)?.label} · {entity}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <FeaturePanel feature={feature} entity={entity} />
        </CardContent>
      </Card>
    </div>
  );
}
