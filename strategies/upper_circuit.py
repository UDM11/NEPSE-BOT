"""Upper circuit breakout strategy implementation."""

from __future__ import annotations

from market_data.models import MarketTick
from strategies.base import BaseStrategy, Signal, StrategyRegistry


class UpperCircuitBreakoutStrategy(BaseStrategy):
    """
    Buy when price reaches upper circuit with favorable order book conditions.

    Conditions (all configurable via YAML):
    - Current price >= upper circuit price
    - Ask/sell quantity <= threshold (low sell pressure)
    - Bid/buy quantity >= threshold (strong buy demand)
    - Volume >= minimum threshold
    """

    name = "upper_circuit_breakout"

    async def evaluate(self, tick: MarketTick) -> Signal | None:
        if not self.enabled:
            return None

        conditions = self.config.get("conditions", [])
        if not conditions:
            return None

        all_met = True
        conditions_result = {}

        for condition in conditions:
            met, detail = self._evaluate_condition(tick, condition)
            conditions_result[condition["field"]] = detail
            if not met:
                all_met = False

        if not all_met:
            return None

        # Build signal from actions config
        actions = self.config.get("actions", [{"type": "buy", "order_type": "market"}])
        action = actions[0]

        order_type = self._resolve_param(action.get("order_type", "market"))
        quantity_profile = self._resolve_param(action.get("quantity_profile", "default"))

        return Signal(
            symbol=tick.symbol,
            strategy_name=self.name,
            action="buy",  # buy-only bot — never sell
            order_type=str(order_type),
            trigger_price=tick.ltp,
            price=tick.upper_circuit if order_type == "limit" else None,
            conditions_met=conditions_result,
            metadata={
                "quantity_profile": quantity_profile,
                "upper_circuit": tick.upper_circuit,
                "bid_quantity": tick.total_bid_quantity,
                "ask_quantity": tick.total_ask_quantity,
                "volume": tick.volume,
            },
        )


# Register strategy
StrategyRegistry.register("upper_circuit_breakout", UpperCircuitBreakoutStrategy)
