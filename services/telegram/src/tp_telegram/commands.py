"""Read-only Telegram commands. Handlers query the internal API so command
logic lives in exactly one place (the API), and the bot stays thin.

Order-affecting commands are deliberately absent until the live phase.
"""

from typing import Any

import httpx
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router()

API_BASE = "http://api:8000"


def allowed(message: Message, chat_id: int) -> bool:
    return message.chat.id == chat_id


async def _get(path: str) -> Any:
    async with httpx.AsyncClient(base_url=API_BASE, timeout=10) as client:
        response = await client.get(path)
        response.raise_for_status()
        return response.json()


def register(allowed_chat_id: int) -> Router:
    @router.message(Command("status"))
    async def status(message: Message) -> None:
        if not allowed(message, allowed_chat_id):
            return
        data = await _get("/api/v1/status")
        await message.answer(
            "📊 Status\n"
            f"Last tick: {data['last_tick']}\n"
            f"Last chain snapshot: {data['last_chain_snapshot']}\n"
            f"Ticks (5m): {data['ticks_last_5m']} · Chain rows (5m): {data['chain_rows_last_5m']}\n"
            f"Open data gaps: {data['open_data_gaps']}\n"
            f"Upstox token: {data['upstox_token']}"
        )

    @router.message(Command("health"))
    async def health(message: Message) -> None:
        if not allowed(message, allowed_chat_id):
            return
        data = await _get("/ready")
        components = " · ".join(
            f"{name} {'✓' if ok else '✗'}" for name, ok in data["components"].items()
        )
        await message.answer(f"{'🟢' if data['ready'] else '🔴'} {components}")

    @router.message(Command("positions"))
    async def positions(message: Message) -> None:
        if not allowed(message, allowed_chat_id):
            return
        rows = await _get("/api/v1/positions")
        if not rows:
            await message.answer("No open positions.")
            return
        lines = "\n".join(
            f"• {r['strategy']} #{r['instrument_id']} qty {r['qty']} @ {r['avg_price']}"
            for r in rows[:30]
        )
        await message.answer(f"📦 Positions\n{lines}")

    @router.message(Command("pnl"))
    async def pnl(message: Message) -> None:
        if not allowed(message, allowed_chat_id):
            return
        rows = await _get("/api/v1/pnl")
        if not rows:
            await message.answer("No PnL recorded yet.")
            return
        lines = "\n".join(
            f"• {r['trade_date']} {r['strategy']}: ₹{r['net_pnl']}" for r in rows[:15]
        )
        await message.answer(f"💰 PnL (recent)\n{lines}")

    @router.message(Command("risk"))
    async def risk(message: Message) -> None:
        if not allowed(message, allowed_chat_id):
            return
        data = await _get("/api/v1/risk")
        await message.answer(
            f"🛡 Risk\nOpen positions: {data['open_positions']}\n"
            f"Today net PnL: ₹{data['today_net_pnl']}"
        )

    return router
