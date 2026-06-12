import {
  Activity,
  FlaskConical,
  Gauge,
  LineChart,
  Microscope,
  Settings,
  ShieldAlert,
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
  { href: "/research", label: "Research", icon: Microscope },
  { href: "/experiments", label: "Experiments", icon: FlaskConical },
  { href: "/backtests", label: "Backtests", icon: LineChart },
  { href: "/paper-trading", label: "Paper Trading", icon: ShieldAlert },
  { href: "/settings", label: "Settings", icon: Settings },
];
