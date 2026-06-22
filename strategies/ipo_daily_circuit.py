"""IPO daily 15% upper circuit buy strategy."""

from __future__ import annotations

from strategies.base import StrategyRegistry
from strategies.upper_circuit import UpperCircuitBreakoutStrategy


class IpoDailyCircuitStrategy(UpperCircuitBreakoutStrategy):
    """
    IPO strategy: buy when daily upper circuit (15%) is hit.

    Upper/lower circuit is calculated each day from previous close:
      upper = prev_close × 1.15
      lower = prev_close × 0.85

  Designed for IPOs that hit 15% upper circuit on consecutive days.
    """

    name = "ipo_daily_circuit"


StrategyRegistry.register("ipo_daily_circuit", IpoDailyCircuitStrategy)
