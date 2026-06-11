"""Read endpoints for positions / PnL / risk. Paper-mode data for now; the
same endpoints serve live mode later via the mode parameter."""

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select, text

from tp_api.deps import AppState, get_state
from tp_core.db.orm import PnlDailyRow, PositionRow

router = APIRouter(prefix="/api/v1")

State = Annotated[AppState, Depends(get_state)]


@router.get("/positions")
async def positions(state: State, mode: str = "PAPER") -> list[dict[str, Any]]:
    async with state.db.session() as s:
        rows = (
            await s.execute(
                select(PositionRow).where(PositionRow.mode == mode, PositionRow.qty != 0)
            )
        ).scalars()
        return [
            {
                "strategy": r.strategy,
                "instrument_id": r.instrument_id,
                "qty": r.qty,
                "avg_price": float(r.avg_price) if r.avg_price is not None else None,
                "realized_pnl": float(r.realized_pnl),
            }
            for r in rows
        ]


@router.get("/pnl")
async def pnl(state: State, mode: str = "PAPER", days: int = 30) -> list[dict[str, Any]]:
    async with state.db.session() as s:
        rows = (
            await s.execute(
                select(PnlDailyRow)
                .where(PnlDailyRow.mode == mode)
                .order_by(PnlDailyRow.trade_date.desc())
                .limit(days)
            )
        ).scalars()
        return [
            {
                "trade_date": r.trade_date.isoformat(),
                "strategy": r.strategy,
                "gross_pnl": float(r.gross_pnl) if r.gross_pnl is not None else None,
                "net_pnl": float(r.net_pnl) if r.net_pnl is not None else None,
                "n_trades": r.n_trades,
            }
            for r in rows
        ]


@router.get("/risk")
async def risk(state: State) -> dict[str, Any]:
    """Risk snapshot. Greeks aggregation arrives with the paper engine;
    until then this reports exposure counts so /risk never lies."""
    async with state.db.session() as s:
        open_positions, today_pnl = (
            await s.execute(
                text("""
                SELECT
                  (SELECT count(*) FROM positions WHERE qty != 0),
                  (SELECT coalesce(sum(net_pnl), 0) FROM pnl_daily WHERE trade_date = :today)
            """),
                {"today": date.today()},  # noqa: DTZ011
            )
        ).one()
    return {"open_positions": open_positions, "today_net_pnl": float(today_pnl)}
