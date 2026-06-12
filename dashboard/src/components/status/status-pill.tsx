import { cn } from "@/lib/utils";

const TONES: Record<string, string> = {
  GREEN: "bg-emerald-500/15 text-emerald-500",
  YELLOW: "bg-amber-500/15 text-amber-500",
  RED: "bg-red-500/15 text-red-500",
  PENDING: "bg-zinc-500/15 text-zinc-400",
  up: "bg-emerald-500/15 text-emerald-500",
  down: "bg-red-500/15 text-red-500",
  REJECT: "bg-red-500/15 text-red-500",
  INVESTIGATE: "bg-amber-500/15 text-amber-500",
  PROMISING: "bg-sky-500/15 text-sky-500",
  ADVANCE_TO_PAPER_TRADING: "bg-emerald-500/15 text-emerald-500",
};

export function StatusPill({ status, label }: { status: string; label?: string }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        TONES[status] ?? "bg-zinc-500/15 text-zinc-400",
      )}
    >
      {label ?? status.replaceAll("_", " ")}
    </span>
  );
}

export function MockBadge({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <span className="inline-flex items-center rounded bg-amber-500/15 px-2 py-0.5 text-xs font-semibold text-amber-500">
      MOCK DATA — backend endpoint not connected
    </span>
  );
}
