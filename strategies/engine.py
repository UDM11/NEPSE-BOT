"""Strategy evaluation engine."""

from __future__ import annotations

import time

from core.config import PROJECT_ROOT, load_yaml_config
from core.events import Event, EventBus, EventType
from core.logging_config import get_logger
from core.metrics import metrics
from market_data.models import MarketTick
from strategies.base import BaseStrategy, Signal, StrategyRegistry
from strategies.upper_circuit import UpperCircuitBreakoutStrategy  # noqa: F401 - registers strategy
from strategies.ipo_daily_circuit import IpoDailyCircuitStrategy  # noqa: F401 - registers strategy

logger = get_logger("strategy_engine")


class StrategyEngine:
    """
    Configurable strategy framework.

    Loads strategies from YAML, evaluates ticks, and publishes signals.
    """

    def __init__(self, event_bus: EventBus, config_path: str | None = None):
        self.event_bus = event_bus
        self.config_path = config_path or PROJECT_ROOT / "config" / "strategies.yaml"
        self._strategies: dict[str, BaseStrategy] = {}
        self._quantity_profiles: dict = {}
        self._symbol_strategy_map: dict[str, str] = {}
        self._signal_cooldown: dict[str, float] = {}
        self._cooldown_seconds = 5.0

    def load(self) -> None:
        """Load strategies and quantity profiles from YAML."""
        config = load_yaml_config(self.config_path)
        self._quantity_profiles = config.get("quantity_profiles", {})

        for name, strategy_config in config.get("strategies", {}).items():
            strategy_config["name"] = name
            try:
                self._strategies[name] = StrategyRegistry.create(name, strategy_config)
                logger.info("strategy_loaded", name=name, enabled=strategy_config.get("enabled"))
            except ValueError:
                logger.warning("strategy_not_registered", name=name)

        # Map symbols to strategies from watchlist
        watchlist = load_yaml_config(PROJECT_ROOT / "config" / "watchlist.yaml")
        for entry in watchlist.get("symbols", []):
            if entry.get("enabled", True):
                self._symbol_strategy_map[entry["symbol"].upper()] = entry.get(
                    "strategy", "ipo_daily_circuit"
                )

    async def evaluate_tick(self, tick: MarketTick) -> Signal | None:
        """Evaluate tick against assigned strategy."""
        strategy_name = self._symbol_strategy_map.get(
            tick.symbol, "ipo_daily_circuit"
        )
        strategy = self._strategies.get(strategy_name)
        if not strategy or not strategy.enabled:
            return None

        # Cooldown to prevent signal spam
        cooldown_key = f"{tick.symbol}:{strategy_name}"
        now = time.monotonic()
        if cooldown_key in self._signal_cooldown:
            if now - self._signal_cooldown[cooldown_key] < self._cooldown_seconds:
                return None

        start = time.perf_counter()
        signal = await strategy.evaluate(tick)
        decision_latency = (time.perf_counter() - start) * 1000
        metrics.record_latency("decision_latency", decision_latency, tick.symbol)

        if signal is None:
            return None

        # Resolve quantity from profile
        signal.quantity = self._resolve_quantity(signal)
        self._signal_cooldown[cooldown_key] = now

        logger.info(
            "strategy_signal_generated",
            symbol=signal.symbol,
            strategy=signal.strategy_name,
            action=signal.action,
            quantity=signal.quantity,
            trigger_price=signal.trigger_price,
            decision_latency_ms=decision_latency,
        )

        await self.event_bus.publish(
            Event(
                type=EventType.STRATEGY_SIGNAL,
                source="strategy_engine",
                data={
                    **signal.to_dict(),
                    "decision_latency_ms": decision_latency,
                },
            )
        )
        return signal

    def _resolve_quantity(self, signal: Signal) -> int:
        """Calculate order quantity from quantity profile, capped by risk limit."""
        from core.config import get_settings
        max_qty = get_settings().risk_max_quantity_per_order

        profile_name = signal.metadata.get("quantity_profile", "default")
        profile = self._quantity_profiles.get(profile_name, {"type": "fixed", "quantity": 100})

        if profile.get("type") == "fixed":
            qty = int(profile.get("quantity", 100))
        elif profile.get("type") == "percentage_of_capital":
            settings = get_settings()
            capital = settings.risk_daily_capital_limit
            pct = profile.get("percentage", 10) / 100
            price = signal.trigger_price or signal.price or 1
            qty = int((capital * pct) / price)
            qty = min(qty, profile.get("max_quantity", qty))
        else:
            qty = 100

        return min(qty, max_qty)

    def get_strategy(self, name: str) -> BaseStrategy | None:
        return self._strategies.get(name)

    def list_strategies(self) -> list[str]:
        return list(self._strategies.keys())
