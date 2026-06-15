"""Format a per-index options market-structure digest from feature-store values.

Pure and defensive: each line is emitted only when the feature(s) it needs are
present, so an index with partial or no data degrades cleanly to "awaiting data"
rather than printing zeros or guesses.
"""

from __future__ import annotations

from datetime import date, datetime

from tp_research.options.live import LiveOptionsSnapshot

OPTIONS_UNDERLYINGS = ("NIFTY", "SENSEX", "BANKNIFTY")

_FOOTER = "📊 Market-structure snapshot — informational, NOT a trading signal."


def _index_block(name: str, f: dict[str, float], as_of: date | None) -> str:
    if not f:
        return f"*{name}* — awaiting data (chain not yet ingested for this index)"

    lines = [f"*{name}*" + (f"  ·  {as_of:%d %b}" if as_of else "")]

    iv_front = f.get("atm_iv_front")
    iv_next = f.get("atm_iv_next")
    if iv_front is not None:
        tail = f" · next {iv_next:.1f}%" if iv_next is not None else ""
        lines.append(f"  ATM IV  {iv_front:.1f}%{tail}")

    pctile = f.get("iv_percentile_1y")
    rank = f.get("iv_rank_1y")
    if pctile is not None or rank is not None:
        parts = []
        if pctile is not None:
            parts.append(f"pctile {pctile:.0f}")
        if rank is not None:
            parts.append(f"rank {rank:.0f}")
        lines.append("  IV 1y  " + " · ".join(parts))

    slope = f.get("term_slope")
    if slope is not None:
        shape = "contango" if slope >= 0 else "backwardation"
        lines.append(f"  Term slope  {slope:+.2f} ({shape})")

    put_sk = f.get("put_skew_25d")
    call_sk = f.get("call_skew_25d")
    if put_sk is not None or call_sk is not None:
        p = f"put {put_sk:.1f}" if put_sk is not None else "put —"
        c = f"call {call_sk:.1f}" if call_sk is not None else "call —"
        lines.append(f"  25Δ skew  {p} / {c}")

    vov = f.get("vov_20d")
    if vov is not None:
        lines.append(f"  Vol-of-vol  {vov:.2f}")

    rv = f.get("rv_yz_20d")
    if rv is not None:
        vrp = f" → VRP {iv_front - rv:+.1f}" if iv_front is not None else ""
        lines.append(f"  RV (YZ 20d)  {rv:.1f}%{vrp}")

    oi = f.get("oi_total_front")
    oi_chg = f.get("oi_change_1d")
    if oi is not None:
        chg = f"  (Δ1d {oi_chg:+,.0f})" if oi_chg is not None else ""
        lines.append(f"  OI front  {oi:,.0f}{chg}")

    if len(lines) == 1:  # header only — had the entity but no recognised fields
        lines.append("  (no recognised structure fields)")
    return "\n".join(lines)


def format_options_digest(
    per_underlying: dict[str, tuple[dict[str, float], date | None]],
    underlyings: tuple[str, ...] = OPTIONS_UNDERLYINGS,
) -> str:
    """`per_underlying[name] = (feature_values, as_of_date)`. Builds one
    Telegram message; missing indices show 'awaiting data'."""
    header = "🧭 Index options — IV & structure"
    blocks = []
    for name in underlyings:
        values, as_of = per_underlying.get(name, ({}, None))
        blocks.append(_index_block(name, values, as_of))
    return f"{header}\n\n" + "\n\n".join(blocks) + f"\n\n{_FOOTER}"


def _live_block(name: str, snap: LiveOptionsSnapshot | None) -> str:
    if snap is None:
        return f"*{name}* — no live snapshot (market closed or not subscribed)"
    parts = [f"*{name}*  spot {snap.spot:,.0f}"]
    line = []
    if snap.atm_iv is not None:
        line.append(f"ATM IV {snap.atm_iv:.1f}%")
    if snap.atm_straddle is not None:
        line.append(f"straddle {snap.atm_straddle:,.0f}")
    if snap.pcr_oi is not None:
        line.append(f"PCR {snap.pcr_oi:.2f}")
    if line:
        parts.append("  " + "  ·  ".join(line))
    return "\n".join(parts)


def format_live_options(
    snapshots: dict[str, LiveOptionsSnapshot | None],
    india_vix: float | None,
    now: datetime,
    underlyings: tuple[str, ...] = OPTIONS_UNDERLYINGS,
) -> str:
    """Intraday options snapshot from live recorded chains. Informational."""
    header = f"⚡ Live options · {now:%H:%M} IST"
    blocks = [_live_block(name, snapshots.get(name)) for name in underlyings]
    vix = f"\n\nIndia VIX  {india_vix:.2f}" if india_vix is not None else ""
    return f"{header}\n\n" + "\n\n".join(blocks) + vix + f"\n\n{_FOOTER}"
