"""Index options market-structure digest (NIFTY / SENSEX / BANKNIFTY).

Factual IV / term-structure / skew / OI snapshot from the feature store — a
monitoring digest, NOT a trading signal. There is no validated options edge
(EXP-001-EOD = INVESTIGATE), so this deliberately never tells you to buy or sell
anything.
"""

from tp_research.options.digest import (
    OPTIONS_UNDERLYINGS,
    format_live_options,
    format_options_digest,
)
from tp_research.options.live import (
    LiveOptionsSnapshot,
    load_india_vix,
    load_live_snapshot,
    summarize_live,
)

__all__ = [
    "OPTIONS_UNDERLYINGS",
    "LiveOptionsSnapshot",
    "format_live_options",
    "format_options_digest",
    "load_india_vix",
    "load_live_snapshot",
    "summarize_live",
]
