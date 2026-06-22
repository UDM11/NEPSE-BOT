"""NEPSE daily price band / circuit calculations."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DailyCircuits:
    """Upper and lower circuit for a trading day."""

    prev_close: float
    circuit_percentage: float
    upper_circuit: float
    lower_circuit: float

    @property
    def circuit_range(self) -> float:
        return self.upper_circuit - self.lower_circuit


def calculate_daily_circuits(prev_close: float, circuit_percentage: float = 15.0) -> DailyCircuits:
    """
    Calculate NEPSE daily upper/lower circuit from previous close.

    IPO/new listings often use 15% daily band:
      upper = prev_close × (1 + 15/100)
      lower = prev_close × (1 - 15/100)
    """
    if prev_close <= 0:
        return DailyCircuits(0, circuit_percentage, 0, 0)

    import math
    multiplier = circuit_percentage / 100.0
    upper = math.floor(prev_close * (1 + multiplier) * 10) / 10
    lower = math.ceil(prev_close * (1 - multiplier) * 10) / 10
    return DailyCircuits(
        prev_close=prev_close,
        circuit_percentage=circuit_percentage,
        upper_circuit=upper,
        lower_circuit=lower,
    )


def next_day_upper_circuit(today_close: float, circuit_percentage: float = 15.0) -> float:
    """Shortcut: tomorrow's upper circuit after today's close."""
    return calculate_daily_circuits(today_close, circuit_percentage).upper_circuit
