"use client";

/** TanStack Query hooks — the only way pages read data. Polling intervals
 * match data cadence (market data is minute-grade; nothing needs websockets). */

import { useQuery } from "@tanstack/react-query";

import { apiGet } from "./client";
import {
  mockBreakoutScan,
  mockBurnIn,
  mockPaperLeaderboard,
  mockPaperPnl,
  mockPaperPositions,
  mockPaperSignals,
  mockDqChecks,
  mockEquity,
  mockExperimentDetail,
  mockExperiments,
  mockFeatureSeries,
  mockOpsSummary,
  mockTrades,
} from "./mocks";
import type {
  BreakoutScan,
  BurnInDay,
  PaperLeaderboardRow,
  PaperPnlRow,
  PaperPositionRow,
  PaperSignalRow,
  DQCheck,
  EquityPoint,
  ExperimentDetail,
  ExperimentSummary,
  FeatureSeries,
  OpsSummary,
  TradeRow,
} from "./types";

const POLL_FAST = 30_000;
const POLL_SLOW = 120_000;

export function useOpsSummary() {
  return useQuery({
    queryKey: ["ops", "summary"],
    queryFn: () => apiGet<OpsSummary>("/api/v1/ops/summary", mockOpsSummary),
    refetchInterval: POLL_FAST,
  });
}

export function useDqChecks(days = 7) {
  return useQuery({
    queryKey: ["ops", "dq", days],
    queryFn: () => apiGet<DQCheck[]>(`/api/v1/ops/dq?days=${days}`, mockDqChecks),
    refetchInterval: POLL_SLOW,
  });
}

export function useBurnIn() {
  return useQuery({
    queryKey: ["ops", "burnin"],
    queryFn: () => apiGet<BurnInDay[]>("/api/v1/ops/burnin", mockBurnIn),
    refetchInterval: POLL_SLOW,
  });
}

export function useExperiments() {
  return useQuery({
    queryKey: ["experiments"],
    queryFn: () => apiGet<ExperimentSummary[]>("/api/v1/experiments", mockExperiments),
    refetchInterval: POLL_SLOW,
  });
}

export function useExperiment(runId: string) {
  return useQuery({
    queryKey: ["experiments", runId],
    queryFn: () =>
      apiGet<ExperimentDetail>(`/api/v1/experiments/${runId}`, mockExperimentDetail),
  });
}

export function useBacktestEquity(runId: string) {
  return useQuery({
    queryKey: ["backtests", runId, "equity"],
    queryFn: () => apiGet<EquityPoint[]>(`/api/v1/backtests/${runId}/equity`, mockEquity),
  });
}

export function useBacktestTrades(runId: string) {
  return useQuery({
    queryKey: ["backtests", runId, "trades"],
    queryFn: () => apiGet<TradeRow[]>(`/api/v1/backtests/${runId}/trades`, mockTrades),
  });
}

export function useFeatureSeries(featureName: string, entity: string) {
  return useQuery({
    queryKey: ["features", featureName, entity],
    queryFn: () =>
      apiGet<FeatureSeries>(
        `/api/v1/features?name=${featureName}&entity=${entity}`,
        mockFeatureSeries(featureName, entity),
      ),
    refetchInterval: POLL_SLOW,
  });
}

export function usePaperLeaderboard() {
  return useQuery({
    queryKey: ["paper", "leaderboard"],
    queryFn: () => apiGet<PaperLeaderboardRow[]>("/api/v1/paper/leaderboard", mockPaperLeaderboard),
    refetchInterval: POLL_SLOW,
  });
}

export function usePaperSignals() {
  return useQuery({
    queryKey: ["paper", "signals"],
    queryFn: () => apiGet<PaperSignalRow[]>("/api/v1/paper/signals", mockPaperSignals),
    refetchInterval: POLL_FAST,
  });
}

export function usePaperPositions() {
  return useQuery({
    queryKey: ["paper", "positions"],
    queryFn: () => apiGet<PaperPositionRow[]>("/api/v1/positions?mode=PAPER", mockPaperPositions),
    refetchInterval: POLL_FAST,
  });
}

export function usePaperPnl() {
  return useQuery({
    queryKey: ["paper", "pnl"],
    queryFn: () => apiGet<PaperPnlRow[]>("/api/v1/pnl?mode=PAPER", mockPaperPnl),
    refetchInterval: POLL_SLOW,
  });
}

export function useBreakoutScan() {
  return useQuery({
    queryKey: ["signals", "breakout"],
    queryFn: () => apiGet<BreakoutScan>("/api/v1/signals/breakout", mockBreakoutScan),
    refetchInterval: POLL_SLOW,
  });
}
