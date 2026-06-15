/** Mock payloads used ONLY when the backend endpoint is unreachable or not
 * yet implemented. Every consumer renders a visible MOCK badge when these
 * are served — mock data must never be mistakable for recorded data. */

import type {
  BreakoutScan,
  OptionChain,
  ScalpReview,
  PaperLeaderboardRow,
  PaperPnlRow,
  PaperPositionRow,
  PaperSignalRow,
  BurnInDay,
  DQCheck,
  EquityPoint,
  ExperimentDetail,
  ExperimentSummary,
  FeatureSeries,
  OpsSummary,
  TradeRow,
} from "./types";

const NOW = new Date();
const iso = (minsAgo: number) => new Date(NOW.getTime() - minsAgo * 60_000).toISOString();
const day = (n: number) => new Date(NOW.getTime() - n * 86_400_000).toISOString().slice(0, 10);

export const mockOpsSummary: OpsSummary = {
  services: { recorder: true, scheduler: true, api: true, telegram: true, db: true, redis: true },
  lastTick: iso(1),
  lastChainSnapshot: iso(2),
  ticksLast5m: 4210,
  chainRowsLast5m: 1840,
  openDataGaps: 0,
  upstoxToken: "valid",
  ticksToday: { NIFTY: 182_450, SENSEX: 121_300 },
  chainRowsToday: { NIFTY: 158_200, SENSEX: 96_400 },
};

export const mockDqChecks: DQCheck[] = [
  { checkDate: day(0), checkName: "completeness_ticks_NIFTY", passed: true, details: { rows: 182450, minimum: 50000 } },
  { checkDate: day(0), checkName: "completeness_option_chain_NIFTY", passed: true, details: { rows: 158200, minimum: 10000 } },
  { checkDate: day(0), checkName: "chain_gaps_NIFTY", passed: true, details: { max_gap_seconds: 64 } },
  { checkDate: day(0), checkName: "missing_strikes_SENSEX", passed: false, details: { missing_pct: 3.2 } },
  { checkDate: day(0), checkName: "invalid_greeks_NIFTY", passed: true, details: { pct: 0.12 } },
  { checkDate: day(0), checkName: "oi_consistency_NIFTY", passed: true, details: {} },
];

export const mockBurnIn: BurnInDay[] = Array.from({ length: 10 }, (_, i) => ({
  day: i + 1,
  date: day(9 - i),
  status: i < 3 ? (i === 0 ? "YELLOW" : "GREEN") : "PENDING",
  grades:
    i < 3
      ? [
          { name: "ticks_NIFTY", status: "GREEN", detail: "182,450" },
          { name: "chain_rows_NIFTY", status: "GREEN", detail: "158,200" },
          { name: "max_chain_gap_s_NIFTY", status: i === 0 ? "YELLOW" : "GREEN", detail: i === 0 ? "164s" : "61s" },
        ]
      : [],
}));

export const mockExperiments: ExperimentSummary[] = [
  {
    runId: "9f2b1c44-mock",
    hypothesis: "H1-VRP-EXP001",
    strategy: "vrp_nifty",
    kind: "BACKTEST",
    trialNumber: 1,
    decision: null,
    dsr: null,
    createdAt: iso(60 * 24),
    gitSha: "41d2e93",
  },
];

export const mockExperimentDetail: ExperimentDetail = {
  ...mockExperiments[0],
  decision: "INVESTIGATE",
  dsr: 0.62,
  params: { grid: "registered-72", protocol: "vrp-experiment-001" },
  gates: [
    { name: "profit_factor", passed: true, detail: "1.71 vs > 1.5" },
    { name: "sharpe", passed: false, detail: "1.21 vs > 1.5" },
    { name: "max_drawdown", passed: true, detail: "6.4% vs < 10%" },
    { name: "sample_size", passed: false, detail: "84 vs >= 100" },
    { name: "monte_carlo", passed: true, detail: "p95 dd 9.8%" },
    { name: "walk_forward", passed: false, detail: "OOS sharpe=1.1" },
  ],
  metrics: {
    expected: {
      netPnl: 184_500, sharpe: 1.21, profitFactor: 1.71, expectancy: 2196,
      maxDrawdownPct: 6.4, winRate: 0.64, nTrades: 84, nDays: 246, totalCosts: 61_240,
    },
    best: {
      netPnl: 248_900, sharpe: 1.62, profitFactor: 2.05, expectancy: 2963,
      maxDrawdownPct: 5.1, winRate: 0.68, nTrades: 84, nDays: 246, totalCosts: 48_100,
    },
    worst: {
      netPnl: 121_700, sharpe: 0.84, profitFactor: 1.42, expectancy: 1449,
      maxDrawdownPct: 8.2, winRate: 0.60, nTrades: 84, nDays: 246, totalCosts: 74_800,
    },
  },
  monteCarlo: { maxDdP95: 98_000, maxDdP99: 131_000, maxDdP999: 162_000, riskOfRuin: 0.004, probNegativePnl: 0.06 },
  regimeSharpes: { low: 0.9, mid: 1.6, high: 0.4 },
  reasons: ["near-miss; failed gates: sharpe, sample_size", "action: extend data, re-run SAME grid"],
  screen: false,
  entryFunnel: [
    { label: "feature-complete days", days: 246 },
    { label: "VRP ≥ 1.0", days: 198 },
    { label: "IV pctile ≥ 70", days: 92 },
    { label: "contango (slope ≥ 0)", days: 71 },
    { label: "vov ≤ 1.5", days: 84 },
  ],
};

export const mockEquity: EquityPoint[] = Array.from({ length: 180 }, (_, i) => {
  const equity = Math.round(1000 * i + 14_000 * Math.sin(i / 9) + 220 * (i % 13));
  return { ts: day(180 - i), equity, drawdown: Math.max(0, Math.round(9000 + 7000 * Math.sin(i / 7)) - 8000) };
});

export const mockTrades: TradeRow[] = Array.from({ length: 12 }, (_, i) => ({
  ts: iso(60 * 24 * (12 - i)),
  instrumentId: 51_000 + i,
  side: i % 4 === 0 ? "BUY" : "SELL",
  qty: 75,
  price: 84.5 + i * 3.2,
  costs: 41.2,
  tag: i % 3 === 0 ? "SETTLE" : "OPEN",
  realizedPnl: i % 3 === 0 ? 2150 - (i % 5) * 900 : 0,
}));

export const mockFeatureSeries = (featureName: string, entity: string): FeatureSeries => ({
  featureName,
  entity,
  points: Array.from({ length: 60 }, (_, i) => ({
    ts: day(60 - i),
    value: 13 + 3 * Math.sin(i / 6) + (i % 7) * 0.2,
  })),
});

export const mockPaperLeaderboard: PaperLeaderboardRow[] = [
  { strategy: "vrp_nifty", netPnl: 18450, days: 6, dayWinRate: 0.67, trades: 14 },
];

export const mockPaperSignals: PaperSignalRow[] = [
  {
    orderId: "mock-1", strategy: "vrp_nifty", side: "SELL", qty: 75,
    createdAt: iso(60), snapshot: { leg: "SELL_CE_24700", delta: 0.25 },
    price: 62.4, slippage: 0.45,
  },
];

export const mockPaperPositions: PaperPositionRow[] = [
  { strategy: "vrp_nifty", instrument_id: 51234, qty: -75, avg_price: 62.4, realized_pnl: 0 },
];

export const mockPaperPnl: PaperPnlRow[] = Array.from({ length: 6 }, (_, i) => ({
  trade_date: day(6 - i), strategy: "vrp_nifty",
  gross_pnl: 4000 - i * 600, net_pnl: 3400 - i * 600, n_trades: 2,
}));

export const mockScalpReview: ScalpReview = {
  days: 30,
  overall: { n: 24, wins: 8, losses: 13, open: 3, hitRate: 8 / 21, expectancyR: -0.18 },
  byTimeframe: [
    { timeframe: "3m", n: 14, wins: 5, losses: 8, open: 1, hitRate: 5 / 13, expectancyR: -0.21 },
    { timeframe: "5m", n: 10, wins: 3, losses: 5, open: 2, hitRate: 3 / 8, expectancyR: -0.13 },
  ],
  recent: Array.from({ length: 8 }, (_, i) => {
    const out = i % 3 === 0 ? "WIN" : i % 3 === 1 ? "LOSS" : "OPEN";
    return {
      ts: iso(i * 25 + 5),
      underlying: ["NIFTY", "SENSEX", "BANKNIFTY"][i % 3],
      timeframe: i % 2 ? "5m" : "3m",
      side: i % 2 ? "SHORT" : "LONG",
      entry: 24500 - i * 7,
      stop: 24470 - i * 7,
      target: 24545 - i * 7,
      outcome: out,
      rMultiple: out === "WIN" ? 1.5 : out === "LOSS" ? -1 : 0.2,
    };
  }),
};

export function mockOptionChain(underlying: string): OptionChain {
  const spot = underlying === "SENSEX" ? 76250 : underlying === "BANKNIFTY" ? 51200 : 24500;
  const step = underlying === "NIFTY" ? 50 : 100;
  const atm = Math.round(spot / step) * step;
  const rows = Array.from({ length: 11 }, (_, i) => {
    const strike = atm + (i - 5) * step;
    const d = (strike - spot) / spot;
    return {
      strike,
      call: { iv: 14 + i * 0.2, oi: 90000 - Math.abs(strike - spot) * 2, oiChg: 4000 - i * 300, ltp: Math.max(2, (spot - strike) * 0.4 + 120), delta: Math.max(0.02, 0.5 - d * 6) },
      put: { iv: 14.4 + i * 0.18, oi: 80000 - Math.abs(strike - spot) * 2, oiChg: 3000 - i * 250, ltp: Math.max(2, (strike - spot) * 0.4 + 110), delta: Math.min(-0.02, -0.5 - d * 6) },
    };
  });
  return { underlying, ts: iso(2), spot, expiry: day(-3), rows };
}

export const mockBreakoutScan: BreakoutScan = {
  asOf: day(0),
  validated: false, // backtest has not cleared the gate — alerts stay UNVALIDATED
  capital: 1_000_000,
  riskPct: 0.01,
  backtest: {
    nTrades: 41,
    winRate: 0.39,
    expectancyR: 0.18,
    profitFactor: 1.22,
    maxDrawdownPct: 18.4,
    totalReturnPct: 26.7,
    avgHoldingDays: 9.3,
    acceptable: false, // PF 1.22 < 1.3 gate → not promoted
  },
  signals: [
    {
      symbol: "NSE:TATAMOTORS", day: day(0), entry: 982.4, stop: 941.2, target: 1064.8,
      atr: 20.6, donchianHigh: 978.0, volumeRatio: 2.8, riskPerShare: 41.2, suggestedQty: 242,
    },
    {
      symbol: "NSE:RELIANCE", day: day(0), entry: 1432.0, stop: 1379.5, target: null,
      atr: 26.2, donchianHigh: 1428.6, volumeRatio: 2.1, riskPerShare: 52.5, suggestedQty: 190,
    },
    {
      symbol: "NSE:HINDALCO", day: day(0), entry: 678.9, stop: 651.3, target: 734.1,
      atr: 13.8, donchianHigh: 676.2, volumeRatio: 1.9, riskPerShare: 27.6, suggestedQty: 362,
    },
  ],
};
