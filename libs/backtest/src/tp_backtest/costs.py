"""Indian index-option cost stack, itemized per fill.

Statutory rates are law and apply at 1x in every scenario; the scenario
multiplier applies to SLIPPAGE only (see fills.py) — multiplying stamp duty
teaches you nothing about robustness, multiplying slippage does.

Rates effective for FY26 (versioned by date so historical backtests can use
historical rates when we extend the table):
  STT                 0.10%  of premium, SELL side only
  Exchange txn (NSE)  0.03503% of premium      (BSE Sensex options: 0.0325%)
  SEBI fees           0.0001% of premium (₹10/crore)
  Stamp duty          0.003% of premium, BUY side only
  GST                 18% on (brokerage + exchange + SEBI)
  Brokerage           ₹20 flat per order (Upstox)
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from tp_core.models import OrderSide

BROKERAGE_PER_ORDER = Decimal("20")
STT_SELL = Decimal("0.0010")
EXCH_TXN = {"NSE": Decimal("0.0003503"), "BSE": Decimal("0.000325")}
SEBI_FEES = Decimal("0.000001")
STAMP_BUY = Decimal("0.00003")
GST = Decimal("0.18")


@dataclass(frozen=True)
class CostBreakdown:
    brokerage: Decimal
    stt: Decimal
    exchange: Decimal
    sebi: Decimal
    stamp: Decimal
    gst: Decimal

    @property
    def total(self) -> Decimal:
        return self.brokerage + self.stt + self.exchange + self.sebi + self.stamp + self.gst

    def as_dict(self) -> dict[str, Decimal]:
        return {
            "brokerage": self.brokerage,
            "stt": self.stt,
            "exchange": self.exchange,
            "sebi": self.sebi,
            "stamp": self.stamp,
            "gst": self.gst,
        }


def option_trade_costs(
    side: OrderSide, premium_per_unit: Decimal, qty: int, exchange: str = "NSE"
) -> CostBreakdown:
    """Charges for one option fill. qty is units (lots x lot_size);
    premium notional = price x qty."""
    notional = premium_per_unit * qty
    stt = notional * STT_SELL if side is OrderSide.SELL else Decimal(0)
    exch = notional * EXCH_TXN[exchange]
    sebi = notional * SEBI_FEES
    stamp = notional * STAMP_BUY if side is OrderSide.BUY else Decimal(0)
    gst = (BROKERAGE_PER_ORDER + exch + sebi) * GST
    return CostBreakdown(
        brokerage=BROKERAGE_PER_ORDER,
        stt=stt.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        exchange=exch.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        sebi=sebi.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        stamp=stamp.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        gst=gst.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
    )
