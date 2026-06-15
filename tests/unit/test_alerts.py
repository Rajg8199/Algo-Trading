"""Breakout alert formatter tests — the safety-critical bit is that an
UNVALIDATED strategy can never produce a message that reads like advice."""

from __future__ import annotations

from datetime import date

from tp_research.screener.alerts import format_breakout_alert
from tp_research.screener.models import BreakoutSignal

DAY = date(2026, 6, 12)


def _sig(symbol: str, vol: float) -> BreakoutSignal:
    return BreakoutSignal(
        symbol=symbol, day=DAY, entry=100.0, stop=92.0, target=116.0, atr=4.0,
        donchian_high=99.5, sma_fast=95.0, sma_slow=90.0, volume_ratio=vol, risk_per_share=8.0,
    )


def test_unvalidated_message_carries_the_banner() -> None:
    msg = format_breakout_alert([_sig("NSE:RELIANCE", 2.5)], DAY, validated=False)
    assert "UNVALIDATED" in msg
    assert "NOT recommendations" in msg
    assert "RELIANCE" in msg
    assert "✅ VALIDATED" not in msg


def test_validated_message_drops_the_banner() -> None:
    msg = format_breakout_alert([_sig("NSE:TCS", 2.0)], DAY, validated=True)
    assert "UNVALIDATED" not in msg
    assert "VALIDATED strategy" in msg


def test_empty_scan_still_labels_unvalidated() -> None:
    msg = format_breakout_alert([], DAY, validated=False)
    assert "No breakouts today" in msg
    assert "UNVALIDATED" in msg


def test_position_size_appears() -> None:
    # 1% of 10L = 10000 risk / 8 per share = 1250 shares
    msg = format_breakout_alert(
        [_sig("NSE:X", 3.0)], DAY, validated=False, capital=1_000_000, risk_pct=0.01
    )
    assert "1250 sh" in msg
