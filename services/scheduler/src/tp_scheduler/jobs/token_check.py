"""Pre-market token job: validate the Upstox token; if invalid, send the
login link to Telegram so the user can re-auth in one tap."""

from tp_core.models import Severity
from tp_core.telemetry.logging import get_logger
from tp_scheduler.context import JobContext

log = get_logger(__name__)


async def run(ctx: JobContext) -> None:
    if await ctx.auth.is_token_valid():
        log.info("token_valid")
        return
    login_url = ctx.auth.login_url()
    await ctx.alert(
        Severity.P1,
        "token_invalid",
        f"Upstox token invalid/expired. Re-authenticate now:\n{login_url}",
    )
    log.warning("token_invalid_alert_sent")
