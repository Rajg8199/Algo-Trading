"""Live intraday scalp signals on index spot (NIFTY/SENSEX/BANKNIFTY).

Forward-test only — there is NO intraday history to backtest, so every signal is
UNVALIDATED context, never a validated edge. Index has no volume, so this uses
EMA(9/21) + RSI + ATR (no VWAP). Built from the recorder's ~2-min spot ticks, so
3/5-min bars are coarse. Scalping costs are brutal; treat alerts as cues for a
human with a hard stop, not auto-trades.
"""

from tp_research.scalp.signals import ScalpBar, ScalpParams, ScalpSignal, scalp_signal

__all__ = ["ScalpBar", "ScalpParams", "ScalpSignal", "scalp_signal"]
