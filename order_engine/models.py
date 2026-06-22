"""Order request and result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


@dataclass
class OrderRequest:
    """Validated order request ready for submission."""

    id: str = field(default_factory=lambda: str(uuid4()))
    symbol: str = ""
    side: str = "buy"
    order_type: str = "market"
    quantity: int = 0
    price: float | None = None
    strategy_name: str = ""
    signal_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "order_type": self.order_type,
            "quantity": self.quantity,
            "price": self.price,
            "strategy_name": self.strategy_name,
            "signal_id": self.signal_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class OrderResult:
    """Order execution result."""

    order_id: str
    success: bool
    status: str = "pending"
    broker_order_id: str | None = None
    message: str = ""
    latency_ms: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    executed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "order_id": self.order_id,
            "success": self.success,
            "status": self.status,
            "broker_order_id": self.broker_order_id,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
        }
