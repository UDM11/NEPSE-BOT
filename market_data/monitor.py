"""High-performance async market monitoring engine."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from datetime import datetime, timezone
from typing import Any

from core.config import get_app_config
from core.events import Event, EventBus, EventType
from core.logging_config import get_logger
from core.metrics import metrics
from market_data.circuit import calculate_daily_circuits
from market_data.models import MarketDepth, MarketTick
from market_data.watchlist import WatchlistManager

logger = get_logger("market_monitor")

TickCallback = Callable[[MarketTick], Coroutine[Any, Any, None]]


class MarketMonitor:
    """
    Event-driven market data monitor.

    Supports multiple data sources:
    - Broker WebSocket feed (via network analyzer)
    - Polling fallback via broker API/page scraping
    - Simulated feed for testing
    """

    def __init__(
        self,
        event_bus: EventBus,
        watchlist: WatchlistManager,
        data_provider: Callable[[str], Coroutine[Any, Any, MarketTick | None]] | None = None,
    ):
        self.event_bus = event_bus
        self.watchlist = watchlist
        self.data_provider = data_provider
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._latest_ticks: dict[str, MarketTick] = {}
        self._circuit_hit_symbols: set[str] = set()
        self._circuit_hit_date: dict[str, str] = {}
        self._callbacks: list[TickCallback] = []
        app_config = get_app_config()
        monitoring = app_config.get("monitoring", {})
        self.poll_interval = monitoring.get("poll_interval_ms", 100) / 1000
        self.max_concurrent = monitoring.get("max_concurrent_symbols", 50)

    def on_tick(self, callback: TickCallback) -> None:
        """Register callback for tick updates."""
        self._callbacks.append(callback)

    async def start(self) -> None:
        """Start monitoring all watchlist symbols."""
        if self._running:
            return
        self._running = True
        symbols = self.watchlist.get_symbols()
        if not symbols:
            logger.warning("watchlist_empty")
            return

        logger.info("market_monitor_starting", symbols=symbols)
        # Pre-populate self._latest_ticks with placeholders so they display on the dashboard immediately
        for symbol in symbols:
            item = self.watchlist.get(symbol)
            if item:
                upper = item.upper_circuit_price
                lower = item.lower_circuit_price
                if item.use_dynamic_circuit and item.prev_close > 0:
                    import math
                    upper = math.floor(item.prev_close * (1 + item.circuit_percentage / 100.0) * 10) / 10
                    lower = math.ceil(item.prev_close * (1 - item.circuit_percentage / 100.0) * 10) / 10
                self._latest_ticks[symbol.upper()] = MarketTick(
                    symbol=symbol.upper(),
                    ltp=0.0,
                    upper_circuit=upper,
                    lower_circuit=lower,
                    prev_close=item.prev_close,
                    source="placeholder",
                )
        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def monitor_symbol(symbol: str) -> None:
            while self._running:
                async with semaphore:
                    try:
                        await self._process_symbol(symbol)
                    except Exception as exc:
                        logger.error("symbol_monitor_error", symbol=symbol, error=str(exc))
                await asyncio.sleep(self.poll_interval)

        self._tasks = [asyncio.create_task(monitor_symbol(s)) for s in symbols]

    async def stop(self) -> None:
        """Stop all monitoring tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("market_monitor_stopped")

    async def _process_symbol(self, symbol: str) -> None:
        """Fetch and process market data for a single symbol."""
        start = time.perf_counter()

        tick = await self._fetch_tick(symbol)
        if tick is None:
            return

        # Enrich with watchlist circuit prices (dynamic 15% daily band for IPOs)
        watchlist_item = self.watchlist.get(symbol)
        if watchlist_item:
            prev_close = tick.prev_close or watchlist_item.prev_close
            if watchlist_item.use_dynamic_circuit and prev_close > 0:
                circuits = calculate_daily_circuits(
                    prev_close, watchlist_item.circuit_percentage
                )
                tick.prev_close = prev_close
                tick.upper_circuit = circuits.upper_circuit
                tick.lower_circuit = circuits.lower_circuit
            else:
                if watchlist_item.upper_circuit_price > 0:
                    tick.upper_circuit = watchlist_item.upper_circuit_price
                if watchlist_item.lower_circuit_price > 0:
                    tick.lower_circuit = watchlist_item.lower_circuit_price

        self._latest_ticks[symbol] = tick
        detection_latency = (time.perf_counter() - start) * 1000
        metrics.record_latency("detection_latency", detection_latency, symbol)

        # Publish market data update
        await self.event_bus.publish(
            Event(
                type=EventType.MARKET_DATA_UPDATE,
                source="market_monitor",
                data=tick.to_dict(),
            )
        )

        # Detect circuit hit (once per symbol per trading day)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        last_hit = self._circuit_hit_date.get(symbol)
        if tick.is_at_upper_circuit and last_hit != today:
            self._circuit_hit_symbols.add(symbol)
            self._circuit_hit_date[symbol] = today
            logger.info(
                "circuit_hit_detected",
                symbol=symbol,
                ltp=tick.ltp,
                upper_circuit=tick.upper_circuit,
                latency_ms=detection_latency,
            )
            await self.event_bus.publish(
                Event(
                    type=EventType.CIRCUIT_HIT,
                    source="market_monitor",
                    data={
                        **tick.to_dict(),
                        "detection_latency_ms": detection_latency,
                    },
                )
            )

        # Notify callbacks
        for callback in self._callbacks:
            try:
                await callback(tick)
            except Exception as exc:
                logger.error("tick_callback_error", symbol=symbol, error=str(exc))

    async def _fetch_tick(self, symbol: str) -> MarketTick | None:
        """Fetch tick from data provider or generate simulated data."""
        if self.data_provider:
            return await self.data_provider(symbol)

        # Simulated tick for development/testing
        item = self.watchlist.get(symbol)
        if not item:
            return None
        # Calculate circuit dynamically for IPOs
        upper = item.upper_circuit_price
        lower = item.lower_circuit_price
        if item.use_dynamic_circuit and item.prev_close > 0:
            from market_data.circuit import calculate_daily_circuits
            circuits = calculate_daily_circuits(item.prev_close, item.circuit_percentage)
            upper = circuits.upper_circuit
            lower = circuits.lower_circuit
        sim_price = upper * 0.99 if upper else 100.0
        return MarketTick(
            symbol=symbol,
            ltp=sim_price,
            bid_quantity=1500,
            ask_quantity=300,
            volume=5000,
            upper_circuit=upper,
            lower_circuit=lower,
            prev_close=item.prev_close,
            bids=[MarketDepth(price=sim_price, quantity=1500)],
            asks=[MarketDepth(price=upper, quantity=300)],
            timestamp=datetime.now(timezone.utc),
            source="simulated",
        )

    def get_latest_tick(self, symbol: str) -> MarketTick | None:
        return self._latest_ticks.get(symbol.upper())

    def get_all_ticks(self) -> dict[str, MarketTick]:
        return dict(self._latest_ticks)

    def reset_circuit_tracking(self, symbol: str | None = None) -> None:
        if symbol:
            sym = symbol.upper()
            self._circuit_hit_symbols.discard(sym)
            self._circuit_hit_date.pop(sym, None)
        else:
            self._circuit_hit_symbols.clear()
            self._circuit_hit_date.clear()
