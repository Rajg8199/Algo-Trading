"""SQLAlchemy 2.0 ORM models.

Hypertable conversion, compression and retention policies are TimescaleDB
DDL and live in alembic migrations — the ORM only describes relational shape.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map: ClassVar = {
        dict[str, Any]: JSONB,
        UUID: PG_UUID(as_uuid=True),
    }


class InstrumentRow(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("exchange", "underlying", "segment", "expiry", "strike", "option_type"),
        Index("ix_instruments_chain", "underlying", "expiry", "strike"),
    )

    instrument_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    upstox_key: Mapped[str] = mapped_column(String, unique=True)
    exchange: Mapped[str] = mapped_column(String(8))
    segment: Mapped[str] = mapped_column(String(8))
    underlying: Mapped[str] = mapped_column(String(16))
    expiry: Mapped[date | None] = mapped_column(Date)
    strike: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    option_type: Mapped[str | None] = mapped_column(String(2))
    lot_size: Mapped[int] = mapped_column(Integer, default=1)
    tick_size: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class EventRow(Base):
    __tablename__ = "events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    event_type: Mapped[str] = mapped_column(String(32), index=True)
    scheduled: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(String)
    extra: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)


class TickRow(Base):
    __tablename__ = "ticks"

    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.instrument_id"), primary_key=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    ltp: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    bid: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    ask: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    bid_qty: Mapped[int | None] = mapped_column(Integer)
    ask_qty: Mapped[int | None] = mapped_column(Integer)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    oi: Mapped[int | None] = mapped_column(BigInteger)


class OptionChainRow(Base):
    __tablename__ = "option_chain"

    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.instrument_id"), primary_key=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    ltp: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    bid: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    ask: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    bid_qty: Mapped[int | None] = mapped_column(Integer)
    ask_qty: Mapped[int | None] = mapped_column(Integer)
    volume: Mapped[int | None] = mapped_column(BigInteger)
    oi: Mapped[int | None] = mapped_column(BigInteger)
    oi_prev_day: Mapped[int | None] = mapped_column(BigInteger)
    iv: Mapped[float | None] = mapped_column(REAL)
    delta: Mapped[float | None] = mapped_column(REAL)
    gamma: Mapped[float | None] = mapped_column(REAL)
    theta: Mapped[float | None] = mapped_column(REAL)
    vega: Mapped[float | None] = mapped_column(REAL)
    spot: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))


class VolMetricsDailyRow(Base):
    __tablename__ = "vol_metrics_daily"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    underlying: Mapped[str] = mapped_column(String(16), primary_key=True)
    rv_cc_20d: Mapped[float | None] = mapped_column(REAL)
    rv_yz_20d: Mapped[float | None] = mapped_column(REAL)
    rv_intraday: Mapped[float | None] = mapped_column(REAL)
    rv_overnight: Mapped[float | None] = mapped_column(REAL)
    har_rv_forecast: Mapped[float | None] = mapped_column(REAL)
    atm_iv_w1: Mapped[float | None] = mapped_column(REAL)
    atm_iv_w2: Mapped[float | None] = mapped_column(REAL)
    atm_iv_m1: Mapped[float | None] = mapped_column(REAL)
    term_slope: Mapped[float | None] = mapped_column(REAL)
    skew_25d: Mapped[float | None] = mapped_column(REAL)
    vrp: Mapped[float | None] = mapped_column(REAL)
    vov_20d: Mapped[float | None] = mapped_column(REAL)
    india_vix: Mapped[float | None] = mapped_column(REAL)
    vix_percentile_1y: Mapped[float | None] = mapped_column(REAL)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class ParticipantOIRow(Base):
    __tablename__ = "participant_oi"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    participant: Mapped[str] = mapped_column(String(16), primary_key=True)
    instrument_class: Mapped[str] = mapped_column(String(16), primary_key=True)
    long_contracts: Mapped[int | None] = mapped_column(BigInteger)
    short_contracts: Mapped[int | None] = mapped_column(BigInteger)


class FuturesBasisDailyRow(Base):
    __tablename__ = "futures_basis_daily"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    underlying: Mapped[str] = mapped_column(String(16), primary_key=True)
    spot: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    fut_near: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    basis_pct: Mapped[float | None] = mapped_column(REAL)
    basis_percentile_1y: Mapped[float | None] = mapped_column(REAL)
    days_to_expiry: Mapped[int | None] = mapped_column(Integer)


class OrderRow(Base):
    __tablename__ = "orders"
    __table_args__ = (Index("ix_orders_strategy_created", "strategy", "created_at"),)

    order_id: Mapped[UUID] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(8))
    strategy: Mapped[str] = mapped_column(String(64))
    instrument_id: Mapped[int] = mapped_column(ForeignKey("instruments.instrument_id"))
    side: Mapped[str] = mapped_column(String(4))
    order_type: Mapped[str] = mapped_column(String(8))
    qty: Mapped[int] = mapped_column(Integer)
    limit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    status: Mapped[str] = mapped_column(String(16))
    reject_reason: Mapped[str | None] = mapped_column(String)
    signal_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FillRow(Base):
    __tablename__ = "fills"

    fill_id: Mapped[UUID] = mapped_column(primary_key=True)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("orders.order_id"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    qty: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    slippage: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    costs: Mapped[dict[str, Any]] = mapped_column(JSONB)


class PositionRow(Base):
    __tablename__ = "positions"

    mode: Mapped[str] = mapped_column(String(8), primary_key=True)
    strategy: Mapped[str] = mapped_column(String(64), primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.instrument_id"), primary_key=True
    )
    qty: Mapped[int] = mapped_column(Integer)
    avg_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PnlDailyRow(Base):
    __tablename__ = "pnl_daily"

    trade_date: Mapped[date] = mapped_column(Date, primary_key=True)
    mode: Mapped[str] = mapped_column(String(8), primary_key=True)
    strategy: Mapped[str] = mapped_column(String(64), primary_key=True)
    gross_pnl: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    costs: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    net_pnl: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    n_trades: Mapped[int | None] = mapped_column(Integer)
    max_intraday_dd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))


class ExperimentRow(Base):
    """Research registry: every research/backtest run is one row, MLflow-style."""

    __tablename__ = "experiments"
    __table_args__ = (Index("ix_experiments_hypothesis", "hypothesis", "created_at"),)

    run_id: Mapped[UUID] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # RESEARCH | BACKTEST
    strategy: Mapped[str | None] = mapped_column(String(64))
    hypothesis: Mapped[str] = mapped_column(String(64))
    params: Mapped[dict[str, Any]] = mapped_column(JSONB)
    data_range_start: Mapped[date | None] = mapped_column(Date)
    data_range_end: Mapped[date | None] = mapped_column(Date)
    cost_multiplier: Mapped[float | None] = mapped_column(REAL)
    git_sha: Mapped[str] = mapped_column(String(40))
    feature_set_version: Mapped[str | None] = mapped_column(String(64))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    artifacts_path: Mapped[str | None] = mapped_column(String)  # datalake/backtests/...
    trial_number: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class FeatureValueRow(Base):
    """Feature store (offline). Every feature value is keyed by its definition
    version so research results are reproducible bit-for-bit."""

    __tablename__ = "feature_values"

    feature_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    feature_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    entity: Mapped[str] = mapped_column(String(32), primary_key=True)  # e.g. NIFTY
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    value: Mapped[float | None] = mapped_column(REAL)
    extra: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class DataGapRow(Base):
    __tablename__ = "data_gaps"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32))
    gap_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    gap_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)


class DQCheckRow(Base):
    __tablename__ = "dq_checks"

    check_date: Mapped[date] = mapped_column(Date, primary_key=True)
    check_name: Mapped[str] = mapped_column(String(64), primary_key=True)
    passed: Mapped[bool] = mapped_column(Boolean)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AuthTokenRow(Base):
    """Broker tokens. One row per provider; updated on each re-auth."""

    __tablename__ = "auth_tokens"

    provider: Mapped[str] = mapped_column(String(16), primary_key=True)
    access_token: Mapped[str] = mapped_column(String)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
