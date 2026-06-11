"""Pre-persistence validation. Bad rows never reach research tables —
they are counted, logged, and dropped (the log line is the quarantine)."""

from decimal import Decimal

from tp_core.models import ChainRow, Tick
from tp_core.telemetry.logging import get_logger
from tp_core.telemetry.metrics import VALIDATION_FAILURES

log = get_logger(__name__)

# Widest plausible single-update move for an index/derivative quote.
MAX_JUMP_FRACTION = Decimal("0.20")


class TickValidator:
    """Stateful per-instrument sanity checks for the hot tick path."""

    def __init__(self) -> None:
        self._last_ltp: dict[int, Decimal] = {}

    def validate(self, tick: Tick) -> bool:
        if tick.ltp <= 0:
            self._reject("nonpositive_ltp", tick.instrument_id)
            return False
        if tick.bid is not None and tick.ask is not None and tick.bid > tick.ask:
            self._reject("crossed_quote", tick.instrument_id)
            return False
        last = self._last_ltp.get(tick.instrument_id)
        if last is not None and last > 0:
            jump = abs(tick.ltp - last) / last
            # Options legitimately jump hard; only indices/futures get the bound.
            if jump > MAX_JUMP_FRACTION and tick.ltp > 1000:
                self._reject("price_jump", tick.instrument_id)
                return False
        self._last_ltp[tick.instrument_id] = tick.ltp
        return True

    @staticmethod
    def _reject(check: str, instrument_id: int) -> None:
        VALIDATION_FAILURES.labels(check=check).inc()
        log.warning("tick_rejected", check=check, instrument_id=instrument_id)


def validate_chain_row(row: ChainRow) -> bool:
    if row.bid is not None and row.ask is not None and row.bid > row.ask:
        VALIDATION_FAILURES.labels(check="chain_crossed_quote").inc()
        return False
    if row.oi is not None and row.oi < 0:
        VALIDATION_FAILURES.labels(check="chain_negative_oi").inc()
        return False
    if row.iv is not None and not (0.0 <= row.iv <= 500.0):
        VALIDATION_FAILURES.labels(check="chain_iv_bounds").inc()
        return False
    return True
