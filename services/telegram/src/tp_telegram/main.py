"""Telegram service entrypoint: alert router + command bot + health server."""

import asyncio

from aiogram import Bot, Dispatcher

from tp_core.config import get_settings
from tp_core.redis import AlertQueue, RedisBus
from tp_core.telemetry import HealthState, configure_logging, get_logger, serve_health
from tp_telegram.alert_router import AlertRouter
from tp_telegram.commands import register

log = get_logger(__name__)


async def main() -> None:
    settings = get_settings()
    configure_logging("telegram", settings.log_level)

    bot = Bot(token=settings.telegram_bot_token.get_secret_value())
    dispatcher = Dispatcher()
    dispatcher.include_router(register(settings.telegram_allowed_chat_id))

    bus = RedisBus(settings)
    alert_router = AlertRouter(bot, settings.telegram_allowed_chat_id, AlertQueue(bus))

    health = HealthState(service="telegram")
    health.set_ready("redis", await bus.ping())
    health.set_ready("bot", True)

    try:
        async with asyncio.TaskGroup() as tg:
            tg.create_task(alert_router.run(), name="alerts")
            tg.create_task(dispatcher.start_polling(bot), name="commands")
            tg.create_task(serve_health(health, settings.telegram_health_port), name="health")
    finally:
        await bus.close()
        await bot.session.close()


def cli() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    cli()
