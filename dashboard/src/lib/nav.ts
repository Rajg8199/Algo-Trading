import {
  Activity,
  CandlestickChart,
  FlaskConical,
  Gauge,
  LineChart,
  Microscope,
  Settings,
  ShieldAlert,
  Table2,
  Zap,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
}

export const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Overview", icon: Gauge },
  { href: "/operations", label: "Operations", icon: Activity },
  { href: "/markets", label: "Markets", icon: CandlestickChart },
  { href: "/option-chain", label: "Option Chain", icon: Table2 },
  { href: "/signals", label: "Signals", icon: Zap },
  { href: "/research", label: "Research", icon: Microscope },
  { href: "/experiments", label: "Experiments", icon: FlaskConical },
  { href: "/backtests", label: "Backtests", icon: LineChart },
  { href: "/paper-trading", label: "Paper Trading", icon: ShieldAlert },
  { href: "/settings", label: "Settings", icon: Settings },
];
