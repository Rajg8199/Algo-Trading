"""EOD equity breakout scan -> Telegram watchlist.

Ingests today's NSE cash bhavcopy, scans the liquid universe for breakouts, and
pushes a clearly-labelled message. The strategy is UNVALIDATED (see
docs/research/breakout-screen-findings.md — no proven edge), so the alert is a
watchlist, never a recommendation. Runs after close; retried hourly until the
bhavcopy is published.
"""

from datetime import date

from tp_research.equity.bhav import download_equity_bhav
from tp_research.equity.importer import filter_liquid, import_bhav_file, load_recent_bars, universe
from tp_research.screener import BreakoutParams, MomentumParams, current_picks, scan
from tp_research.screener.alerts import format_breakout_alert, format_momentum_alert

from tp_core.models import Severity
from tp_core.telemetry.logging import get_logger
from tp_core.timeutils import now_ist
from tp_scheduler.context import JobContext

log = get_logger(__name__)

# The backtest never cleared the acceptance gate, so signals stay UNVALIDATED.
VALIDATED = False
MIN_TURNOVER_CR = 5.0


async def run(ctx: JobContext, for_date: date | None = None) -> None:
    holidays = await ctx.events.holidays()
    today = for_date or now_ist().date()
    if today.weekday() >= 5 or today in holidays:
        return

    # Fresh data first — 404 raises FileNotFoundError, which the scheduler's
    # hourly retry treats as "not published yet".
    raw = await download_equity_bhav(today)
    imported = await import_bhav_file(ctx.db, raw)
    log.info("breakout_scan_ingested", date=today.isoformat(), bars=imported)

    params = BreakoutParams()
    syms = await universe(ctx.db, min_days=params.min_history)
    bars = await load_recent_bars(ctx.db, symbols=syms, lookback_per_symbol=300)
    liquid = filter_liquid(bars, MIN_TURNOVER_CR)
    signals = scan(dict(liquid), params)
    log.info(
        "breakout_scan_done", date=today.isoformat(), universe=len(liquid), signals=len(signals)
    )

    # `signal_` is a passthrough prefix in the telegram router -> sent immediately.
    message = format_breakout_alert(signals, today, validated=VALIDATED)
    await ctx.alert(Severity.INFO, f"signal_breakout_{today.isoformat()}", message)

    # Momentum book — also UNVALIDATED (see docs/research/momentum-screen.md).
    picks, risk_on = current_picks(dict(liquid), MomentumParams())
    mom = format_momentum_alert(picks, today, risk_on=risk_on, validated=VALIDATED)
    await ctx.alert(Severity.INFO, f"signal_momentum_{today.isoformat()}", mom)
    log.info("momentum_book_sent", date=today.isoformat(), picks=len(picks), risk_on=risk_on)
