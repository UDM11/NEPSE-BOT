"""Main application entry point and orchestrator."""

from __future__ import annotations

import asyncio
import signal
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Any

import uvicorn

from broker.client import BrokerClient
from broker.naasa import create_broker_client
from core.config import get_settings, get_app_config
from core.events import Event, EventBus, EventType
from core.logging_config import setup_logging, get_logger
from core.metrics import metrics
from dashboard.app import create_dashboard_app
from database.repository import DatabaseRepository
from database.session import get_session_factory, init_db
from market_data.monitor import MarketMonitor
from market_data.watchlist import WatchlistManager
from order_engine.executor import OrderExecutor
from risk_management.manager import RiskManager
from strategies.engine import StrategyEngine

logger = get_logger("main")


class NepseTradingBot:
    """
    Main orchestrator for the NEPSE IPO upper-circuit trading system.

    Coordinates all modules in an event-driven async architecture.
    """

    def __init__(self, simulate: bool = False):
        self.settings = get_settings()
        self.event_bus = EventBus()
        self.start_time = datetime.now(timezone.utc)
        self.simulate = simulate
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._staging_lock = asyncio.Lock()
        self._staging_tasks: list[asyncio.Task] = []
        self.staged_flag = False

        # Components (initialized in setup)
        self.watchlist: WatchlistManager | None = None
        self.market_monitor: MarketMonitor | None = None
        self.strategy_engine: StrategyEngine | None = None
        self.risk_manager: RiskManager | None = None
        self.broker: BrokerClient | None = None
        self.order_executor: OrderExecutor | None = None
        self.db_repo: DatabaseRepository | None = None
        self._session_factory = None

    async def setup(self) -> None:
        """Initialize all system components."""
        logger.info("system_setup_start", env=self.settings.app_env)

        # Database
        await init_db()
        self._session_factory = get_session_factory()
        session = self._session_factory()
        self.db_repo = DatabaseRepository(session)

        # Core components
        self.watchlist = WatchlistManager()
        self.watchlist.load()

        self.broker = create_broker_client(self.event_bus, simulate=self.simulate)
        self.risk_manager = RiskManager(self.event_bus, self.db_repo)
        self.strategy_engine = StrategyEngine(self.event_bus)
        self.strategy_engine.load()

        self.order_executor = OrderExecutor(
            self.event_bus, self.risk_manager, self.broker, self.db_repo
        )

        # Market monitor with broker data provider (None in simulation mode to trigger simulated ticks)
        self.market_monitor = MarketMonitor(
            self.event_bus,
            self.watchlist,
            data_provider=None if self.simulate else self._broker_data_provider,
        )

        # Wire strategy evaluation to market ticks
        self.market_monitor.on_tick(self._on_market_tick)

        # Notifications

        # System restart event
        await self.event_bus.publish(
            Event(type=EventType.SYSTEM_RESTART, source="main", data={})
        )

        logger.info("system_setup_complete")

    async def _broker_data_provider(self, symbol: str):
        """Fetch market data from broker or fall back to simulation."""
        from market_data.models import MarketTick

        # Skip broker polling unconditionally before staging is complete to prevent browser focus sharing from interfering with order input!
        if not getattr(self, "staged_flag", False):
            logger.debug("skipping_broker_market_data_polling_before_staging_complete", symbol=symbol)
            return None

        if self.broker and self.broker.session.is_logged_in:
            data = await self.broker.get_market_data(symbol)
            if data and "ltp" in data:
                return MarketTick(
                    symbol=symbol,
                    ltp=float(data["ltp"]),
                    bid_quantity=int(data.get("bid_quantity", 0)),
                    ask_quantity=int(data.get("ask_quantity", 0)),
                    volume=int(data.get("volume", 0)),
                    upper_circuit=float(data.get("upper_circuit", 0)),
                    lower_circuit=float(data.get("lower_circuit", 0)),
                    prev_close=float(data.get("prev_close", 0)),
                    open_price=float(data.get("open_price", 0)),
                    high_price=float(data.get("high_price", 0)),
                    low_price=float(data.get("low_price", 0)),
                    high_limit=float(data.get("high_limit", 0.0)),
                    source=data.get("source", "broker"),
                )

        return None

    async def _on_market_tick(self, tick) -> None:
        """Process market tick: evaluate strategy and execute if signal generated."""
        signal = await self.strategy_engine.evaluate_tick(tick)
        if signal:
            try:
                await self.order_executor.execute_signal(signal)
            except Exception as exc:
                logger.error("signal_execution_failed", symbol=tick.symbol, error=str(exc))
                await self.event_bus.publish(
                    Event(
                        type=EventType.SYSTEM_ERROR,
                        source="main",
                        data={"error": str(exc), "symbol": tick.symbol},
                    )
                )

    async def start(self) -> None:
        """Start all bot services."""
        self._running = True
        logger.info("system_starting")

        # Initialize broker browser (skip in simulation mode)
        if not self.simulate:
            try:
                await self.broker.initialize()
                await self.broker.login()
            except Exception as exc:
                logger.warning("broker_init_degraded", error=str(exc))
                logger.info("continuing_in_simulation_mode")
        else:
            logger.info("simulation_mode_active_skipping_broker_login")

        # Start market monitoring
        await self.market_monitor.start()

        # Start metrics reporting
        self._tasks.append(asyncio.create_task(self._metrics_reporter()))

        # Start IPO early staging tasks for each symbol
        await self.start_staging_orchestrators()

        logger.info("system_started")

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        logger.info("system_stopping")

        if self.market_monitor:
            await self.market_monitor.stop()
        
        all_tasks = self._tasks + self._staging_tasks
        for task in all_tasks:
            task.cancel()
        if all_tasks:
            await asyncio.gather(*all_tasks, return_exceptions=True)
        if self.broker:
            try:
                report_path = await self.broker.generate_network_report()
                logger.info("network_report_saved_on_shutdown", path=str(report_path))
            except Exception as exc:
                logger.warning("failed_to_save_network_report_on_shutdown", error=str(exc))
            await self.broker.shutdown()

        logger.info("system_stopped")

    async def _metrics_reporter(self) -> None:
        """Periodic metrics report generation."""
        while self._running:
            await asyncio.sleep(300)
            report = metrics.generate_report()
            await self.event_bus.publish(
                Event(
                    type=EventType.METRICS_REPORT,
                    source="main",
                    data=report,
                )
            )
            logger.info("metrics_report", **report.get("key_metrics", {}))

    async def start_staging_orchestrators(self) -> None:
        """Arm staging orchestrators for all enabled watchlist items."""
        # Cancel any active staging tasks first
        if hasattr(self, "_staging_tasks") and self._staging_tasks:
            for task in self._staging_tasks:
                task.cancel()
            await asyncio.gather(*self._staging_tasks, return_exceptions=True)
            self._staging_tasks.clear()
        else:
            self._staging_tasks = []

        if not self.watchlist:
            return

        for symbol in self.watchlist.get_symbols():
            item = self.watchlist.get(symbol)
            if item and item.enabled and (item.is_ipo or item.strategy == "ipo_daily_circuit"):
                task = asyncio.create_task(self._ipo_staging_orchestrator_for_symbol(symbol.upper()))
                self._staging_tasks.append(task)
                logger.info("armed_staging_orchestrator_for_symbol", symbol=symbol)

    async def _ipo_staging_orchestrator_for_symbol(self, symbol: str) -> None:
        """
        Background task to coordinate staging and trigger at market open (11:00 AM)
        for a specific watchlist item.
        """
        symbol = symbol.upper()
        if not self.watchlist:
            return

        item = self.watchlist.get(symbol)
        if not item or not item.enabled:
            return

        # 2. Calculate target circuit limit price
        prev_close = item.prev_close
        if prev_close <= 0:
            logger.warning("ipo_staging_invalid_prev_close", symbol=symbol, prev_close=prev_close)
            return

        circuit_pct = item.circuit_percentage or 15.0
        import math
        target_price = math.floor(prev_close * (1 + circuit_pct / 100.0) * 10) / 10

        # Quantity
        quantity = item.quantity if hasattr(item, "quantity") else 10
        # Cap by risk parameters
        max_qty = self.settings.risk_max_quantity_per_order
        quantity = min(quantity, max_qty)

        logger.info(
            "ipo_staging_orchestrator_for_symbol_initialized",
            symbol=symbol,
            prev_close=prev_close,
            target_price=target_price,
            quantity=quantity,
        )

        app_config = get_app_config()
        price_band_pct = app_config.get("trading", {}).get("price_band_percentage", 3.0)
        price_band_divisor = 1.0 + (price_band_pct / 100.0)

        tz = ZoneInfo("Asia/Kathmandu")
        staged = False
        triggered = False
        last_logged_sec = -1

        # Shared pre-resolved order variables
        scrip_id = None
        exchange = None
        cookies = None
        user_agent = None

        while self._running:
            # Check if kill switch is active
            is_kill_active = self.settings.risk_kill_switch or (self.risk_manager.state.kill_switch_active if self.risk_manager else False)
            if is_kill_active:
                now_nepal = datetime.now(tz)
                current_sec = now_nepal.second
                if current_sec % 10 == 0 and current_sec != last_logged_sec:
                    last_logged_sec = current_sec
                    logger.warning("orchestrator_paused_kill_switch_active", symbol=symbol)
                await asyncio.sleep(1.0)
                continue

            now_nepal = datetime.now(tz)
            current_time_str = now_nepal.strftime("%H:%M:%S")

            # Check if it is staging time: between 10:50:00 AM and 10:59:50 AM
            if not staged:
                is_staging_window = (
                    now_nepal.hour == 10 and 50 <= now_nepal.minute < 59
                )
                is_test_run = self.settings.app_env.lower() == "development" or now_nepal.hour >= 11 or now_nepal.hour < 10
                
                if is_staging_window or is_test_run:
                    logger.info("ipo_staging_triggering_form_stage", symbol=symbol)
                    if hasattr(self.broker, "stage_order"):
                        async with self._staging_lock:
                            staged = await self.broker.stage_order(symbol, quantity, target_price)
                            if staged:
                                # Pre-resolve order tokens and session data once staged successfully
                                symbol_page = getattr(self.broker, "_symbol_pages", {}).get(symbol.upper(), getattr(self.broker, "_page", None))
                                if not self.simulate and symbol_page:
                                    try:
                                        scrip_id = await symbol_page.evaluate("Selected_scrip")
                                        exchange = await symbol_page.evaluate("Selected_Exchange")
                                        playwright_cookies = await self.broker._context.cookies()
                                        cookies = {c["name"]: c["value"] for c in playwright_cookies if "naasasecurities.com.np" in c["domain"]}
                                        user_agent = await symbol_page.evaluate("navigator.userAgent")
                                        logger.info("pre_resolved_order_tokens_successfully", symbol=symbol, scrip_id=scrip_id, exchange=exchange)
                                        if not scrip_id or not exchange:
                                            logger.warning("staged_tokens_empty_retrying", symbol=symbol)
                                            staged = False
                                    except Exception as e:
                                        logger.warning("failed_to_pre_resolve_order_tokens", symbol=symbol, error=str(e))
                                        staged = False
                                if staged:
                                    self.staged_flag = True
                                    logger.info("ipo_staging_form_staged_successfully", symbol=symbol)
                            else:
                                logger.error("ipo_staging_form_stage_failed", symbol=symbol)
                    else:
                        logger.warning("broker_does_not_support_staging")
                        staged = True # don't loop endlessly

            # Get live price from MarketMonitor to check price trigger
            current_price = 0.0
            high_limit = 0.0
            pct_change = 0.0
            if self.market_monitor:
                tick = self.market_monitor.get_latest_tick(symbol)
                if tick:
                    if tick.ltp > 0:
                        current_price = tick.ltp
                        if prev_close > 0:
                            pct_change = ((current_price - prev_close) / prev_close) * 100.0
                    if getattr(tick, "high_limit", 0.0) > 0.0:
                        high_limit = tick.high_limit

            # Periodically log wait status to console (every 5 seconds)
            if staged and not triggered:
                current_sec = now_nepal.second
                if current_sec % 5 == 0 and current_sec != last_logged_sec:
                    last_logged_sec = current_sec
                    if current_price == 0.0:
                        logger.info("waiting_for_first_price_tick", symbol=symbol)
                    else:
                        logger.info(
                            "monitoring_price_breakout",
                            symbol=symbol,
                            ltp=current_price,
                            change=f"{pct_change:.2f}%",
                            target_ltp=f">={target_price / price_band_divisor:.1f}",
                        )

            # Check if it is trigger time
            if staged and not triggered:
                # Trigger when current price allows placing target_price under NEPSE's price band (LTP >= target_price / price_band_divisor)
                # Or when the broker's actual high limit has reached/exceeded the target price
                # Fallback to immediate trigger in development environment to support testing
                is_dev = self.settings.app_env.lower() == "development"
                is_within_price_band = (current_price >= (target_price / price_band_divisor)) if current_price > 0.0 else False
                is_high_limit_reached = (high_limit >= target_price) if high_limit > 0.0 else False
                should_trigger = is_within_price_band or is_high_limit_reached or is_dev

                if should_trigger:
                    logger.critical(
                        "ipo_staging_preemptive_trigger_met",
                        symbol=symbol,
                        ltp=current_price,
                        high_limit=high_limit,
                    )

                if should_trigger:
                    logger.info("ipo_staging_starting_fast_trigger_loop", symbol=symbol, time=current_time_str)
                    triggered = True
                    
                    attempts = 0
                    max_attempts = 150
                    success = False
                    last_error_msg = None
                    
                    while attempts < max_attempts and self._running and not success:
                        attempts += 1
                        logger.info("fast_trigger_attempt", symbol=symbol, attempt=attempts, time=datetime.now(tz).strftime("%H:%M:%S.%f"))
                        
                        if hasattr(self.broker, "fast_trigger_buy"):
                            is_kill_active = self.settings.risk_kill_switch or (self.risk_manager.state.kill_switch_active if self.risk_manager else False)
                            res = await self.broker.fast_trigger_buy(
                                symbol=symbol,
                                quantity=quantity,
                                price=target_price,
                                kill_switch=is_kill_active,
                                scrip_id=scrip_id,
                                exchange=exchange,
                                cookies=cookies,
                                user_agent=user_agent,
                            )
                            if res.get("success"):
                                success = True
                                logger.critical(
                                    "ipo_staging_order_executed_successfully",
                                    symbol=symbol,
                                    result=res,
                                )
                                await self._log_ipo_order(
                                    symbol=symbol,
                                    quantity=quantity,
                                    price=target_price,
                                    success=True,
                                    broker_order_id=res.get("order_id"),
                                    error_msg=res.get("message"),
                                )
                                break
                            else:
                                reason = res.get("reason", res.get("error", "unknown"))
                                message = res.get("message", "")
                                last_error_msg = f"{reason}: {message}"
                                logger.debug("fast_trigger_attempt_failed", symbol=symbol, attempt=attempts, reason=reason, message=message)
                                if reason == "Kill switch active":
                                    logger.warning("fast_trigger_stopped_due_to_kill_switch", symbol=symbol)
                                    break
                                # Self-healing: if session or cookie error occurs, refresh tokens from the active browser context
                                if any(x in (str(reason) + " " + str(message)).lower() for x in ("cookie", "session", "auth", "unauthorized", "login", "expired")):
                                    try:
                                        playwright_cookies = await self.broker._context.cookies()
                                        cookies = {c["name"]: c["value"] for c in playwright_cookies if "naasasecurities.com.np" in c["domain"]}
                                        logger.info("dynamically_refreshed_expired_cookies_during_trigger_loop", symbol=symbol)
                                    except Exception as e:
                                        logger.warning("failed_to_dynamically_refresh_cookies", error=str(e))
                        # Constant high-frequency sleep (50ms) to ensure maximum speed once the 8% price trigger is hit
                        await asyncio.sleep(0.05)
                    
                    if not success:
                        logger.error("ipo_staging_fast_trigger_loop_exhausted_without_success", symbol=symbol)
                        await self._log_ipo_order(
                            symbol=symbol,
                            quantity=quantity,
                            price=target_price,
                            success=False,
                            error_msg=last_error_msg or "Fast trigger loop exhausted without success",
                        )
                        triggered = False                  # Reset triggered so we can check again on the next price tick
            
            # Precise polling sleep intervals
            if staged and not triggered:
                is_critical_window = (
                    (now_nepal.hour == 10 and now_nepal.minute == 59) or
                    (now_nepal.hour == 11 and now_nepal.minute < 5) or
                    (self.settings.app_env.lower() == "development")
                )
                if is_critical_window:
                    if self.market_monitor:
                        self.market_monitor.poll_interval = 0.05 # Boost poll interval to 50ms
                    await asyncio.sleep(0.02)
                elif now_nepal.hour == 10 and now_nepal.minute >= 50:
                    await asyncio.sleep(0.1)
                else:
                    await asyncio.sleep(1.0)
            else:
                await asyncio.sleep(1.0)

    async def _log_ipo_order(
        self,
        symbol: str,
        quantity: int,
        price: float,
        success: bool,
        broker_order_id: str | None = None,
        error_msg: str | None = None,
    ) -> None:
        """Log IPO fast trigger order execution results to the database and event bus."""
        from database.models import Order, OrderStatus
        from uuid import uuid4
        from datetime import datetime, timezone

        order_id = str(uuid4())
        status = OrderStatus.EXECUTED if success else OrderStatus.FAILED

        if self._session_factory:
            async with self._session_factory() as session:
                try:
                    db_repo = DatabaseRepository(session)
                    await db_repo.create_order(
                        Order(
                            id=order_id,
                            symbol=symbol,
                            side="buy",
                            order_type="limit",
                            quantity=quantity,
                            price=price,
                            status=status,
                            broker_order_id=broker_order_id,
                            strategy_name="ipo_daily_circuit",
                            error_message=error_msg,
                            executed_at=datetime.now(timezone.utc) if success else None,
                        )
                    )
                    logger.info("logged_ipo_order_to_db", symbol=symbol, order_id=order_id, success=success)
                except Exception as e:
                    logger.error("failed_to_log_ipo_order_to_db", symbol=symbol, error=str(e))

        if self.risk_manager:
            if success:
                self.risk_manager.state.orders_today[symbol] = (
                    self.risk_manager.state.orders_today.get(symbol, 0) + 1
                )
                self.risk_manager.record_success()
            else:
                self.risk_manager.record_failure()

        if success:
            metrics.increment("orders_executed")

        event_type = EventType.ORDER_EXECUTED if success else EventType.ORDER_FAILED
        try:
            await self.event_bus.publish(
                Event(
                    type=event_type,
                    source="ipo_staging_orchestrator",
                    data={
                        "order_id": order_id,
                        "symbol": symbol,
                        "side": "buy",
                        "quantity": quantity,
                        "price": price,
                        "success": success,
                        "broker_order_id": broker_order_id,
                        "error": error_msg,
                    },
                )
            )
        except Exception as e:
            logger.warning("failed_to_publish_ipo_order_event", symbol=symbol, error=str(e))

    def get_state(self) -> dict[str, Any]:
        """Return bot state for dashboard."""
        uptime = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        return {
            "uptime": f"{uptime:.0f}s",
            "market_monitor": self.market_monitor,
            "risk_manager": self.risk_manager,
            "broker": self.broker,
            "db_repo": self.db_repo,
            "event_bus": self.event_bus,
            "bot": self,
        }


async def run_bot(with_dashboard: bool = True, simulate: bool = False) -> None:
    """Run the trading bot with optional dashboard."""
    setup_logging()
    bot = NepseTradingBot(simulate=simulate)
    await bot.setup()

    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _signal_handler(*_):
        shutdown_event.set()

    if sys.platform == "win32":
        signal.signal(signal.SIGINT, _signal_handler)
    else:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _signal_handler)

    await bot.start()

    async def monitor_bot_running():
        try:
            while bot._running:
                await asyncio.sleep(0.5)
            shutdown_event.set()
        except asyncio.CancelledError:
            pass

    monitor_task = asyncio.create_task(monitor_bot_running())

    if with_dashboard:
        settings = get_settings()
        app = create_dashboard_app(bot.get_state())
        config = uvicorn.Config(
            app,
            host=settings.dashboard_host,
            port=settings.dashboard_port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        _dashboard_task = asyncio.create_task(server.serve())
        logger.info("dashboard_started", port=settings.dashboard_port)

    try:
        await shutdown_event.wait()
    except KeyboardInterrupt:
        pass
    finally:
        monitor_task.cancel()
        await bot.stop()


def main():
    """CLI entry point."""
    # Set Windows Process Priority to High for maximum speed
    if sys.platform == "win32":
        try:
            import ctypes
            # HIGH_PRIORITY_CLASS = 0x00000080
            ctypes.windll.kernel32.SetPriorityClass(
                ctypes.windll.kernel32.GetCurrentProcess(), 0x00000080
            )
            print("Windows Process Priority set to HIGH for maximum execution speed.")
        except Exception as e:
            print(f"Failed to set Windows Process Priority: {e}")

    with_dashboard = "--no-dashboard" not in sys.argv
    simulate = "--simulate" in sys.argv
    asyncio.run(run_bot(with_dashboard=with_dashboard, simulate=simulate))


if __name__ == "__main__":
    main()
