"use client";

/** Live market strip — TradingView's embeddable ticker tape (free, no key).
 * This is the one genuinely real-time element in an otherwise polled console,
 * so it streams independent of the backend. Re-mounts on theme change so its
 * own colors track ours.
 *
 * The loader renders into a `.tradingview-widget-container__widget` child of
 * the container — that inner div is REQUIRED; without it the strip is blank.
 * If the script fails to load (offline / blocked), we show a static fallback
 * row instead of empty space. */

import { useEffect, useRef, useState } from "react";

import { useUiStore } from "@/stores/ui";

const SYMBOLS = [
  { proName: "NSE:NIFTY", title: "NIFTY 50" },
  { proName: "BSE:SENSEX", title: "SENSEX" },
  { proName: "NSE:BANKNIFTY", title: "BANK NIFTY" },
  { proName: "NSE:CNXFINANCE", title: "FINNIFTY" },
  { proName: "NSE:INDIAVIX", title: "INDIA VIX" },
];

export function TickerTape() {
  const theme = useUiStore((s) => s.theme);
  const containerRef = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    container.innerHTML = "";
    setFailed(false);

    // Official embed structure: an inner mount div + the loader script.
    const widget = document.createElement("div");
    widget.className = "tradingview-widget-container__widget";
    container.appendChild(widget);

    const script = document.createElement("script");
    script.src =
      "https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js";
    script.async = true;
    script.type = "text/javascript";
    script.onerror = () => setFailed(true);
    script.text = JSON.stringify({
      symbols: SYMBOLS,
      showSymbolLogo: true,
      isTransparent: true,
      displayMode: "adaptive",
      colorTheme: theme,
      locale: "en",
    });
    container.appendChild(script);

    // If nothing rendered after a few seconds, treat it as a failure.
    const timer = window.setTimeout(() => {
      if (!container.querySelector("iframe")) setFailed(true);
    }, 6000);

    return () => {
      window.clearTimeout(timer);
      container.innerHTML = "";
    };
  }, [theme]);

  return (
    <div className="relative overflow-hidden rounded-lg border bg-card">
      <div ref={containerRef} className="tradingview-widget-container min-h-[52px]" />
      {failed ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-3 text-xs text-muted-foreground">
          <span className="font-medium text-foreground">Market data unavailable</span>
          {SYMBOLS.map((s) => (
            <span key={s.proName} className="tabular-nums">
              {s.title}
            </span>
          ))}
          <span className="ml-auto">TradingView feed unreachable</span>
        </div>
      ) : null}
    </div>
  );
}
