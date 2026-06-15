"use client";

import { Search } from "lucide-react";
import { useState } from "react";

import { PageHeader } from "@/components/layout/page-header";
import { TradingViewWidget } from "@/components/market/tv-widget";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const PRESETS = [
  { label: "NIFTY 50", symbol: "NSE:NIFTY" },
  { label: "BANK NIFTY", symbol: "NSE:BANKNIFTY" },
  { label: "SENSEX", symbol: "BSE:SENSEX" },
  { label: "RELIANCE", symbol: "NSE:RELIANCE" },
  { label: "HDFC BANK", symbol: "NSE:HDFCBANK" },
  { label: "INFY", symbol: "NSE:INFY" },
  { label: "TCS", symbol: "NSE:TCS" },
];

export default function MarketsPage() {
  const [symbol, setSymbol] = useState("NSE:NIFTY");
  const [draft, setDraft] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const v = draft.trim().toUpperCase();
    if (v) setSymbol(v.includes(":") ? v : `NSE:${v}`);
    setDraft("");
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Markets"
        description="External market analysis (TradingView) — charting, technicals, fundamentals, and a stock screener. Separate from the platform's own validated data pipeline."
      />

      <Card>
        <CardContent className="flex flex-col gap-3 p-4">
          <form onSubmit={submit} className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Symbol — e.g. RELIANCE or NSE:TCS"
                aria-label="Symbol"
                className="pl-8"
              />
            </div>
            <Button type="submit" variant="secondary">
              Load
            </Button>
          </form>
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map((p) => (
              <button
                key={p.symbol}
                type="button"
                onClick={() => setSymbol(p.symbol)}
                className={cn(
                  "rounded-full border px-2.5 py-1 text-xs transition-colors",
                  symbol === p.symbol
                    ? "border-transparent bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {p.label}
              </button>
            ))}
          </div>
          <p className="text-xs text-muted-foreground">
            Active: <span className="font-mono text-foreground">{symbol}</span>
          </p>
        </CardContent>
      </Card>

      <TradingViewWidget
        label="Chart"
        height={500}
        script="advanced-chart"
        config={{ symbol, style: "1", interval: "D", hide_side_toolbar: false, allow_symbol_change: true }}
      />

      <div className="grid gap-6 xl:grid-cols-2">
        <div className="space-y-2">
          <h2 className="text-sm font-semibold">Technical analysis</h2>
          <TradingViewWidget
            label="Technicals"
            height={420}
            script="technical-analysis"
            config={{ symbol, interval: "1D", showIntervalTabs: true, displayMode: "single" }}
          />
        </div>
        <div className="space-y-2">
          <h2 className="text-sm font-semibold">Fundamentals</h2>
          <TradingViewWidget
            label="Fundamentals"
            height={420}
            script="financials"
            config={{ symbol, displayMode: "regular", largeChartUrl: "" }}
          />
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Stock screener — India</CardTitle>
          <p className="text-xs text-muted-foreground">
            Screen the NSE/BSE universe by overview, performance, valuation, dividends, and more.
          </p>
        </CardHeader>
        <CardContent className="p-0">
          <TradingViewWidget
            label="Screener"
            height={520}
            script="screener"
            config={{
              market: "india",
              screener_type: "stock",
              defaultColumn: "overview",
              defaultScreen: "most_capitalized",
            }}
          />
        </CardContent>
      </Card>
    </div>
  );
}
