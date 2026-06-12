"""Paper execution engine.

Drives the SAME ConditionalVRP strategy, RiskEngine, fill model (EXPECTED
scenario — real recorded bid/ask, spread-crossing, 1.5x slippage) and
position accounting as the backtester, but on live snapshots as the recorder
lands them. No broker API is imported anywhere in this package.

Persistence: every order/fill/position/pnl row written to the Phase-1 trading
tables (mode=PAPER). Restart-safe: the book rebuilds from the positions table.
"""

from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from tp_backtest.costs import option_trade_costs
from tp_backtest.dataset import _features_before  # shared leakage-safe loader
from tp_backtest.fills import FillScenario, fill_price
from tp_backtest.positions import BookEntry, PositionBook
from tp_backtest.strategies.vrp import ConditionalVRP, VRPParams

from tp_core.db import Database
from tp_core.db.repos import TradingRepo
from tp_core.models import OrderIntent, Severity, TradingMode
from tp_core.strategy import InstrumentMeta, MarketState, Quote, RiskEngine, RiskLimits
from tp_core.telemetry.logging import get_logger
from tp_core.timeutils import IST, now_ist
from tp_paper.signals import build_vrp_signal

log = get_logger(__name__)

_LATEST_SNAPSHOT_SQL = text("""
    WITH cut AS (
        SELECT max(oc.ts) AS ts FROM option_chain oc
        JOIN instruments i USING (instrument_id)
        WHERE i.underlying = :u AND oc.ts >= :day_start
    )
    SELECT oc.instrument_id, oc.ltp, oc.bid, oc.ask, oc.iv, oc.delta, oc.oi, oc.spot, cut.ts
    FROM option_chain oc JOIN instruments i USING (instrument_id), cut
    WHERE oc.ts = cut.ts AND i.underlying = :u
""")

_META_SQL = text("""
    SELECT instrument_id, underlying, segment, expiry, strike, option_type, lot_size
    FROM instruments WHERE underlying = ANY(:unders) AND is_active
""")


class PaperEngine:
    def __init__(self, db: Database, params: VRPParams, capital: float = 1_000_000.0) -> None:
        self.db = db
        self.params = params
        self.capital = capital
        self.strategy = ConditionalVRP(params)
        self.risk = RiskEngine(RiskLimits())
        self.book = PositionBook(strategy=self.strategy.name)
        self.trading = TradingRepo(db)
        self.meta: dict[int, InstrumentMeta] = {}
        self._day: date | None = None
        self._day_start_net = Decimal(0)
        self._day_trades = 0

    # ── lifecycle ────────────────────────────────────────────────────────
    async def start(self) -> None:
        async with self.db.session() as s:
            rows = (await s.execute(_META_SQL, {"unders": ["NIFTY", "SENSEX"]})).all()
        self.meta = {
            r.instrument_id: InstrumentMeta(
                r.instrument_id,
                r.underlying,
                r.segment,
                r.expiry,
                float(r.strike) if r.strike is not None else None,
                r.option_type,
                r.lot_size,
            )
            for r in rows
        }
        for pos in await self.trading.open_positions("PAPER", self.strategy.name):
            entry = self.book.entries.setdefault(pos.instrument_id, BookEntry())
            entry.qty = pos.qty
            entry.avg_price = pos.avg_price or Decimal(0)
            entry.realized = pos.realized_pnl
        log.info(
            "paper_engine_started",
            open_positions=sum(1 for e in self.book.entries.values() if e.qty != 0),
            params=str(self.params),
        )

    # ── per-snapshot tick ────────────────────────────────────────────────
    async def on_snapshot(self, underlying: str) -> list[tuple[Severity, str, str]]:
        """Process the latest recorded snapshot. Returns alerts to publish."""
        if underlying != self.params.underlying:
            return []
        day_start = datetime.combine(now_ist().date(), time(9, 0), tzinfo=IST)
        async with self.db.session() as s:
            rows = (
                await s.execute(_LATEST_SNAPSHOT_SQL, {"u": underlying, "day_start": day_start})
            ).all()
        if not rows:
            return []
        ts: datetime = rows[0].ts
        quotes: dict[int, Quote] = {}
        spot: dict[str, float] = {}
        for r in rows:
            quotes[r.instrument_id] = Quote(
                r.instrument_id,
                float(r.ltp) if r.ltp is not None else None,
                float(r.bid) if r.bid is not None else None,
                float(r.ask) if r.ask is not None else None,
                iv=float(r.iv) if r.iv is not None else None,
                delta=float(r.delta) if r.delta is not None else None,
                oi=float(r.oi) if r.oi is not None else None,
            )
            if r.spot is not None:
                spot[underlying] = float(r.spot)

        today = ts.astimezone(IST).date()
        alerts: list[tuple[Severity, str, str]] = []
        if today != self._day:
            alerts.extend(await self._roll_day(ts, today, spot))

        features = await _features_before(self.db, today)
        state = MarketState(ts=ts, spot=spot, quotes=quotes, meta=self.meta, features=features)
        state.positions = self.book.as_positions(TradingMode.PAPER)
        marks = {iid: q.mid for iid, q in quotes.items() if q.mid is not None}
        state.cash_pnl = self.book.net_pnl(marks)

        prev_open = self.strategy._open
        executed: list[OrderIntent] = []
        for intent in self.strategy.on_market(state):
            verdict = self.risk.validate(intent, state)
            if not verdict.accepted:
                alerts.append(
                    (Severity.P2, "paper_risk_reject", f"Paper intent rejected: {verdict.reason}")
                )
                continue
            alert = await self._execute(intent, state)
            executed.append(intent)
            if alert:
                alerts.append(alert)

        new_open = self.strategy._open
        if prev_open is None and new_open is not None and executed:
            legs = []
            for it in executed:
                raw = str(it.signal_snapshot.get("leg", ""))
                parts = raw.split("_")
                if len(parts) == 3:
                    legs.append((parts[0], float(parts[2]), parts[1]))
            expiry = next(
                (
                    str(self.meta[it.instrument_id].expiry)
                    for it in executed
                    if it.instrument_id in self.meta
                ),
                "?",
            )
            card = build_vrp_signal(state, self.params, legs, new_open.credit, expiry)
            alerts.append(
                (
                    Severity.INFO,
                    f"trade_entry_{state.ts.isoformat()}",
                    card.telegram_text(),
                )
            )
        await self._persist_pnl(today)
        return alerts

    # ── internals ────────────────────────────────────────────────────────
    async def _roll_day(
        self, ts: datetime, today: date, spot: dict[str, float]
    ) -> list[tuple[Severity, str, str]]:
        alerts: list[tuple[Severity, str, str]] = []
        before = self.book.realized_total
        pre_settle = len(self.book.trades)
        self.book.settle_expired(ts, today, self.meta, spot)
        for trade in self.book.trades[pre_settle:]:
            await self._persist_trade_row(
                trade.ts,
                trade.instrument_id,
                "SETTLE",
                trade.qty,
                trade.price,
                Decimal(0),
                None,
                {"reason": "expiry_settlement"},
            )
            alerts.append(
                (
                    Severity.INFO,
                    f"trade_settle_{trade.instrument_id}_{today}",
                    f"📉 PAPER EXIT (expiry settle) #{trade.instrument_id} "
                    f"@ {trade.price} · realized ₹{trade.realized_pnl:,.0f}",
                )
            )
        settled_pnl = self.book.realized_total - before
        if settled_pnl:
            log.info("paper_settled", pnl=str(settled_pnl))
        self._day = today
        self._day_start_net = self.book.realized_total - self.book.total_costs
        self._day_trades = 0
        return alerts

    async def _execute(
        self, intent: OrderIntent, state: MarketState
    ) -> tuple[Severity, str, str] | None:
        quote = state.quotes.get(intent.instrument_id)
        meta = self.meta.get(intent.instrument_id)
        if quote is None or meta is None:
            return (Severity.P2, "paper_unfillable", f"No quote for #{intent.instrument_id}")
        fill = fill_price(quote, intent.side, FillScenario.EXPECTED)
        if fill is None:
            return (
                Severity.P2,
                "paper_unfillable",
                f"Unfillable (no touch) #{intent.instrument_id}",
            )
        exchange = "BSE" if meta.underlying == "SENSEX" else "NSE"
        costs = option_trade_costs(intent.side, fill.price, intent.qty, exchange)
        self.book.apply_fill(
            state.ts, intent.instrument_id, intent.side, intent.qty, fill.price, costs.total
        )
        self._day_trades += 1
        await self._persist_trade_row(
            state.ts,
            intent.instrument_id,
            intent.side.value,
            intent.qty,
            fill.price,
            costs.total,
            fill.slippage_vs_mid,
            dict(intent.signal_snapshot),
        )
        reason = intent.signal_snapshot.get("reason", "")
        if reason == "stop":
            pos_pnl = self.book.entries[intent.instrument_id].realized
            return (
                Severity.INFO,
                f"trade_exit_{intent.instrument_id}_{state.ts.isoformat()}",
                f"🛑 PAPER EXIT (stop) {intent.side.value} #{intent.instrument_id} "
                f"{intent.qty} @ {fill.price} · leg realized ₹{pos_pnl:,.0f}",
            )
        return None  # entries get one consolidated SignalCard from main loop

    async def _persist_trade_row(
        self,
        ts: datetime,
        instrument_id: int,
        side: str,
        qty: int,
        price: Decimal,
        costs: Decimal,
        slippage: Decimal | None,
        snapshot: dict[str, Any],
    ) -> None:
        from uuid import uuid4

        order_id = uuid4()
        now = datetime.now(UTC)
        await self.trading.insert_order(
            {
                "order_id": order_id,
                "mode": "PAPER",
                "strategy": self.strategy.name,
                "instrument_id": instrument_id,
                "side": side if side in ("BUY", "SELL") else "SELL",
                "order_type": "MARKET",
                "qty": qty,
                "limit_price": None,
                "status": "FILLED",
                "reject_reason": None,
                "signal_snapshot": snapshot,
                "created_at": now,
                "updated_at": now,
            }
        )
        await self.trading.insert_fill(
            {
                "fill_id": uuid4(),
                "order_id": order_id,
                "ts": ts,
                "qty": qty,
                "price": price,
                "slippage": slippage,
                "costs": {"total": str(costs)},
            }
        )
        entry = self.book.entries.get(instrument_id)
        await self.trading.upsert_position(
            {
                "mode": "PAPER",
                "strategy": self.strategy.name,
                "instrument_id": instrument_id,
                "qty": entry.qty if entry else 0,
                "avg_price": entry.avg_price if entry else None,
                "realized_pnl": entry.realized if entry else Decimal(0),
                "updated_at": now,
            }
        )

    async def _persist_pnl(self, today: date) -> None:
        net_now = self.book.realized_total - self.book.total_costs
        await self.trading.upsert_pnl_daily(
            {
                "trade_date": today,
                "mode": "PAPER",
                "strategy": self.strategy.name,
                "gross_pnl": self.book.realized_total,
                "costs": self.book.total_costs,
                "net_pnl": net_now - self._day_start_net,
                "n_trades": self._day_trades,
                "max_intraday_dd": None,
            }
        )
