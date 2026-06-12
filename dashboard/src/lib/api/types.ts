/** Contracts mirroring the FastAPI read endpoints (existing + planned).
 * Single source of truth for both real responses and mocks. */

export type ServiceName = "recorder" | "scheduler" | "api" | "telegram" | "db" | "redis";

export interface OpsSummary {
  services: Record<ServiceName, boolean>;
  lastTick: string | null;
  lastChainSnapshot: string | null;
  ticksLast5m: number;
  chainRowsLast5m: number;
  openDataGaps: number;
  upstoxToken: "valid" | "missing/expired";
  ticksToday: Record<string, number>;
  chainRowsToday: Record<string, number>;
}

export interface DQCheck {
  checkDate: string;
  checkName: string;
  passed: boolean;
  details: Record<string, unknown>;
}

export type BurnInStatus = "GREEN" | "YELLOW" | "RED";

export interface BurnInGrade {
  name: string;
  status: BurnInStatus;
  detail: string;
}

export interface BurnInDay {
  day: number;
  date: string;
  status: BurnInStatus | "PENDING";
  grades: BurnInGrade[];
}

export type ExperimentDecision =
  | "REJECT"
  | "INVESTIGATE"
  | "PROMISING"
  | "ADVANCE_TO_PAPER_TRADING";

export interface ExperimentSummary {
  runId: string;
  hypothesis: string;
  strategy: string | null;
  kind: string;
  trialNumber: number;
  decision: ExperimentDecision | null;
  dsr: number | null;
  createdAt: string;
  gitSha: string;
}

export interface GateResult {
  name: string;
  passed: boolean;
  detail: string;
}

export interface ExperimentDetail extends ExperimentSummary {
  params: Record<string, unknown>;
  gates: GateResult[];
  metrics: {
    expected: ScenarioMetrics | null;
    best: ScenarioMetrics | null;
    worst: ScenarioMetrics | null;
  };
  monteCarlo: MonteCarloSummary | null;
  regimeSharpes: Record<string, number>;
}

export interface ScenarioMetrics {
  netPnl: number;
  sharpe: number | null;
  profitFactor: number | null;
  expectancy: number | null;
  maxDrawdownPct: number;
  winRate: number | null;
  nTrades: number;
  nDays: number;
  totalCosts: number;
}

export interface MonteCarloSummary {
  maxDdP95: number;
  maxDdP99: number;
  maxDdP999: number;
  riskOfRuin: number;
  probNegativePnl: number;
}

export interface EquityPoint {
  ts: string;
  equity: number;
  drawdown: number;
}

export interface TradeRow {
  ts: string;
  instrumentId: number;
  side: string;
  qty: number;
  price: number;
  costs: number;
  tag: string;
  realizedPnl: number;
}

export interface FeaturePoint {
  ts: string;
  value: number;
}

export interface FeatureSeries {
  featureName: string;
  entity: string;
  points: FeaturePoint[];
}

export interface PaperLeaderboardRow {
  strategy: string;
  netPnl: number;
  days: number;
  dayWinRate: number | null;
  trades: number;
}

export interface PaperSignalRow {
  orderId: string;
  strategy: string;
  side: string;
  qty: number;
  createdAt: string;
  snapshot: Record<string, unknown>;
  price: number | null;
  slippage: number | null;
}

export interface PaperPositionRow {
  strategy: string;
  instrument_id: number;
  qty: number;
  avg_price: number | null;
  realized_pnl: number;
}

export interface PaperPnlRow {
  trade_date: string;
  strategy: string;
  gross_pnl: number | null;
  net_pnl: number | null;
  n_trades: number | null;
}
