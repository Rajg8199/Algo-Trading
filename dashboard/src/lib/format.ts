/** Formatting helpers. All timestamps render in IST — the market's clock. */

const IST_FMT = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  dateStyle: "medium",
  timeStyle: "short",
});

const IST_TIME = new Intl.DateTimeFormat("en-IN", {
  timeZone: "Asia/Kolkata",
  timeStyle: "medium",
});

export function fmtIst(value: string | null | undefined): string {
  if (!value) return "—";
  return IST_FMT.format(new Date(value));
}

export function fmtIstTime(value: string | null | undefined): string {
  if (!value) return "—";
  return IST_TIME.format(new Date(value));
}

export function fmtInt(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-IN").format(Math.round(value));
}

export function fmtRupees(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `₹${new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(value)}`;
}

export function fmtNum(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "—";
  return value.toFixed(digits);
}

export function fmtPct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(digits)}%`;
}

export function agoMinutes(value: string | null | undefined): number | null {
  if (!value) return null;
  return Math.round((Date.now() - new Date(value).getTime()) / 60_000);
}
