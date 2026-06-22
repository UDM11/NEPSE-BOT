"""Risk management with capital limits, kill switch, and failure detection."""

from __future__ import annotations

from dataclasses import dataclass, field

from core.config import get_app_config, get_settings
from core.events import Event, EventBus, EventType
from core.exceptions import RiskLimitError
from core.logging_config import get_logger
from database.repository import DatabaseRepository
from strategies.base import Signal

logger = get_logger("risk_manager")


@dataclass
class RiskState:
    """Current risk management state."""

    kill_switch_active: bool = False
    consecutive_failures: int = 0
    daily_capital_used: float = 0.0
    total_exposure: float = 0.0
    orders_today: dict[str, int] = field(default_factory=dict)
    last_check: float = 0.0


class RiskManager:
    """
    Pre-trade risk checks:
    - Daily capital limits
    - Maximum quantity per order
    - Maximum exposure
    - Emergency kill switch
    - Consecutive failure detection
    - Duplicate order detection
    - Session expiry awareness
    """

    def __init__(self, event_bus: EventBus, db_repo: DatabaseRepository | None = None):
        self.event_bus = event_bus
        self.db_repo = db_repo
        self.state = RiskState()
        settings = get_settings()
        app_config = get_app_config()
        risk_config = app_config.get("risk", {})

        self.daily_capital_limit = risk_config.get(
            "daily_capital_limit", settings.risk_daily_capital_limit
        )
        self.max_quantity = risk_config.get(
            "max_quantity_per_order", settings.risk_max_quantity_per_order
        )
        self.max_exposure = risk_config.get("max_exposure", settings.risk_max_exposure)
        self.max_orders_per_symbol = risk_config.get("max_orders_per_symbol_per_day", 3)
        self.max_consecutive_failures = risk_config.get(
            "max_consecutive_failures", settings.risk_max_consecutive_failures
        )
        self.duplicate_window = risk_config.get("duplicate_order_window_seconds", 30)

        if settings.risk_kill_switch or risk_config.get("kill_switch"):
            self.state.kill_switch_active = True

    async def check_signal(self, signal: Signal) -> tuple[bool, str]:
        """
        Validate signal against all risk rules.
        Returns (approved, reason).
        """
        if self.state.kill_switch_active:
            return False, "Kill switch is active"

        if self.state.consecutive_failures >= self.max_consecutive_failures:
            self.activate_kill_switch("Max consecutive failures reached")
            return False, "Kill switch activated due to consecutive failures"

        # Quantity check
        if signal.quantity <= 0:
            return False, "Invalid quantity: must be > 0"
        if signal.quantity > self.max_quantity:
            return False, f"Quantity {signal.quantity} exceeds max {self.max_quantity}"

        # Capital limit check
        order_value = signal.quantity * (signal.price or signal.trigger_price)
        if self.db_repo:
            self.state.daily_capital_used = await self.db_repo.get_daily_capital_used()
            self.state.total_exposure = await self.db_repo.get_total_exposure()

        if self.state.daily_capital_used + order_value > self.daily_capital_limit:
            return False, (
                f"Daily capital limit exceeded: "
                f"{self.state.daily_capital_used + order_value:.2f} > {self.daily_capital_limit}"
            )

        if self.state.total_exposure + order_value > self.max_exposure:
            return False, (
                f"Max exposure exceeded: "
                f"{self.state.total_exposure + order_value:.2f} > {self.max_exposure}"
            )

        # Per-symbol daily order limit
        symbol_orders = self.state.orders_today.get(signal.symbol, 0)
        if symbol_orders >= self.max_orders_per_symbol:
            return False, f"Max orders per symbol reached: {symbol_orders}/{self.max_orders_per_symbol}"

        # Duplicate order detection
        if self.db_repo:
            is_duplicate = await self.db_repo.has_recent_duplicate_order(
                signal.symbol, signal.action, signal.quantity, self.duplicate_window
            )
            if is_duplicate:
                await self.event_bus.publish(
                    Event(
                        type=EventType.ORDER_DUPLICATE_BLOCKED,
                        source="risk_manager",
                        data={"symbol": signal.symbol, "quantity": signal.quantity},
                    )
                )
                return False, "Duplicate order blocked within time window"

        return True, "Approved"

    async def approve_signal(self, signal: Signal) -> Signal:
        """Run risk checks and raise on rejection."""
        approved, reason = await self.check_signal(signal)
        if not approved:
            logger.warning("risk_rejected", symbol=signal.symbol, reason=reason)
            await self.event_bus.publish(
                Event(
                    type=EventType.RISK_REJECTED,
                    source="risk_manager",
                    data={"signal": signal.to_dict(), "reason": reason},
                )
            )
            raise RiskLimitError(reason, {"signal": signal.to_dict()})

        self.state.orders_today[signal.symbol] = (
            self.state.orders_today.get(signal.symbol, 0) + 1
        )
        logger.info("risk_approved", symbol=signal.symbol, quantity=signal.quantity)
        await self.event_bus.publish(
            Event(
                type=EventType.RISK_APPROVED,
                source="risk_manager",
                data=signal.to_dict(),
            )
        )
        return signal

    def record_failure(self) -> None:
        """Increment consecutive failure counter."""
        self.state.consecutive_failures += 1
        logger.warning(
            "consecutive_failure",
            count=self.state.consecutive_failures,
            max=self.max_consecutive_failures,
        )
        if self.state.consecutive_failures >= self.max_consecutive_failures:
            self.activate_kill_switch("Max consecutive failures reached")

    def record_success(self) -> None:
        """Reset consecutive failure counter on success."""
        self.state.consecutive_failures = 0

    def activate_kill_switch(self, reason: str) -> None:
        """Activate emergency kill switch."""
        self.state.kill_switch_active = True
        logger.critical("kill_switch_activated", reason=reason)
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self.event_bus.publish(
                    Event(
                        type=EventType.KILL_SWITCH_ACTIVATED,
                        source="risk_manager",
                        data={"reason": reason},
                    )
                )
            )
        except RuntimeError:
            pass

    def deactivate_kill_switch(self) -> None:
        """Manually deactivate kill switch (requires operator action)."""
        self.state.kill_switch_active = False
        self.state.consecutive_failures = 0
        logger.info("kill_switch_deactivated")

    def get_status(self) -> dict:
        return {
            "kill_switch_active": self.state.kill_switch_active,
            "consecutive_failures": self.state.consecutive_failures,
            "daily_capital_used": self.state.daily_capital_used,
            "daily_capital_limit": self.daily_capital_limit,
            "total_exposure": self.state.total_exposure,
            "max_exposure": self.max_exposure,
            "orders_today": dict(self.state.orders_today),
        }
