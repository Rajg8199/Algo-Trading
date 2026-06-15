"""NSE cash-market (equity) EOD ingestion for the breakout scanner.

Free historical OHLCV from NSE's UDiFF CM bhavcopy — the equity counterpart of
the F&O bhav pipeline. Feeds tp_research.screener with real daily bars so the
breakout strategy can be backtested on actual history before any alert is sent.
"""

from tp_research.equity.bhav import (
    EQUITY_BHAV_URL,
    EquityBhavProbe,
    download_equity_bhav,
    parse_equity_bhav,
    probe_equity_bhav,
)

__all__ = [
    "EQUITY_BHAV_URL",
    "EquityBhavProbe",
    "download_equity_bhav",
    "parse_equity_bhav",
    "probe_equity_bhav",
]
