"""Event-driven architecture for decoupled module communication."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Coroutine
from uuid import uuid4


class EventType(str, Enum):
    """System event types."""

    MARKET_DATA_UPDATE = "market_data.update"
    CIRCUIT_HIT = "market_data.circuit_hit"
    STRATEGY_SIGNAL = "strategy.signal"
    RISK_APPROVED = "risk.approved"
    RISK_REJECTED = "risk.rejected"
    ORDER_SUBMITTED = "order.submitted"
    ORDER_EXECUTED = "order.executed"
    ORDER_FAILED = "order.failed"
    ORDER_DUPLICATE_BLOCKED = "order.duplicate_blocked"
    LOGIN_SUCCESS = "broker.login_success"
    LOGIN_FAILURE = "broker.login_failure"
    SESSION_EXPIRED = "broker.session_expired"
    CAPTCHA_DETECTED = "broker.captcha_detected"
    KILL_SWITCH_ACTIVATED = "risk.kill_switch"
    SYSTEM_ERROR = "system.error"
    SYSTEM_RESTART = "system.restart"
    METRICS_REPORT = "metrics.report"


@dataclass
class Event:
    """Immutable event payload."""

    type: EventType
    data: dict[str, Any]
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "system"

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.type.value,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "data": self.data,
        }


EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """Async publish-subscribe event bus."""

    def __init__(self) -> None:
        self._handlers: dict[EventType, list[EventHandler]] = {}
        self._wildcard_handlers: list[EventHandler] = []
        self._history: list[Event] = []
        self._max_history = 1000
        self._lock = asyncio.Lock()

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Register handler for specific event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Unsubscribe handler from specific event type."""
        if event_type in self._handlers:
            try:
                self._handlers[event_type].remove(handler)
            except ValueError:
                pass

    def unsubscribe_all(self, handler: EventHandler) -> None:
        """Unsubscribe handler from all event types and wildcard list."""
        if handler in self._wildcard_handlers:
            try:
                self._wildcard_handlers.remove(handler)
            except ValueError:
                pass
        for event_type in list(self._handlers.keys()):
            if handler in self._handlers[event_type]:
                try:
                    self._handlers[event_type].remove(handler)
                except ValueError:
                    pass

    def subscribe_all(self, handler: EventHandler) -> None:
        """Register handler for all events."""
        self._wildcard_handlers.append(handler)

    async def publish(self, event: Event) -> None:
        """Publish event to all registered handlers."""
        async with self._lock:
            self._history.append(event)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history :]

        handlers = list(self._wildcard_handlers)
        handlers.extend(self._handlers.get(event.type, []))

        await asyncio.gather(
            *[self._safe_call(handler, event) for handler in handlers],
            return_exceptions=True,
        )

    async def _safe_call(self, handler: EventHandler, event: Event) -> None:
        try:
            await handler(event)
        except Exception as exc:
            # Avoid recursive error publishing
            import structlog

            structlog.get_logger().error(
                "event_handler_error",
                event_type=event.type.value,
                error=str(exc),
            )

    def get_recent_events(self, limit: int = 100) -> list[Event]:
        return self._history[-limit:]
