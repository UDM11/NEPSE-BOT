"""Order validation before submission."""

from __future__ import annotations

from core.config import get_app_config
from core.exceptions import OrderError
from core.logging_config import get_logger
from order_engine.models import OrderRequest
from strategies.base import Signal

logger = get_logger("order_validator")


def _is_buy_only() -> bool:
    return get_app_config().get("trading", {}).get("buy_only", True)


class OrderValidator:
    """Validate orders before submission to broker. Enforces buy-only mode."""

    VALID_TYPES = {"market", "limit"}

    @property
    def valid_sides(self) -> set[str]:
        if _is_buy_only():
            return {"buy"}
        return {"buy", "sell"}

    def validate_signal(self, signal: Signal) -> OrderRequest:
        """Convert and validate a trading signal into an order request."""
        errors = []

        if not signal.symbol:
            errors.append("Symbol is required")
        if signal.action not in self.valid_sides:
            if _is_buy_only():
                errors.append("Sell orders are disabled — this bot is buy-only")
            else:
                errors.append(f"Invalid side: {signal.action}")
        if signal.order_type not in self.VALID_TYPES:
            errors.append(f"Invalid order type: {signal.order_type}")
        if signal.quantity <= 0:
            errors.append(f"Invalid quantity: {signal.quantity}")
        if signal.order_type == "limit" and (signal.price is None or signal.price <= 0):
            errors.append("Limit orders require a valid price")

        if errors:
            raise OrderError("Order validation failed", {"errors": errors})

        return OrderRequest(
            symbol=signal.symbol.upper(),
            side="buy",  # always buy in buy-only mode
            order_type=signal.order_type,
            quantity=signal.quantity,
            price=signal.price,
            strategy_name=signal.strategy_name,
            signal_id=signal.id,
            metadata=signal.metadata,
        )

    def validate_request(self, request: OrderRequest) -> OrderRequest:
        """Re-validate an existing order request."""
        errors = []
        if not request.symbol:
            errors.append("Symbol is required")
        if request.side not in self.valid_sides:
            errors.append("Sell orders are disabled — this bot is buy-only")
        if request.quantity <= 0:
            errors.append("Quantity must be positive")
        if request.order_type == "limit" and not request.price:
            errors.append("Limit price required")
        if errors:
            raise OrderError("Order validation failed", {"errors": errors})
        return request
