"""SQLAlchemy ORM models."""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    EXECUTED = "executed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    FAILED = "failed"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    side: Mapped[str] = mapped_column(String(10))
    order_type: Mapped[str] = mapped_column(String(10))
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.PENDING)
    broker_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    strategy_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    signal_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    __table_args__ = (Index("ix_orders_symbol_created", "symbol", "created_at"),)


class TradeSignal(Base):
    __tablename__ = "trade_signals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    strategy_name: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(10))
    trigger_price: Mapped[float] = mapped_column(Float)
    upper_circuit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bid_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ask_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    volume: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    conditions_met: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MarketSnapshot(Base):
    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    ltp: Mapped[float] = mapped_column(Float)
    bid_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ask_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    bid_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ask_quantity: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    volume: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    upper_circuit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lower_circuit: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    market_depth: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    __table_args__ = (Index("ix_snapshots_symbol_time", "symbol", "captured_at"),)


class PerformanceMetric(Base):
    __tablename__ = "performance_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_name: Mapped[str] = mapped_column(String(100), index=True)
    latency_ms: Mapped[float] = mapped_column(Float)
    symbol: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class SystemEvent(Base):
    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    source: Mapped[str] = mapped_column(String(100))
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    action: Mapped[str] = mapped_column(String(100), index=True)
    actor: Mapped[str] = mapped_column(String(100), default="system")
    resource_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
