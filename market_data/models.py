"""Market data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class MarketDepth:
    """Order book depth level."""

    price: float
    quantity: int
    orders: int = 0


@dataclass
class MarketTick:
    """Real-time market data snapshot for a symbol."""

    symbol: str
    ltp: float
    bid_price: float = 0.0
    ask_price: float = 0.0
    bid_quantity: int = 0
    ask_quantity: int = 0
    volume: int = 0
    upper_circuit: float = 0.0
    lower_circuit: float = 0.0
    open_price: float = 0.0
    high_price: float = 0.0
    low_price: float = 0.0
    prev_close: float = 0.0
    high_limit: float = 0.0
    bids: list[MarketDepth] = field(default_factory=list)
    asks: list[MarketDepth] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: str = "broker"

    @property
    def current_price(self) -> float:
        """Alias for ltp used by strategy conditions."""
        return self.ltp

    @property
    def upper_circuit_price(self) -> float:
        """Alias for upper_circuit used by strategy conditions."""
        return self.upper_circuit

    @property
    def is_at_upper_circuit(self) -> bool:
        if self.upper_circuit <= 0:
            return False
        tolerance = self.upper_circuit * 0.001
        return self.ltp >= (self.upper_circuit - tolerance)

    @property
    def total_bid_quantity(self) -> int:
        return self.bid_quantity or sum(b.quantity for b in self.bids)

    @property
    def total_ask_quantity(self) -> int:
        return self.ask_quantity or sum(a.quantity for a in self.asks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "ltp": self.ltp,
            "bid_price": self.bid_price,
            "ask_price": self.ask_price,
            "bid_quantity": self.total_bid_quantity,
            "ask_quantity": self.total_ask_quantity,
            "volume": self.volume,
            "upper_circuit": self.upper_circuit,
            "lower_circuit": self.lower_circuit,
            "prev_close": self.prev_close,
            "is_at_upper_circuit": self.is_at_upper_circuit,
            "high_limit": self.high_limit,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class WatchlistItem:
    """Watchlist entry with strategy binding."""

    symbol: str
    upper_circuit_price: float = 0.0
    lower_circuit_price: float = 0.0
    enabled: bool = True
    strategy: str = "ipo_daily_circuit"
    is_ipo: bool = False
    circuit_percentage: float = 15.0
    use_dynamic_circuit: bool = True
    prev_close: float = 0.0
    listing_date: str | None = None
    notes: str = ""
