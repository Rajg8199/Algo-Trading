"""The acceptance gate (3F). Default verdict: REJECTED.

A strategy is judged on the EXPECTED fill scenario (spread-crossing,
1.5x slippage, latency) — BEST exists only to measure the gap. Every gate is
hard; there is no "close enough"; a missing input (None) FAILS its gate,
because absence of evidence is absence of evidence.
"""

from dataclasses import dataclass, field

from tp_backtest.fills import FillScenario
from tp_backtest.metrics import Metrics
from tp_backtest.montecarlo import MonteCarloReport


@dataclass(frozen=True)
class AcceptanceCriteria:
    min_profit_factor: float = 1.5
    min_sharpe: float = 1.5
    min_expectancy: float = 0.0  # strictly positive required
    max_drawdown_pct: float = 10.0
    min_trades: int = 100
    mc_max_dd_p95_pct: float = 15.0  # of capital
    mc_max_risk_of_ruin: float = 0.01
    max_unfillable_ratio: float = 0.05
    min_regime_sharpe: float = 0.0  # no regime bucket may be net-negative


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str


@dataclass
class Verdict:
    accepted: bool
    gates: list[GateResult] = field(default_factory=list)

    @property
    def failures(self) -> list[GateResult]:
        return [g for g in self.gates if not g.passed]

    def summary(self) -> str:
        status = "ACCEPTED" if self.accepted else "REJECTED"
        lines = [f"{status} — {len(self.failures)}/{len(self.gates)} gates failed"]
        lines += [f"  ✗ {g.name}: {g.detail}" for g in self.failures]
        return "\n".join(lines)


def _gate(name: str, passed: bool, detail: str) -> GateResult:
    return GateResult(name=name, passed=passed, detail=detail)


def evaluate(
    expected_metrics: Metrics,
    capital: float,
    mc: MonteCarloReport | None,
    walkforward_oos_metrics: Metrics | None,
    regime_sharpes: dict[str, float] | None,
    criteria: AcceptanceCriteria | None = None,
    scenario: FillScenario = FillScenario.EXPECTED,
) -> Verdict:
    c = criteria or AcceptanceCriteria()
    gates: list[GateResult] = []
    m = expected_metrics

    if scenario is not FillScenario.EXPECTED:
        gates.append(_gate("scenario", False, f"judged on {scenario}, must be EXPECTED"))

    gates.append(
        _gate(
            "profit_factor",
            m.profit_factor is not None and m.profit_factor > c.min_profit_factor,
            f"{m.profit_factor} vs > {c.min_profit_factor}",
        )
    )
    gates.append(
        _gate(
            "expectancy",
            m.expectancy is not None and m.expectancy > c.min_expectancy,
            f"{m.expectancy} vs > {c.min_expectancy}",
        )
    )
    gates.append(
        _gate(
            "sharpe",
            m.sharpe is not None and m.sharpe > c.min_sharpe,
            f"{m.sharpe} vs > {c.min_sharpe}",
        )
    )
    gates.append(
        _gate(
            "max_drawdown",
            m.max_drawdown_pct < c.max_drawdown_pct,
            f"{m.max_drawdown_pct:.2f}% vs < {c.max_drawdown_pct}%",
        )
    )
    gates.append(
        _gate("sample_size", m.n_trades >= c.min_trades, f"{m.n_trades} vs >= {c.min_trades}")
    )
    total_orders = m.n_trades + m.unfillable_orders
    unfillable_ratio = m.unfillable_orders / total_orders if total_orders else 0.0
    gates.append(
        _gate(
            "fillability",
            unfillable_ratio <= c.max_unfillable_ratio,
            f"{unfillable_ratio:.1%} unfillable vs <= {c.max_unfillable_ratio:.0%}",
        )
    )

    if mc is None:
        gates.append(_gate("monte_carlo", False, "not run or insufficient trades"))
    else:
        gates.append(
            _gate(
                "mc_drawdown_p95",
                100.0 * mc.max_dd_p95 / capital < c.mc_max_dd_p95_pct,
                f"{100.0 * mc.max_dd_p95 / capital:.1f}% vs < {c.mc_max_dd_p95_pct}%",
            )
        )
        gates.append(
            _gate(
                "risk_of_ruin",
                mc.risk_of_ruin <= c.mc_max_risk_of_ruin,
                f"{mc.risk_of_ruin:.4f} vs <= {c.mc_max_risk_of_ruin}",
            )
        )

    if walkforward_oos_metrics is None:
        gates.append(_gate("walk_forward", False, "no out-of-sample walk-forward result"))
    else:
        wf = walkforward_oos_metrics
        gates.append(
            _gate(
                "walk_forward",
                wf.sharpe is not None
                and wf.sharpe > c.min_sharpe
                and wf.expectancy is not None
                and wf.expectancy > 0,
                f"OOS sharpe={wf.sharpe}, expectancy={wf.expectancy}",
            )
        )

    if regime_sharpes is None or not regime_sharpes:
        gates.append(_gate("regime_analysis", False, "no regime-stratified results"))
    else:
        worst = min(regime_sharpes.items(), key=lambda kv: kv[1])
        gates.append(
            _gate(
                "regime_analysis",
                worst[1] >= c.min_regime_sharpe,
                f"worst regime {worst[0]}: sharpe {worst[1]:.2f}",
            )
        )

    return Verdict(accepted=all(g.passed for g in gates), gates=gates)
