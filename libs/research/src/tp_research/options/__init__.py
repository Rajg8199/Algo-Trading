"""Index options market-structure digest (NIFTY / SENSEX / BANKNIFTY).

Factual IV / term-structure / skew / OI snapshot from the feature store — a
monitoring digest, NOT a trading signal. There is no validated options edge
(EXP-001-EOD = INVESTIGATE), so this deliberately never tells you to buy or sell
anything.
"""

from tp_research.options.digest import OPTIONS_UNDERLYINGS, format_options_digest

__all__ = ["OPTIONS_UNDERLYINGS", "format_options_digest"]
