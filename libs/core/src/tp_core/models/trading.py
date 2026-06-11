from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from tp_core.models.enums import OrderSide, OrderStatus, OrderType, TradingMode


class OrderIntent(BaseModel):
    """What a strategy emits. The risk layer turns intents into orders (or rejections).

    signal_snapshot carries the full signal state at decision time so every
    order is auditable and every backtest/paper divergence is explainable.
    """

    model_config = ConfigDict(frozen=True)

    intent_id: UUID = Field(default_factory=uuid4)
    strategy: str
    mode: TradingMode
    instrument_id: int
    side: OrderSide
    order_type: OrderType
    qty: int = Field(gt=0)
    limit_price: Decimal | None = None
    signal_snapshot: dict[str, Any] = Field(default_factory=dict)


class Fill(BaseModel):
    model_config = ConfigDict(frozen=True)

    fill_id: UUID = Field(default_factory=uuid4)
    order_id: UUID
    ts: datetime
    qty: int
    price: Decimal
    slippage: Decimal | None = None
    costs: dict[str, Decimal] = Field(default_factory=dict)


class Position(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: TradingMode
    strategy: str
    instrument_id: int
    qty: int
    avg_price: Decimal | None = None
    realized_pnl: Decimal = Decimal(0)
    updated_at: datetime | None = None


class Order(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: UUID = Field(default_factory=uuid4)
    mode: TradingMode
    strategy: str
    instrument_id: int
    side: OrderSide
    order_type: OrderType
    qty: int
    limit_price: Decimal | None = None
    status: OrderStatus = OrderStatus.PENDING_RISK
    reject_reason: str | None = None
    signal_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
