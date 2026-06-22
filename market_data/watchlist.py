"""Watchlist management from YAML configuration."""

from __future__ import annotations

from pathlib import Path

from core.config import PROJECT_ROOT, load_yaml_config
from core.logging_config import get_logger
from market_data.models import WatchlistItem

logger = get_logger("watchlist")


class WatchlistManager:
    """Load and manage configurable watchlists."""

    def __init__(self, config_path: str | Path | None = None):
        self.config_path = config_path or PROJECT_ROOT / "config" / "watchlist.yaml"
        self._items: dict[str, WatchlistItem] = {}

    def load(self) -> list[WatchlistItem]:
        """Load watchlist from YAML file."""
        config = load_yaml_config(self.config_path)
        self._items.clear()
        for entry in config.get("symbols", []):
            item = WatchlistItem(
                symbol=entry["symbol"].upper(),
                upper_circuit_price=float(entry.get("upper_circuit_price", 0)),
                lower_circuit_price=float(entry.get("lower_circuit_price", 0)),
                enabled=entry.get("enabled", True),
                strategy=entry.get("strategy", "ipo_daily_circuit"),
                is_ipo=entry.get("is_ipo", False),
                circuit_percentage=float(entry.get("circuit_percentage", 15)),
                use_dynamic_circuit=entry.get("use_dynamic_circuit", True),
                prev_close=float(entry.get("prev_close", 0)),
                listing_date=entry.get("listing_date"),
                notes=entry.get("notes", ""),
            )
            self._items[item.symbol] = item
        logger.info("watchlist_loaded", count=len(self._items))
        return self.get_enabled()

    def get_enabled(self) -> list[WatchlistItem]:
        return [item for item in self._items.values() if item.enabled]

    def get(self, symbol: str) -> WatchlistItem | None:
        return self._items.get(symbol.upper())

    def get_symbols(self) -> list[str]:
        return [item.symbol for item in self.get_enabled()]

    def update_circuit_price(self, symbol: str, upper: float, lower: float = 0.0) -> None:
        symbol = symbol.upper()
        if symbol in self._items:
            self._items[symbol].upper_circuit_price = upper
            if lower:
                self._items[symbol].lower_circuit_price = lower
