"""EOD downloads from NSE: participant-wise OI. Retried hourly by the
scheduler until success or the retry window closes."""

import csv
import io
from datetime import date

import httpx
from sqlalchemy.dialects.postgresql import insert as pg_insert

from tp_core.db.orm import ParticipantOIRow
from tp_core.models import Severity
from tp_core.telemetry.logging import get_logger
from tp_scheduler.context import JobContext

log = get_logger(__name__)

PARTICIPANT_OI_URL = (
    "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_{ddmmyyyy}.csv"
)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
    "Accept": "text/csv,*/*",
}

PARTICIPANTS = {"Client", "DII", "FII", "Pro"}


async def run(ctx: JobContext, for_date: date | None = None) -> None:
    target = for_date or date.today()  # noqa: DTZ011 — IST host clock by deployment contract
    url = PARTICIPANT_OI_URL.format(ddmmyyyy=target.strftime("%d%m%Y"))
    async with httpx.AsyncClient(timeout=30, headers=HEADERS, follow_redirects=True) as client:
        response = await client.get(url)
    if response.status_code == 404:
        log.info("participant_oi_not_published_yet", date=target.isoformat())
        raise FileNotFoundError(url)  # scheduler retry handles it
    response.raise_for_status()

    rows = _parse(response.text, target)
    if not rows:
        await ctx.alert(
            Severity.P2, "participant_oi_empty", f"Participant OI parse empty for {target}"
        )
        return
    stmt = pg_insert(ParticipantOIRow).values(rows)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["trade_date", "participant", "instrument_class"]
    )
    async with ctx.db.session() as s:
        await s.execute(stmt)
    log.info("participant_oi_ingested", date=target.isoformat(), rows=len(rows))


def _parse(text: str, target: date) -> list[dict[str, object]]:
    """The file has a banner line, then a header, then one row per participant.
    Columns include long/short contracts for index futures/calls/puts."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    reader = csv.reader(io.StringIO("\n".join(lines[1:])))  # drop banner
    header = [h.strip() for h in next(reader)]
    idx = {name: i for i, name in enumerate(header)}

    wanted = {
        "IDX_FUT": ("Future Index Long", "Future Index Short"),
        "IDX_OPT_CALL": ("Option Index Call Long", "Option Index Call Short"),
        "IDX_OPT_PUT": ("Option Index Put Long", "Option Index Put Short"),
    }
    out: list[dict[str, object]] = []
    for row in reader:
        participant = row[idx.get("Client Type", 0)].strip()
        if participant not in PARTICIPANTS:
            continue
        for instrument_class, (long_col, short_col) in wanted.items():
            if long_col not in idx or short_col not in idx:
                continue
            out.append(
                {
                    "trade_date": target,
                    "participant": participant.upper(),
                    "instrument_class": instrument_class,
                    "long_contracts": int(float(row[idx[long_col]] or 0)),
                    "short_contracts": int(float(row[idx[short_col]] or 0)),
                }
            )
    return out
