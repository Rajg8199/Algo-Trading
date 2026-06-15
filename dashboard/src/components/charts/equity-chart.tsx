"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { EquityPoint } from "@/lib/api/types";
import { fmtRupees } from "@/lib/format";

export function EquityChart({ data, height = 320 }: { data: EquityPoint[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--chart-1)" stopOpacity={0.22} />
            <stop offset="100%" stopColor="var(--chart-1)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
        <XAxis dataKey="ts" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={48} />
        <YAxis
          yAxisId="equity"
          tick={{ fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={76}
          tickFormatter={(v) => fmtRupees(Number(v))}
        />
        <YAxis yAxisId="dd" orientation="right" hide />
        <Tooltip
          formatter={(value, name) => [fmtRupees(Number(value)), name === "equity" ? "Equity" : "Drawdown"]}
          contentStyle={{
            background: "var(--card)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            fontSize: 12,
          }}
        />
        <Area
          yAxisId="dd"
          type="monotone"
          dataKey="drawdown"
          stroke="none"
          fill="var(--loss)"
          fillOpacity={0.14}
        />
        <Area
          yAxisId="equity"
          type="monotone"
          dataKey="equity"
          stroke="var(--chart-1)"
          fill="url(#equityFill)"
          strokeWidth={1.8}
          dot={false}
        />
        <Line yAxisId="equity" type="monotone" dataKey="equity" stroke="var(--chart-1)" dot={false} strokeWidth={1.8} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
