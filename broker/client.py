"""Playwright-based broker TMS automation client."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from broker.network_analyzer import NetworkAnalyzer
from broker.session import SessionManager
from core.config import PROJECT_ROOT, get_app_config, get_settings
from core.events import Event, EventBus, EventType
from core.exceptions import BrokerError, CaptchaDetectedError, LoginError
from core.logging_config import get_logger

logger = get_logger("broker_client")


class BrokerClient:
    """
    Browser automation layer for NEPSE broker TMS platforms.

    Features:
    - Secure login with credential management
    - Session management with auto re-login
    - DOM monitoring and page state validation
    - Error recovery with screenshot capture
    - CAPTCHA detection
    - Network traffic analysis
    - Headless and headed debug modes
    - Multiple browser profiles
    """

    def __init__(self, event_bus: EventBus, profile_name: str = "default", simulate: bool = False):
        self.event_bus = event_bus
        self.profile_name = profile_name
        self.simulate = simulate
        settings = get_settings()
        app_config = get_app_config()
        broker_config = app_config.get("broker", {})

        self.broker_url = settings.broker_url
        self.username = settings.broker_username
        self.password = settings.broker_password.get_secret_value()
        self.client_code = settings.broker_client_code
        self.headless = settings.broker_headless if settings.broker_headless is not None else broker_config.get("headless", True)
        self.screenshot_on_failure = broker_config.get(
            "screenshot_on_failure", settings.broker_debug_screenshots
        )
        self.timeout = broker_config.get("timeout_ms", 30000)
        self.selectors = broker_config.get("selectors", {})

        self.session = SessionManager(event_bus)
        self.network = NetworkAnalyzer(event_bus=event_bus)
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._screenshot_dir = PROJECT_ROOT / "logs" / "screenshots"
        self._screenshot_dir.mkdir(parents=True, exist_ok=True)

    async def initialize(self) -> None:
        """Launch browser and set up network monitoring."""
        await self.shutdown()
        if self.simulate:
            logger.info("simulated_broker_browser_initialized", profile=self.profile_name)
            return
        
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-ipc-flooding-protection",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--disable-hang-monitor",
                "--no-first-run",
                "--no-sandbox",
                "--disable-setuid-sandbox",
            ],
        )
        profile_dir = PROJECT_ROOT / "config" / "browser_profiles" / self.profile_name
        profile_dir.mkdir(parents=True, exist_ok=True)

        self._context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            storage_state=str(profile_dir / "state.json")
            if (profile_dir / "state.json").exists()
            else None,
        )
        self._context.set_default_timeout(self.timeout)
        self._page = await self._context.new_page()
        await self._page.route("**/*", self._route_filter)

        # Attach network analyzers
        self._page.on("request", self.network.on_request)
        self._page.on("response", lambda r: asyncio.create_task(self.network.on_response(r)))
        self._page.on("websocket", self.network.on_websocket)

        logger.info("broker_browser_initialized", headless=self.headless, profile=self.profile_name)

    async def _route_filter(self, route) -> None:
        """Filter out fonts, media, analytics, and ads to prioritize trading bandwidth."""
        request = route.request
        url = request.url.lower()
        resource_type = request.resource_type

        # Block fonts, media (videos/ads), and tracking domains
        block_keywords = ("analytics", "hotjar", "facebook", "pixel", "doubleclick", "adservice", "google-analytics")
        if resource_type in ("font", "media") or any(kw in url for kw in block_keywords):
            try:
                await route.abort()
            except Exception:
                pass
        else:
            try:
                await route.continue_()
            except Exception:
                pass

    async def login(self) -> bool:
        """Authenticate with broker TMS platform."""
        if self.simulate:
            logger.info("simulated_broker_login_success")
            self.session.mark_logged_in()
            return True

        if not self._page or self._page.is_closed():
            await self.initialize()

        try:
            logger.info("broker_login_start", url=self.broker_url)
            await self._page.goto(self.broker_url, wait_until="networkidle")

            # Check for CAPTCHA
            captcha_sel = self.selectors.get("captcha", ".captcha")
            if await self._page.locator(captcha_sel).count() > 0:
                await self._capture_screenshot("captcha_detected")
                await self.event_bus.publish(
                    Event(
                        type=EventType.CAPTCHA_DETECTED,
                        source="broker_client",
                        data={"url": self.broker_url},
                    )
                )
                raise CaptchaDetectedError("CAPTCHA detected - manual intervention required")

            # Fill credentials
            username_sel = self.selectors.get("username", 'input[name="username"]')
            password_sel = self.selectors.get("password", 'input[name="password"]')
            login_btn_sel = self.selectors.get("login_button", 'button[type="submit"]')

            await self._page.fill(username_sel, self.username)
            await self._page.fill(password_sel, self.password)

            if self.client_code:
                client_sel = self.selectors.get("client_code", 'input[name="clientCode"]')
                if await self._page.locator(client_sel).count() > 0:
                    await self._page.fill(client_sel, self.client_code)

            await self._page.click(login_btn_sel)
            await self._page.wait_for_load_state("networkidle")

            # Validate login success
            if await self._is_login_page():
                await self._capture_screenshot("login_failed")
                await self.event_bus.publish(
                    Event(
                        type=EventType.LOGIN_FAILURE,
                        source="broker_client",
                        data={"reason": "Still on login page after submission"},
                    )
                )
                raise LoginError("Login failed - still on login page")

            self.session.mark_logged_in()
            await self._save_browser_state()

            await self.event_bus.publish(
                Event(
                    type=EventType.LOGIN_SUCCESS,
                    source="broker_client",
                    data={"profile": self.profile_name},
                )
            )
            logger.info("broker_login_success")
            return True

        except (CaptchaDetectedError, LoginError):
            raise
        except Exception as exc:
            await self._capture_screenshot("login_error")
            await self.event_bus.publish(
                Event(
                    type=EventType.LOGIN_FAILURE,
                    source="broker_client",
                    data={"error": str(exc)},
                )
            )
            raise LoginError(f"Login failed: {exc}") from exc

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: int,
        price: float | None = None,
    ) -> dict[str, Any]:
        """Place order through broker TMS web interface."""
        if self.simulate:
            logger.info(
                "simulated_order_placed",
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity,
                price=price,
            )
            return {
                "success": True,
                "status": "submitted",
                "message": "Simulated order placed successfully",
                "order_id": f"SIM-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            }

        await self.session.ensure_session(self.login)

        if not self._page:
            raise BrokerError("Browser not initialized")

        self.session.touch()
        logger.info(
            "placing_order",
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
        )

        try:
            # Navigate to order entry (broker-specific - customize selectors)
            order_url = f"{self.broker_url}/order"
            current_url = self._page.url
            if "order" not in current_url.lower():
                try:
                    await self._page.goto(order_url, wait_until="networkidle", timeout=10000)
                except Exception:
                    pass  # May already be on trading page

            # Fill order form
            symbol_sel = self.selectors.get("order_symbol", 'input[name="symbol"]')
            qty_sel = self.selectors.get("order_quantity", 'input[name="quantity"]')
            price_sel = self.selectors.get("order_price", 'input[name="price"]')

            await self._page.fill(symbol_sel, symbol.upper())
            await self._page.fill(qty_sel, str(quantity))

            if order_type == "limit" and price:
                limit_sel = self.selectors.get("order_type_limit", 'input[value="limit"]')
                if await self._page.locator(limit_sel).count() > 0:
                    await self._page.click(limit_sel)
                await self._page.fill(price_sel, str(price))
            else:
                market_sel = self.selectors.get("order_type_market", 'input[value="market"]')
                if await self._page.locator(market_sel).count() > 0:
                    await self._page.click(market_sel)

            # Click buy/sell
            action_sel = (
                self.selectors.get("buy_button", ".btn-buy")
                if side == "buy"
                else self.selectors.get("sell_button", ".btn-sell")
            )
            await self._page.click(action_sel)

            # Submit order
            submit_sel = self.selectors.get("submit_order", 'button[type="submit"]')
            await self._page.click(submit_sel)
            await self._page.wait_for_load_state("networkidle", timeout=15000)

            # Validate submission (look for confirmation)
            confirmation = await self._check_order_confirmation()
            return confirmation

        except Exception as exc:
            await self._capture_screenshot(f"order_error_{symbol}")
            logger.error("order_placement_failed", symbol=symbol, error=str(exc))
            raise BrokerError(f"Order placement failed: {exc}") from exc

    async def get_market_data(self, symbol: str) -> dict[str, Any] | None:
        """Fetch market data for symbol from broker page/API."""
        if self.simulate:
            return {
                "symbol": symbol,
                "ltp": 100.0,
                "prev_close": 100.0,
                "source": "simulated",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        await self.session.ensure_session(self.login)
        if not self._page:
            return None

        self.session.touch()
        # Attempt to extract from page or intercepted network data
        market_streams = self.network.get_market_data_streams()
        if market_streams:
            logger.debug("market_data_from_network", symbol=symbol, streams=len(market_streams))

        return {
            "symbol": symbol,
            "source": "broker_page",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _is_login_page(self) -> bool:
        if not self._page:
            return True
        expired_sel = self.selectors.get("session_expired", ".login-page")
        login_sel = self.selectors.get("username", 'input[name="username"]')
        return (
            await self._page.locator(expired_sel).count() > 0
            or await self._page.locator(login_sel).count() > 0
        )

    async def _check_order_confirmation(self) -> dict[str, Any]:
        """Detect Naasa X order confirmation via toast, modal, or alert."""
        if not self._page:
            return {"success": False, "message": "No page"}

        # Wait briefly for any confirmation UI to appear
        await asyncio.sleep(1.5)

        # Naasa X shows SweetAlert2 modals, Bootstrap toasts, or Gritter alerts
        for sel in (
            ".swal2-title", ".swal2-content", ".toast-message",
            ".alert-success", ".alert-danger", "#successModal", "#errorModal",
            ".gritter-item",
        ):
            try:
                el = self._page.locator(sel)
                if await el.count() > 0:
                    text = (await el.first.inner_text()).lower()
                    if any(w in text for w in ("success", "placed", "submitted", "accepted")):
                        return {"success": True, "status": "submitted", "message": text,
                                "order_id": f"NAASA-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"}
                    if any(w in text for w in ("error", "fail", "reject", "invalid", "insufficient", "cannot", "not enough", "exceeded")):
                        return {"success": False, "status": "rejected", "message": text}
            except Exception:
                continue

        # Last resort: check page text
        try:
            body = (await self._page.inner_text("body")).lower()
            if any(w in body for w in ("order placed", "order submitted", "successfully")):
                return {"success": True, "status": "submitted", "message": "Order submitted",
                        "order_id": f"NAASA-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"}
        except Exception:
            pass

        return {"success": True, "status": "unconfirmed", "message": "Order submitted (confirmation unclear)"}

    async def _capture_screenshot(self, name: str) -> Path | None:
        if not self.screenshot_on_failure or not self._page:
            return None
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = self._screenshot_dir / f"{name}_{timestamp}.png"
        try:
            await self._page.screenshot(path=str(path), full_page=True)
            logger.info("screenshot_captured", path=str(path))
            return path
        except Exception as exc:
            logger.error("screenshot_failed", error=str(exc))
            return None

    async def _save_browser_state(self) -> None:
        if self._context:
            profile_dir = PROJECT_ROOT / "config" / "browser_profiles" / self.profile_name
            profile_dir.mkdir(parents=True, exist_ok=True)
            await self._context.storage_state(path=str(profile_dir / "state.json"))

    async def generate_network_report(self) -> Path:
        return self.network.save_report()

    async def shutdown(self) -> None:
        """Clean shutdown of browser resources."""
        if self.simulate:
            self.session.mark_logged_out()
            logger.info("simulated_broker_client_shutdown")
            return

        if self._context:
            try:
                await self._save_browser_state()
            except Exception:
                pass
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        if hasattr(self, "_market_page"):
            self._market_page = None
        self._page = None
        self.session.mark_logged_out()
        logger.info("broker_client_shutdown")

    def get_status(self) -> dict:
        return {
            "profile": self.profile_name,
            "headless": self.headless,
            "broker_url": self.broker_url,
            "session": self.session.get_status(),
            "network_endpoints": len(self.network._endpoints),
        }

    async def capture_live_screenshot(self) -> bytes | None:
        """Capture screenshot of the current active page (or main page) and return bytes."""
        if self.simulate:
            return None

        page_to_capture = None
        # Check Naasa broker specific pages first
        symbol_pages = getattr(self, "_symbol_pages", {})
        if symbol_pages:
            for page in symbol_pages.values():
                if page and not page.is_closed():
                    page_to_capture = page
                    break

        if not page_to_capture:
            market_page = getattr(self, "_market_page", None)
            if market_page and not market_page.is_closed():
                page_to_capture = market_page
            elif self._page and not self._page.is_closed():
                page_to_capture = self._page

        if not page_to_capture:
            return None

        try:
            return await page_to_capture.screenshot(type="png", full_page=False, timeout=5000)
        except Exception as exc:
            logger.error("live_screenshot_capture_failed", error=str(exc))
            return None
