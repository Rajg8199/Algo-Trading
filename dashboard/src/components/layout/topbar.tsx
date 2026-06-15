"use client";

import { Menu, Search } from "lucide-react";

import { SidebarNav } from "@/components/layout/sidebar";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { useOpsSummary } from "@/lib/api/queries";
import { agoMinutes } from "@/lib/format";
import { useUiStore } from "@/stores/ui";

function FreshnessDot() {
  const { data } = useOpsSummary();
  const mins = agoMinutes(data?.data.lastChainSnapshot);
  const color =
    mins === null ? "bg-zinc-500" : mins <= 3 ? "bg-emerald-500" : mins <= 10 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2 text-xs text-muted-foreground">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      <span className="hidden sm:inline">
        {mins === null ? "no snapshot" : `snapshot ${mins}m ago`}
      </span>
      {data?.isMock ? <span className="rounded bg-amber-500/15 px-1.5 py-0.5 font-medium text-amber-500">MOCK</span> : null}
    </div>
  );
}

function SearchTrigger() {
  const setPaletteOpen = useUiStore((s) => s.setPaletteOpen);
  return (
    <button
      type="button"
      onClick={() => setPaletteOpen(true)}
      aria-label="Open command palette"
      className="flex items-center gap-2 rounded-md border bg-muted/40 px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-muted"
    >
      <Search className="h-3.5 w-3.5" />
      <span className="hidden sm:inline">Search…</span>
      <kbd className="hidden rounded border bg-background px-1.5 py-0.5 font-sans text-[10px] sm:inline">
        ⌘K
      </kbd>
    </button>
  );
}

export function Topbar() {
  const { sidebarOpen, setSidebarOpen } = useUiStore();
  return (
    <header className="flex h-14 items-center justify-between border-b bg-card px-4">
      <div className="flex items-center gap-3">
        <Sheet open={sidebarOpen} onOpenChange={setSidebarOpen}>
          <SheetTrigger
            render={
              <Button variant="ghost" size="icon" className="lg:hidden" aria-label="Open navigation" />
            }
          >
            <Menu className="h-5 w-5" />
          </SheetTrigger>
          <SheetContent side="left" className="w-64 p-0">
            <SheetHeader className="border-b px-4 py-3">
              <SheetTitle className="text-sm">trading-platform</SheetTitle>
            </SheetHeader>
            <div className="py-3">
              <SidebarNav onNavigate={() => setSidebarOpen(false)} />
            </div>
          </SheetContent>
        </Sheet>
        <span className="text-sm font-medium lg:hidden">trading-platform</span>
        <SearchTrigger />
      </div>
      <div className="flex items-center gap-2">
        <FreshnessDot />
        <ThemeToggle />
      </div>
    </header>
  );
}
