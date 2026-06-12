from datetime import date

from tp_research.chain import ChainClose, ChainRowLite, atm_iv, iv_at_delta, skew_metrics


def make_chain(spot: float = 24500.0) -> ChainClose:
    rows: list[ChainRowLite] = []
    # Symmetric smile: ATM IV 14, +0.8 per 100 points away, both legs present
    for strike in range(24000, 25001, 100):
        distance = abs(strike - spot) / 100
        iv = 14.0 + 0.8 * distance
        for opt, delta in (("CE", 0.5 - distance * 0.08), ("PE", -(0.5 - distance * 0.08))):
            rows.append(
                ChainRowLite(strike=float(strike), option_type=opt, iv=iv, delta=delta, oi=1000.0)
            )
    return ChainClose("NIFTY", date(2026, 6, 16), spot, rows)


def test_atm_iv_picks_nearest_strike_pair() -> None:
    assert atm_iv(make_chain()) == 14.0


def test_atm_iv_requires_both_legs() -> None:
    chain = make_chain()
    one_legged = ChainClose(
        chain.underlying,
        chain.expiry,
        chain.spot,
        [r for r in chain.rows if r.option_type == "CE"],
    )
    assert atm_iv(one_legged) is None


def test_iv_at_delta_finds_25d() -> None:
    # delta 0.25 -> ~3 strikes from ATM -> iv ~14 + 0.8*3 = 16.4 (grid snaps)
    iv = iv_at_delta(make_chain(), "PE", 0.25)
    assert iv is not None
    assert 15.5 < iv < 17.5


def test_skew_metrics_symmetric_smile() -> None:
    metrics = skew_metrics(make_chain())
    put_skew, call_skew = metrics["put_skew_25d"], metrics["call_skew_25d"]
    curvature = metrics["smile_curvature"]
    assert put_skew is not None and call_skew is not None and curvature is not None
    # Symmetric smile: put and call skew equal, curvature positive
    assert abs(put_skew - call_skew) < 1e-6
    assert curvature > 0


def test_garbage_iv_excluded() -> None:
    chain = make_chain()
    for row in chain.rows:
        if row.strike == 24500.0:
            row.iv = 900.0  # corrupt the ATM pair
    # ATM falls back to the next nearest valid strike pair
    value = atm_iv(chain)
    assert value is not None
    assert 14.0 < value < 15.0
