"use client";

import { PageHeader } from "@/components/layout/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

const ROWS: { label: string; value: string }[] = [
  { label: "API base URL", value: process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000 (default)" },
  { label: "Mode", value: "read-only console" },
  { label: "Timezone", value: "Asia/Kolkata (all timestamps)" },
  { label: "Polling", value: "30s ops · 120s research" },
  { label: "Auth", value: "cookie session (DASHBOARD_PASSWORD) + Caddy basic-auth in production" },
];

export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Settings" description="Console configuration (environment-driven, no runtime mutation)" />
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Configuration</CardTitle>
        </CardHeader>
        <CardContent>
          {ROWS.map((row, i) => (
            <div key={row.label}>
              {i > 0 ? <Separator className="my-3" /> : null}
              <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                <span className="text-sm text-muted-foreground">{row.label}</span>
                <span className="font-mono text-xs">{row.value}</span>
              </div>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
