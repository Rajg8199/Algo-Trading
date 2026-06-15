"use client";

import { useState } from "react";

import { PageHeader } from "@/components/layout/page-header";
import { LoadingBlock } from "@/components/feedback/states";
import { MockBadge } from "@/components/status/status-pill";
import { Card, CardContent } from "@/components/ui/card";
import { useOptionChain } from "@/lib/api/queries";
import type { OptionLeg } from "@/lib/api/types";
import { fmtInt, fmtIst, fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";

const UNDERLYINGS = ["NIFTY", "SENSEX", "BANKNIFTY"];

function leg(l: OptionLeg | null, key: keyof OptionLeg): string {
  if (!l || l[key] === null) return "—";
  const v = l[key] as number;
  if (key === "oi" || key === "oiChg") return fmtInt(v);
  if (key === "iv") return `${fmtNum(v, 1)}`;
  return fmtNum(v, 1);
}

export default function OptionChainPage() {
  const [underlying, setUnderlying] = useState("NIFTY");
  const q = useOptionChain(underlying);
  const data = q.data?.data;
  const spot = data?.spot ?? null;
  // ATM = strike nearest spot
  const atm =
    spot && data?.rows.length
      ? data.rows.reduce((b, r) => (Math.abs(r.strike - spot) < Math.abs(b - spot) ? r.strike : b), data.rows[0].strike)
      : null;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Option chain"
        description="Latest recorded chain for the nearest expiry — live during market hours, last snapshot otherwise."
        actions={<MockBadge show={q.data?.isMock ?? false} />}
      />

      <div className="flex flex-wrap items-center gap-2">
        {UNDERLYINGS.map((u) => (
          <button
            key={u}
            type="button"
            onClick={() => setUnderlying(u)}
            className={cn(
              "rounded-full border px-3 py-1 text-xs transition-colors",
              underlying === u
                ? "border-transparent bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            {u}
          </button>
        ))}
        <span className="ml-auto text-xs text-muted-foreground">
          {data?.spot != null ? (
            <>
              spot <span className="font-mono text-foreground">{fmtInt(data.spot)}</span> · exp{" "}
              {data.expiry ?? "—"} · {fmtIst(data.ts)}
            </>
          ) : null}
        </span>
      </div>

      <Card>
        <CardContent className="p-0">
          {q.isLoading || !data ? (
            <div className="p-4">
              <LoadingBlock rows={6} />
            </div>
          ) : data.rows.length === 0 ? (
            <p className="p-8 text-center text-sm text-muted-foreground">
              No recorded chain for {underlying} yet (market closed or not subscribed).
            </p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-right text-xs tabular-nums">
                <thead className="border-b text-muted-foreground">
                  <tr>
                    <th className="px-2 py-2 font-medium" colSpan={3}>
                      CALLS
                    </th>
                    <th className="px-2 py-2 text-center font-medium">STRIKE</th>
                    <th className="px-2 py-2 font-medium" colSpan={3}>
                      PUTS
                    </th>
                  </tr>
                  <tr className="text-[10px]">
                    <th className="px-2 pb-1 font-normal">OI</th>
                    <th className="px-2 pb-1 font-normal">IV</th>
                    <th className="px-2 pb-1 font-normal">LTP</th>
                    <th className="px-2 pb-1 text-center font-normal" />
                    <th className="px-2 pb-1 font-normal">LTP</th>
                    <th className="px-2 pb-1 font-normal">IV</th>
                    <th className="px-2 pb-1 font-normal">OI</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map((r) => {
                    const isAtm = r.strike === atm;
                    const callItm = spot != null && r.strike < spot;
                    const putItm = spot != null && r.strike > spot;
                    return (
                      <tr
                        key={r.strike}
                        className={cn("border-b border-border/40", isAtm && "bg-primary/10 font-medium")}
                      >
                        <td className={cn("px-2 py-1", callItm && "bg-gain/5")}>{leg(r.call, "oi")}</td>
                        <td className={cn("px-2 py-1", callItm && "bg-gain/5")}>{leg(r.call, "iv")}</td>
                        <td className={cn("px-2 py-1", callItm && "bg-gain/5")}>{leg(r.call, "ltp")}</td>
                        <td className="px-2 py-1 text-center font-mono">{fmtInt(r.strike)}</td>
                        <td className={cn("px-2 py-1", putItm && "bg-gain/5")}>{leg(r.put, "ltp")}</td>
                        <td className={cn("px-2 py-1", putItm && "bg-gain/5")}>{leg(r.put, "iv")}</td>
                        <td className={cn("px-2 py-1", putItm && "bg-gain/5")}>{leg(r.put, "oi")}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
