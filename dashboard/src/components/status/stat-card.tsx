import type { LucideIcon } from "lucide-react";

import { Sparkline } from "@/components/charts/sparkline";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function StatCard({
  label,
  value,
  hint,
  tone = "default",
  icon: Icon,
  spark,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: "default" | "good" | "warn" | "bad";
  icon?: LucideIcon;
  spark?: number[];
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
          {Icon ? <Icon className="h-4 w-4 text-muted-foreground" /> : null}
        </div>
        <div className="mt-1 flex items-end justify-between gap-3">
          <p
            className={cn(
              "text-2xl font-semibold tabular-nums",
              tone === "good" && "text-emerald-500",
              tone === "warn" && "text-amber-500",
              tone === "bad" && "text-red-500",
            )}
          >
            {value}
          </p>
          {spark && spark.length > 1 ? <Sparkline data={spark} className="shrink-0" /> : null}
        </div>
        {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  );
}
