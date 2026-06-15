"use client";

/** Generic TradingView embed wrapper (free widgets, no key). Generalises the
 * ticker-tape pattern: mounts the loader into the required
 * `.tradingview-widget-container__widget` child, re-mounts on theme/config
 * change, and shows a fallback instead of blank space when the external script
 * is blocked or offline.
 *
 * These widgets stream TradingView's OWN data — they are external analysis
 * tools, deliberately separate from the platform's validated pipeline. */

import { useEffect, useRef, useState } from "react";

import { useUiStore } from "@/stores/ui";

export function TradingViewWidget({
  script,
  config,
  height = 420,
  label = "TradingView widget",
}: {
  /** Widget id, e.g. "advanced-chart", "technical-analysis", "financials", "screener". */
  script: string;
  config: Record<string, unknown>;
  height?: number;
  label?: string;
}) {
  const theme = useUiStore((s) => s.theme);
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);
  const configKey = JSON.stringify(config);

  useEffect(() => {
    const container = ref.current;
    if (!container) return;
    container.innerHTML = "";
    setFailed(false);

    const widget = document.createElement("div");
    widget.className = "tradingview-widget-container__widget";
    widget.style.height = `${height}px`;
    container.appendChild(widget);

    const el = document.createElement("script");
    el.src = `https://s3.tradingview.com/external-embedding/embed-widget-${script}.js`;
    el.async = true;
    el.type = "text/javascript";
    el.onerror = () => setFailed(true);
    // Defaults first; per-widget config wins. theme + colorTheme both set so
    // each widget reads whichever key it understands.
    el.text = JSON.stringify({
      colorTheme: theme,
      theme,
      locale: "en",
      isTransparent: true,
      autosize: true,
      ...config,
    });
    container.appendChild(el);

    const timer = window.setTimeout(() => {
      if (!container.querySelector("iframe")) setFailed(true);
    }, 6000);

    return () => {
      window.clearTimeout(timer);
      container.innerHTML = "";
    };
    // configKey is the stringified `config` — used instead of the object to
    // avoid re-running on identity-only changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [script, configKey, theme, height]);

  return (
    <div className="relative overflow-hidden rounded-lg border bg-card">
      <div ref={ref} className="tradingview-widget-container" style={{ height }} />
      {failed ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 p-4 text-center text-xs text-muted-foreground">
          <span className="font-medium text-foreground">{label} unavailable</span>
          <span>TradingView feed unreachable — offline, or blocked by an extension.</span>
        </div>
      ) : null}
    </div>
  );
}
