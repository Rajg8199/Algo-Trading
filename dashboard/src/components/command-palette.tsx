"use client";

/** Global ⌘K / Ctrl-K command palette. Read-only navigator over the console:
 * jumps to any page and to any recorded experiment by hypothesis/strategy.
 * Mounted once in Providers so it is reachable from every route. */

import { Dialog } from "@base-ui/react/dialog";
import { CornerDownLeft, FlaskConical, Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { StatusPill } from "@/components/status/status-pill";
import { useExperiments } from "@/lib/api/queries";
import { NAV_ITEMS } from "@/lib/nav";
import { cn } from "@/lib/utils";
import { useUiStore } from "@/stores/ui";

interface PaletteItem {
  id: string;
  href: string;
  label: string;
  group: "Pages" | "Experiments";
  hint?: string;
  decision?: string | null;
  Icon?: typeof Search;
}

export function CommandPalette() {
  const router = useRouter();
  const { paletteOpen, setPaletteOpen } = useUiStore();
  const experiments = useExperiments();
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Global hotkey: ⌘K / Ctrl-K toggles; "/" opens when not typing in a field.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const k = e.key.toLowerCase();
      if (k === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setPaletteOpen(!paletteOpen);
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [paletteOpen, setPaletteOpen]);

  const items = useMemo<PaletteItem[]>(() => {
    const pages: PaletteItem[] = NAV_ITEMS.map((n) => ({
      id: `page:${n.href}`,
      href: n.href,
      label: n.label,
      group: "Pages",
      Icon: n.icon,
    }));
    const exps: PaletteItem[] = (experiments.data?.data ?? []).map((e) => ({
      id: `exp:${e.runId}`,
      href: `/experiments/${e.runId}`,
      label: e.hypothesis,
      group: "Experiments",
      hint: `${e.strategy ?? "—"} · trial #${e.trialNumber}`,
      decision: e.decision,
      Icon: FlaskConical,
    }));
    return [...pages, ...exps];
  }, [experiments.data]);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (it) => it.label.toLowerCase().includes(q) || (it.hint?.toLowerCase().includes(q) ?? false),
    );
  }, [items, query]);

  // Reset highlight + query each time the palette opens; focus the input.
  useEffect(() => {
    if (paletteOpen) {
      setQuery("");
      setActive(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [paletteOpen]);

  useEffect(() => {
    setActive((a) => Math.min(a, Math.max(0, results.length - 1)));
  }, [results.length]);

  function select(item: PaletteItem | undefined) {
    if (!item) return;
    setPaletteOpen(false);
    router.push(item.href);
  }

  function onInputKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      select(results[active]);
    }
  }

  let lastGroup: string | null = null;

  return (
    <Dialog.Root open={paletteOpen} onOpenChange={setPaletteOpen}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm transition-opacity duration-150 data-ending-style:opacity-0 data-starting-style:opacity-0" />
        <Dialog.Popup
          className={cn(
            "fixed left-1/2 top-[12vh] z-50 w-[92vw] max-w-xl -translate-x-1/2 overflow-hidden rounded-xl border bg-popover text-popover-foreground shadow-2xl outline-none",
            "transition-all duration-150 data-ending-style:scale-95 data-ending-style:opacity-0 data-starting-style:scale-95 data-starting-style:opacity-0",
          )}
        >
          <Dialog.Title className="sr-only">Command palette</Dialog.Title>
          <div className="flex items-center gap-2 border-b px-3">
            <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
            <input
              ref={inputRef}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={onInputKey}
              placeholder="Jump to a page or experiment…"
              aria-label="Search pages and experiments"
              className="h-12 w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            />
            <kbd className="hidden rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground sm:inline">
              ESC
            </kbd>
          </div>

          <ul className="max-h-[50vh] overflow-y-auto p-1.5" role="listbox" aria-label="Results">
            {results.length === 0 ? (
              <li className="px-3 py-8 text-center text-sm text-muted-foreground">
                No matches for “{query}”
              </li>
            ) : (
              results.map((item, i) => {
                const header = item.group !== lastGroup ? item.group : null;
                lastGroup = item.group;
                const Icon = item.Icon ?? Search;
                return (
                  <li key={item.id}>
                    {header ? (
                      <p className="px-2 pb-1 pt-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                        {header}
                      </p>
                    ) : null}
                    <button
                      type="button"
                      role="option"
                      aria-selected={i === active}
                      onMouseMove={() => setActive(i)}
                      onClick={() => select(item)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-md px-2 py-2 text-left text-sm transition-colors",
                        i === active ? "bg-accent text-accent-foreground" : "text-foreground",
                      )}
                    >
                      <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                      <span className="min-w-0 flex-1 truncate">{item.label}</span>
                      {item.hint ? (
                        <span className="hidden shrink-0 text-xs text-muted-foreground sm:inline">
                          {item.hint}
                        </span>
                      ) : null}
                      {item.decision ? <StatusPill status={item.decision} /> : null}
                      {i === active ? (
                        <CornerDownLeft className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      ) : null}
                    </button>
                  </li>
                );
              })
            )}
          </ul>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
