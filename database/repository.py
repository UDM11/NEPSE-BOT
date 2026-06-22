"""Database repository for CRUD operations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AuditLog,
    MarketSnapshot,
    Order,
    OrderStatus,
    PerformanceMetric,
    SystemEvent,
    TradeSignal,
)


class DatabaseRepository:
    """Async repository for all database operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_order(self, order: Order) -> Order:
        self.session.add(order)
        await self.session.commit()
        return order

    async def update_order(self, order_id: str, **kwargs: Any) -> Order | None:
        result = await self.session.execute(select(Order).where(Order.id == order_id))
        order = result.scalar_one_or_none()
        if order:
            for key, value in kwargs.items():
                setattr(order, key, value)
            await self.session.commit()
        return order

    async def get_order(self, order_id: str) -> Order | None:
        result = await self.session.execute(select(Order).where(Order.id == order_id))
        return result.scalar_one_or_none()

    async def get_recent_orders(self, limit: int = 50) -> list[Order]:
        result = await self.session.execute(
            select(Order).order_by(desc(Order.created_at)).limit(limit)
        )
        return list(result.scalars().all())

    async def get_orders_by_symbol_today(self, symbol: str) -> list[Order]:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        result = await self.session.execute(
            select(Order).where(Order.symbol == symbol, Order.created_at >= today)
        )
        return list(result.scalars().all())

    async def has_recent_duplicate_order(
        self, symbol: str, side: str, quantity: int, window_seconds: int
    ) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        result = await self.session.execute(
            select(func.count())
            .select_from(Order)
            .where(
                Order.symbol == symbol,
                Order.side == side,
                Order.quantity == quantity,
                Order.created_at >= cutoff,
                Order.status.in_([OrderStatus.PENDING, OrderStatus.SUBMITTED, OrderStatus.EXECUTED]),
            )
        )
        return (result.scalar() or 0) > 0

    async def create_signal(self, signal: TradeSignal) -> TradeSignal:
        self.session.add(signal)
        await self.session.commit()
        return signal

    async def save_market_snapshot(self, snapshot: MarketSnapshot) -> MarketSnapshot:
        self.session.add(snapshot)
        await self.session.commit()
        return snapshot

    async def save_performance_metric(
        self, metric_name: str, latency_ms: float, symbol: str | None = None, metadata: dict | None = None
    ) -> PerformanceMetric:
        metric = PerformanceMetric(
            metric_name=metric_name,
            latency_ms=latency_ms,
            symbol=symbol,
            metadata_json=metadata,
        )
        self.session.add(metric)
        await self.session.commit()
        return metric

    async def log_system_event(
        self, event_type: str, source: str, message: str | None = None, data: dict | None = None
    ) -> SystemEvent:
        event = SystemEvent(
            event_type=event_type,
            source=source,
            message=message,
            data_json=data,
        )
        self.session.add(event)
        await self.session.commit()
        return event

    async def log_audit(
        self,
        action: str,
        actor: str = "system",
        resource_type: str | None = None,
        resource_id: str | None = None,
        details: dict | None = None,
    ) -> AuditLog:
        log = AuditLog(
            action=action,
            actor=actor,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
        )
        self.session.add(log)
        await self.session.commit()
        return log

    async def get_daily_capital_used(self) -> float:
        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        result = await self.session.execute(
            select(func.coalesce(func.sum(Order.quantity * Order.price), 0.0)).where(
                Order.created_at >= today,
                Order.status.in_([OrderStatus.SUBMITTED, OrderStatus.EXECUTED, OrderStatus.PARTIAL]),
            )
        )
        return float(result.scalar() or 0)

    async def get_total_exposure(self) -> float:
        result = await self.session.execute(
            select(func.coalesce(func.sum(Order.quantity * Order.price), 0.0)).where(
                Order.status.in_([OrderStatus.SUBMITTED, OrderStatus.EXECUTED, OrderStatus.PARTIAL])
            )
        )
        return float(result.scalar() or 0)

    async def get_recent_signals(self, limit: int = 50) -> list[TradeSignal]:
        result = await self.session.execute(
            select(TradeSignal).order_by(desc(TradeSignal.created_at)).limit(limit)
        )
        return list(result.scalars().all())

    async def get_latency_stats(self, metric_name: str, hours: int = 24) -> dict:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = await self.session.execute(
            select(
                func.count(PerformanceMetric.id),
                func.min(PerformanceMetric.latency_ms),
                func.max(PerformanceMetric.latency_ms),
                func.avg(PerformanceMetric.latency_ms),
            ).where(
                PerformanceMetric.metric_name == metric_name,
                PerformanceMetric.recorded_at >= cutoff,
            )
        )
        row = result.one()
        return {
            "count": row[0] or 0,
            "min": row[1] or 0,
            "max": row[2] or 0,
            "mean": row[3] or 0,
        }
