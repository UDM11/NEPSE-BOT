"""Configurable trading strategy framework."""

from strategies.base import BaseStrategy, Signal, StrategyRegistry
from strategies.engine import StrategyEngine
from strategies.ipo_daily_circuit import IpoDailyCircuitStrategy  # noqa: F401
from strategies.upper_circuit import UpperCircuitBreakoutStrategy

__all__ = [
    "BaseStrategy",
    "Signal",
    "StrategyRegistry",
    "StrategyEngine",
    "UpperCircuitBreakoutStrategy",
]
