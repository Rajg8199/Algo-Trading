"use client";

/** Live market strip — TradingView's embeddable ticker tape (free, no key).
 * This is the one genuinely real-time element in an otherwise polled console,
 * so it streams independent of the backend. Re-mounts on theme change so its
 * own colors track ours. External script, so it loads async and degrades to
 * empty space if TradingView is unreachable. */

import { useEffect, useRef } from "react";

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

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    container.innerHTML = "";

    const script = document.createElement("script");
    script.src =
      "https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js";
    script.async = true;
    script.type = "text/javascript";
    script.innerHTML = JSON.stringify({
      symbols: SYMBOLS,
      showSymbolLogo: false,
      isTransparent: true,
      displayMode: "adaptive",
      colorTheme: theme,
      locale: "en",
    });
    container.appendChild(script);

    return () => {
      container.innerHTML = "";
    };
  }, [theme]);

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <div ref={containerRef} className="tradingview-widget-container min-h-[46px]" />
    </div>
  );
}
