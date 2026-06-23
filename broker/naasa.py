"""Naasa Securities (Naasa X) broker automation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx

from broker.client import BrokerClient
from core.config import get_broker_config, get_settings
from core.events import Event, EventBus, EventType
from core.exceptions import BrokerError, LoginError
from core.logging_config import get_logger

logger = get_logger("naasa_broker")


class NaasaBrokerClient(BrokerClient):
    """
    Naasa X platform automation.

    Platform: https://x.naasasecurities.com.np/
    Auth: Keycloak (email + password) at auth.naasasecurities.com.np
    Trading: Navigate to Order via top navigation after login.
    """

    def __init__(self, event_bus: EventBus, profile_name: str = "naasa", simulate: bool = False):
        super().__init__(event_bus, profile_name=profile_name, simulate=simulate)
        self._broker_profile = get_broker_config()
        profile_config = self._broker_profile.get("profile_config", {})
        urls = profile_config.get("urls", {})

        settings = get_settings()
        self.broker_url = settings.broker_url or urls.get("dashboard", urls.get("base", ""))
        self._auth_domain = urls.get("auth_domain", "auth.naasasecurities.com.np")
        self._order_url = urls.get("order_entry", self.broker_url)
        self._login_config = profile_config.get("login", {})
        self._order_config = profile_config.get("order", {})
        self.selectors = self._broker_profile.get("selectors", self.selectors)
        self._added_symbols: set[str] = set()
        self._fast_buy_clicked = False
        self._fast_buy_click_time = 0.0
        self._market_page_lock = asyncio.Lock()
        self._symbol_pages = {}
        self._last_page_scrape_time: dict[str, datetime] = {}

    async def login(self) -> bool:
        """Login to Naasa X via Keycloak email/password form."""
        if self.simulate:
            logger.info("simulated_naasa_login_success")
            self.session.mark_logged_in()
            return True

        if not self._page or self._page.is_closed():
            await self.initialize()

        try:
            logger.info("naasa_login_start", url=self.broker_url)
            await self._page.goto(self.broker_url, wait_until="domcontentloaded")

            if not await self._is_login_page():
                logger.info("naasa_already_logged_in")
                self.session.mark_logged_in()
                await self._preload_order_page()
                return True

            username_sel = self.selectors.get("username", "#username")
            password_sel = self.selectors.get("password", "#login-password")
            login_btn_sel = self.selectors.get("login_button", "#kc-login")

            await self._page.wait_for_selector(username_sel, timeout=self.timeout)
            await self._page.fill(username_sel, self.username)
            await self._page.fill(password_sel, self.password)

            remember_sel = self.selectors.get("remember_me", "#rememberMe")
            if await self._page.locator(remember_sel).count() > 0:
                await self._page.check(remember_sel)

            async with self._page.expect_navigation(wait_until="domcontentloaded", timeout=60000):
                await self._page.click(login_btn_sel)

            post_wait = self._login_config.get("post_login_wait_ms", 3000) / 1000
            await asyncio.sleep(post_wait)

            if await self._is_login_page():
                await self._capture_screenshot("naasa_login_failed")
                await self.event_bus.publish(
                    Event(
                        type=EventType.LOGIN_FAILURE,
                        source="naasa_broker",
                        data={"reason": "Keycloak login failed — check email/password"},
                    )
                )
                raise LoginError("Naasa X login failed — still on auth page")

            self.session.mark_logged_in()
            await self._save_browser_state()
            # Pre-load order page immediately after login so circuit hit needs zero navigation
            await self._preload_order_page()

            await self.event_bus.publish(
                Event(
                    type=EventType.LOGIN_SUCCESS,
                    source="naasa_broker",
                    data={"profile": self.profile_name, "url": self._page.url},
                )
            )
            logger.info("naasa_login_success", url=self._page.url)
            return True

        except LoginError:
            raise
        except Exception as exc:
            await self._capture_screenshot("naasa_login_error")
            raise LoginError(f"Naasa X login failed: {exc}") from exc

    async def _preload_order_page(self) -> None:
        """Navigate to Order page right after login and stay there.
        This eliminates the ~2 sec page load delay when circuit hits."""
        order_url = self._order_config.get(
            "direct_url",
            "https://x.naasasecurities.com.np/MarketOrder/Order",
        )
        try:
            await self._page.goto(order_url, wait_until="domcontentloaded", timeout=30000)
            symbol_sel = self.selectors.get("order_symbol", "#searchStock")
            await self._page.wait_for_selector(symbol_sel, timeout=10000)
            logger.info("naasa_order_page_preloaded")
        except Exception as exc:
            logger.warning("naasa_order_page_preload_failed", error=str(exc))

    async def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: int,
        price: float | None = None,
    ) -> dict[str, Any]:
        """Place order on Naasa X MarketOrder page (buy-only)."""
        if side != "buy":
            raise BrokerError("Sell orders are disabled — this bot is buy-only")

        if self.simulate:
            logger.info(
                "simulated_naasa_order_placed",
                symbol=symbol,
                side=side,
                type=order_type,
                quantity=quantity,
                price=price,
            )
            return {
                "success": True,
                "status": "submitted",
                "message": "Simulated Naasa order placed successfully",
                "order_id": f"SIM-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            }

        if not self._page or self._page.is_closed():
            self.session.mark_logged_out()

        await self.session.ensure_session(self.login)
        if not self._page:
            raise BrokerError("Browser not initialized")

        self.session.touch()
        logger.info("naasa_placing_order", symbol=symbol, side=side, quantity=quantity)

        try:
            await self._navigate_to_order_page()

            symbol_sel = self.selectors.get("order_symbol", "#searchStock")
            qty_sel = self.selectors.get("order_quantity", "#OrdertxtQty")
            price_sel = self.selectors.get("order_price", "#OrdertxtPrice")

            await self._page.wait_for_selector(symbol_sel, timeout=self.timeout)

            # Buy-only: always use buy tab and buy button
            buy_tab = self.selectors.get("buy_side_tab", "a.buy_frm_order")
            if await self._page.locator(buy_tab).count() > 0:
                await self._page.click(buy_tab)

            # Enter scrip — type, wait for autocomplete dropdown, click first match
            await self._page.fill(symbol_sel, "")
            await self._page.type(symbol_sel, symbol.upper(), delay=80)
            await asyncio.sleep(1)
            # Try clicking the first dropdown suggestion
            dropdown_sel = self._order_config.get("symbol_dropdown_item", ".ui-autocomplete li:first-child, .autocomplete-item:first-child, li.ui-menu-item:first-child")
            try:
                await self._page.wait_for_selector(dropdown_sel, timeout=3000)
                await self._page.click(dropdown_sel)
            except Exception:
                # Fallback: press Enter if no dropdown appears
                await self._page.press(symbol_sel, "Enter")
            await asyncio.sleep(0.5)

            await self._page.fill(qty_sel, str(quantity))

            if order_type == "limit" and price:
                await self._page.click(self.selectors.get("order_type_limit", "#chkOrderTypeLMT"))
                await self._page.fill(price_sel, str(price))
            else:
                await self._page.click(self.selectors.get("order_type_market", "#chkOrderTypeMKT"))

            # Submit buy order only
            submit_sel = self.selectors.get("buy_button", "#btnBuy")
            await self._page.click(submit_sel, force=True)

            timeout = self._order_config.get("confirmation_timeout_ms", 15000)
            await asyncio.sleep(2)
            await self._page.wait_for_load_state("domcontentloaded", timeout=timeout)

            return await self._check_order_confirmation()

        except Exception as exc:
            await self._capture_screenshot(f"naasa_order_error_{symbol}")
            raise BrokerError(f"Naasa X order failed: {exc}") from exc

    async def _navigate_to_order_page(self) -> None:
        """Ensure order page is active. Reset form if already there (saves ~2 sec)."""
        order_url = self._order_config.get(
            "direct_url",
            self._order_url or "https://x.naasasecurities.com.np/MarketOrder/Order",
        )
        if "MarketOrder" in self._page.url:
            # Already on order page — just reset the form, no navigation needed
            reset_sel = self.selectors.get("reset_button", "#btnReset")
            try:
                if await self._page.locator(reset_sel).count() > 0:
                    await self._page.click(reset_sel)
                    await asyncio.sleep(0.3)
            except Exception:
                pass
        else:
            await self._page.goto(order_url, wait_until="domcontentloaded")

    async def _is_login_page(self) -> bool:
        if not self._page:
            return True

        url = self._page.url
        success_pattern = self._login_config.get("wait_for_url_pattern", "x.naasasecurities.com.np")
        exclude = self._login_config.get("success_excludes", self._auth_domain)

        # Logged in: on Naasa X domain, not on Keycloak auth
        if success_pattern in url and exclude not in url:
            login_indicator = self.selectors.get("login_page_indicator", "#username")
            if await self._page.locator(login_indicator).count() == 0:
                return False

        return (
            self._auth_domain in url
            or await self._page.locator(self.selectors.get("username", "#username")).count() > 0
        )

    async def initialize(self) -> None:
        """Launch browser, set up network monitoring, and create second page for market data."""
        await super().initialize()
        if self.simulate:
            return

        # Second page for market data — keeps order page untouched during monitoring
        self._market_page = await self._context.new_page()
        await self._market_page.route("**/*", self._route_filter)
        self._market_page.on("websocket", self.network.on_websocket)
        logger.info("naasa_market_page_created")

        # Initialize persistent HTTP client for ultra-fast direct API submissions
        self._http_client = httpx.AsyncClient(timeout=10.0)

    async def shutdown(self) -> None:
        """Clean shutdown of broker resources."""
        if hasattr(self, "_http_client") and self._http_client:
            try:
                await self._http_client.aclose()
                logger.info("naasa_http_client_closed")
            except Exception as e:
                logger.warning("failed_to_close_naasa_http_client", error=str(e))
            self._http_client = None
        if hasattr(self, "_symbol_pages"):
            self._symbol_pages.clear()
        await super().shutdown()

    async def get_market_data(self, symbol: str) -> dict[str, Any] | None:
        """Fetch live quote from Naasa X Market Watch on second page."""
        if self.simulate:
            return {
                "symbol": symbol.upper(),
                "ltp": 100.0,
                "prev_close": 100.0,
                "source": "simulated",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        if not self._page or self._page.is_closed() or (hasattr(self, "_market_page") and (not self._market_page or self._market_page.is_closed())):
            self.session.mark_logged_out()

        await self.session.ensure_session(self.login)
        if not self._page:
            return None

        self.session.touch()

        # Try WebSocket cache first
        ws_data = await self._parse_ws_quote(symbol)

        # Determine if we should perform a browser page scrape (throttled to 1.5 seconds)
        now = datetime.now(timezone.utc)
        last_scrape = self._last_page_scrape_time.get(symbol.upper(), datetime.min.replace(tzinfo=timezone.utc))
        should_scrape = (now - last_scrape).total_seconds() >= 1.5

        symbol_page = getattr(self, "_symbol_pages", {}).get(symbol.upper(), None)
        if not symbol_page and self._page and not self._page.is_closed() and "MarketOrder" in self._page.url:
            try:
                search_val = await self._page.locator("#searchStock").input_value()
                if search_val.upper() == symbol.upper():
                    symbol_page = self._page
            except Exception:
                pass

        if ws_data:
            # If we have WebSocket data, only scrape high_limit from the page occasionally
            if should_scrape and symbol_page and not symbol_page.is_closed() and "MarketOrder" in symbol_page.url:
                self._last_page_scrape_time[symbol.upper()] = now
                try:
                    page_data = await symbol_page.evaluate(
                        r"""() => {
                            const parse = v => parseFloat(String(v).replace(/,/g, '')) || 0;
                            let high_limit = 0;
                            let ltp = 0;
                            
                            const elements = document.querySelectorAll('span, div, h1, h2, h3, h4, h5, h6, label');
                            for (const el of elements) {
                                const txt = el.innerText ? el.innerText.trim() : '';
                                if (txt.includes('Low-High:')) {
                                    const match = txt.match(/Low-High:\s*([\d\.,]+)\s*-\s*([\d\.,]+)/i);
                                    if (match) {
                                        high_limit = parse(match[2]);
                                        break;
                                    }
                                }
                            }
                            
                            const rows = document.querySelectorAll('tr');
                            for (const row of rows) {
                                const text = row.innerText.trim();
                                if (text.includes('D.High') || text.includes('High')) {
                                    const cells = row.querySelectorAll('td');
                                    if (cells.length >= 2) {
                                        ltp = parse(cells[1].innerText);
                                        break;
                                    }
                                }
                            }
                            return { high_limit, ltp };
                        }"""
                    )
                    if page_data:
                        page_high_limit = page_data.get("high_limit", 0.0)
                        if page_high_limit > 0.0:
                            if not hasattr(self, "_cached_high_limit"):
                                self._cached_high_limit = {}
                            self._cached_high_limit[symbol.upper()] = page_high_limit
                            ws_data["high_limit"] = max(ws_data.get("high_limit", 0.0), page_high_limit)
                        
                        if page_data.get("ltp", 0.0) > 0.0:
                            ws_data["ltp"] = max(ws_data.get("ltp", 0.0), page_data["ltp"])
                except Exception as exc:
                    logger.debug("failed_to_scrape_order_page_high_limit", symbol=symbol, error=str(exc))

            if "high_limit" not in ws_data or ws_data["high_limit"] <= 0.0:
                cached_high = getattr(self, "_cached_high_limit", {}).get(symbol.upper(), 0.0)
                if cached_high > 0.0:
                    ws_data["high_limit"] = cached_high
            return ws_data

        # Try scraping from the active order page second (only if we should scrape)
        if should_scrape and symbol_page and not symbol_page.is_closed() and "MarketOrder" in symbol_page.url:
            self._last_page_scrape_time[symbol.upper()] = now
            try:
                data = await symbol_page.evaluate(
                    r"""(sym) => {
                        const searchInput = document.querySelector("#searchStock");
                        if (!searchInput || !searchInput.value.toUpperCase().includes(sym.toUpperCase())) {
                            return null;
                        }
                        const parse = v => parseFloat(String(v).replace(/,/g, '')) || 0;
                        const rows = document.querySelectorAll('tr');
                        let prev_close = 0;
                        let ltp = 0;
                        let high_limit = 0;
                        
                        for (const row of rows) {
                            const text = row.innerText.trim();
                            if (text.includes('P.Close')) {
                                const cells = row.querySelectorAll('td');
                                if (cells.length >= 2) {
                                    prev_close = parse(cells[1].innerText);
                                }
                            }
                        }
                        
                        const elements = document.querySelectorAll('span, div, h1, h2, h3, h4, h5, h6, label');
                        for (const el of elements) {
                            const txt = el.innerText.trim().toUpperCase();
                            if ((txt === sym.toUpperCase() || txt.startsWith(sym.toUpperCase() + ' ')) && txt.length < 50) {
                                const parentText = el.parentElement ? el.parentElement.innerText : el.innerText;
                                const match = parentText.match(/(\d+\.?\d*)\s*[▲▼]/) || 
                                              parentText.match(/(\d+\.?\d*)\s+\d+\.\d+\s*\(/) ||
                                              parentText.match(new RegExp(sym.toUpperCase() + '\\s+(\\d+\\.?\\d*)'));
                                if (match) {
                                    ltp = parse(match[1]);
                                    break;
                                }
                            }
                        }
                        
                        if (!ltp) {
                            for (const row of rows) {
                                const text = row.innerText.trim();
                                if (text.includes('D.High') || text.includes('High')) {
                                    const cells = row.querySelectorAll('td');
                                    if (cells.length >= 2) {
                                        ltp = parse(cells[1].innerText);
                                        break;
                                    }
                                }
                            }
                        }

                        for (const el of elements) {
                            const txt = el.innerText ? el.innerText.trim() : '';
                            if (txt.includes('Low-High:')) {
                                const match = txt.match(/Low-High:\s*([\d\.,]+)\s*-\s*([\d\.,]+)/i);
                                if (match) {
                                    high_limit = parse(match[2]);
                                    break;
                                }
                            }
                        }
                        
                        return { ltp, prev_close, high_limit };
                    }""",
                    symbol.upper(),
                )
                if data and data.get("ltp") > 0:
                    if not hasattr(self, "_cached_high_limit"):
                        self._cached_high_limit = {}
                    self._cached_high_limit[symbol.upper()] = data.get("high_limit", 0.0)

                    from market_data.circuit import calculate_daily_circuits
                    prev_close = data.get("prev_close") or 0.0
                    high_limit = data.get("high_limit", 0.0)
                    
                    if prev_close > 0:
                        circuits = calculate_daily_circuits(prev_close, 15.0)
                        upper_circuit = circuits.upper_circuit
                        lower_circuit = circuits.lower_circuit
                    else:
                        upper_circuit = high_limit
                        lower_circuit = 0.0

                    return {
                        "symbol": symbol.upper(),
                        "ltp": data["ltp"],
                        "prev_close": prev_close,
                        "upper_circuit": upper_circuit,
                        "lower_circuit": lower_circuit,
                        "high_limit": high_limit,
                        "source": "naasa_order_page_scrape",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
            except Exception as exc:
                logger.debug("failed_to_scrape_order_page_price", symbol=symbol, error=str(exc))

        # Fetch from Market Watch on second page third (with 2-second throttling)
        now = datetime.now(timezone.utc)
        last_mw_time = getattr(self, "_last_mw_time", datetime.min.replace(tzinfo=timezone.utc))
        if (now - last_mw_time).total_seconds() >= 2.0:
            self._last_mw_time = now
            return await self._fetch_market_watch_quote(symbol)

        return None

    async def _fetch_market_watch_quote(self, symbol: str) -> dict[str, Any] | None:
        """Parse symbol row from Naasa X Market Watch HTML table (uses second page)."""
        if self._market_page_lock.locked():
            logger.debug("skipping_market_watch_fetch_lock_busy", symbol=symbol)
            return None

        async with self._market_page_lock:
            page = getattr(self, "_market_page", None)
            if not page or page.is_closed():
                if self._context:
                    try:
                        self._market_page = await self._context.new_page()
                        await self._market_page.route("**/*", self._route_filter)
                        page = self._market_page
                        logger.info("recreated_market_page")
                    except Exception as exc:
                        logger.warning("failed_to_recreate_market_page", error=str(exc))
                        return None
                else:
                    return None

            market_url = "https://x.naasasecurities.com.np/MarketWatch"
            if "MarketWatch" not in page.url:
                try:
                    await page.goto(market_url, wait_until="domcontentloaded", timeout=15000)
                    await asyncio.sleep(1)
                except Exception as exc:
                    logger.warning("failed_to_navigate_market_page", error=str(exc))
                    return None

            row = await page.evaluate(
                """(sym) => {
                    const parse = v => parseFloat(String(v).replace(/,/g, '')) || 0;
                    const parseI = v => parseInt(String(v).replace(/,/g, '')) || 0;
                    // Try table rows first (most common Naasa X layout)
                    const rows = document.querySelectorAll('table tbody tr, #marketTable tbody tr, .market-table tbody tr');
                    for (const row of rows) {
                        const cells = row.querySelectorAll('td');
                        if (!cells.length) continue;
                        const symbolCell = cells[0].innerText.trim();
                        if (symbolCell.toUpperCase() !== sym.toUpperCase()) continue;
                        if (cells.length >= 7) {
                            return {
                                symbol: sym,
                                ltp:        parse(cells[1]?.innerText),
                                open_price: parse(cells[2]?.innerText || cells[4]?.innerText),
                                high_price: parse(cells[3]?.innerText || cells[5]?.innerText),
                                low_price:  parse(cells[4]?.innerText || cells[6]?.innerText),
                                volume:     parseI(cells[5]?.innerText || cells[7]?.innerText),
                                prev_close: parse(cells[6]?.innerText || cells[8]?.innerText),
                            };
                        }
                    }
                    return null;
                }""",
                symbol.upper(),
            )

            if not row:
                # If symbol not in MarketWatch table, try filtering or adding it (only once per symbol)
                if symbol.upper() not in self._added_symbols:
                    self._added_symbols.add(symbol.upper())

                    # Try filtering the regular table first using the always-visible searchInput filter
                    table_search_sel = "#searchInput"
                    try:
                        if await page.locator(table_search_sel).count() > 0:
                            logger.info("filtering_market_watch_table_by_symbol", symbol=symbol)
                            await page.locator(table_search_sel).click(timeout=2000)
                            await page.locator(table_search_sel).fill("")
                            await page.locator(table_search_sel).type(symbol.upper(), delay=50, timeout=2000)
                            await asyncio.sleep(1.5)

                            # Re-evaluate row after filtering
                            row = await page.evaluate(
                                """(sym) => {
                                    const parse = v => parseFloat(String(v).replace(/,/g, '')) || 0;
                                    const parseI = v => parseInt(String(v).replace(/,/g, '')) || 0;
                                    const rows = document.querySelectorAll('table tbody tr, #marketTable tbody tr, .market-table tbody tr');
                                    for (const row of rows) {
                                        const cells = row.querySelectorAll('td');
                                        if (!cells.length) continue;
                                        const symbolCell = cells[0].innerText.trim();
                                        if (symbolCell.toUpperCase() !== sym.toUpperCase()) continue;
                                        if (cells.length >= 7) {
                                            return {
                                                symbol: sym,
                                                ltp:        parse(cells[1]?.innerText),
                                                open_price: parse(cells[2]?.innerText || cells[4]?.innerText),
                                                high_price: parse(cells[3]?.innerText || cells[5]?.innerText),
                                                low_price:  parse(cells[4]?.innerText || cells[6]?.innerText),
                                                volume:     parseI(cells[5]?.innerText || cells[7]?.innerText),
                                                prev_close: parse(cells[6]?.innerText || cells[8]?.innerText),
                                            };
                                        }
                                    }
                                    return null;
                                }""",
                                symbol.upper(),
                            )
                    except Exception as exc:
                        logger.warning("failed_to_filter_market_watch_table", symbol=symbol, error=str(exc))

                    # Fallback to custom watchlist search (#txtAddTicker) only if #searchInput is not found or failed
                    if not row:
                        search_sel = self.selectors.get("watchlist_search", "#txtAddTicker")
                        try:
                            if await page.locator(search_sel).count() > 0:
                                logger.info("symbol_not_found_in_market_watch_attempting_to_add", symbol=symbol)
                                await page.locator(search_sel).click(timeout=2000)
                                await page.locator(search_sel).press("Control+A", timeout=1000)
                                await page.locator(search_sel).press("Backspace", timeout=1000)
                                await asyncio.sleep(0.2)
                                await page.locator(search_sel).type(symbol.upper(), delay=100, timeout=2000)
                                await asyncio.sleep(1.0)

                                # Click autocomplete suggestion if present, otherwise press Enter
                                dropdown_sel = self._order_config.get("symbol_dropdown_item", ".ui-autocomplete li:first-child, .autocomplete-item:first-child, li.ui-menu-item:first-child")
                                try:
                                    if await page.locator(dropdown_sel).count() > 0:
                                        await page.click(dropdown_sel, timeout=1000)
                                    else:
                                        await page.press(search_sel, "Enter", timeout=1000)
                                except Exception:
                                    await page.press(search_sel, "Enter", timeout=1000)
                                await asyncio.sleep(1.5)

                                # Re-evaluate row after adding
                                row = await page.evaluate(
                                    """(sym) => {
                                        const parse = v => parseFloat(String(v).replace(/,/g, '')) || 0;
                                        const parseI = v => parseInt(String(v).replace(/,/g, '')) || 0;
                                        const rows = document.querySelectorAll('table tbody tr, #marketTable tbody tr, .market-table tbody tr');
                                        for (const row of rows) {
                                            const cells = row.querySelectorAll('td');
                                            if (!cells.length) continue;
                                            const symbolCell = cells[0].innerText.trim();
                                            if (symbolCell.toUpperCase() !== sym.toUpperCase()) continue;
                                            if (cells.length >= 7) {
                                                return {
                                                    symbol: sym,
                                                    ltp:        parse(cells[1]?.innerText),
                                                    open_price: parse(cells[2]?.innerText || cells[4]?.innerText),
                                                    high_price: parse(cells[3]?.innerText || cells[5]?.innerText),
                                                    low_price:  parse(cells[4]?.innerText || cells[6]?.innerText),
                                                    volume:     parseI(cells[5]?.innerText || cells[7]?.innerText),
                                                    prev_close: parse(cells[6]?.innerText || cells[8]?.innerText),
                                                };
                                            }
                                        }
                                        return null;
                                    }""",
                                    symbol.upper(),
                                )
                        except Exception as exc:
                            logger.warning("failed_to_add_symbol_to_market_watch", symbol=symbol, error=str(exc))

        if not row:
            return None

        from market_data.circuit import calculate_daily_circuits

        prev_close = row.get("prev_close") or 0.0
        circuits = calculate_daily_circuits(prev_close, 15.0)

        return {
            "symbol": symbol.upper(),
            "ltp": row["ltp"],
            "prev_close": prev_close,
            "open_price": row.get("open_price", 0),
            "high_price": row.get("high_price", 0),
            "low_price": row.get("low_price", 0),
            "volume": row.get("volume", 0),
            "upper_circuit": circuits.upper_circuit,
            "lower_circuit": circuits.lower_circuit,
            "source": "naasa_market_watch",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _parse_ws_quote(self, symbol: str) -> dict[str, Any] | None:
        """Look up symbol in real-time parsed WebSocket cache."""
        cached = getattr(self.network, "ws_cache", {}).get(symbol.upper())
        if cached:
            data = cached["data"]
            parsed = self._parse_naasa_quote(symbol, data)
            if parsed:
                return parsed
        return None

    def _parse_naasa_quote(self, symbol: str, data: dict) -> dict[str, Any] | None:
        """Best-effort parse of Naasa X market data JSON."""
        for key in ("ltp", "lastTradedPrice", "last_price", "price"):
            if key in data:
                return {
                    "symbol": symbol,
                    "ltp": float(data[key]),
                    "bid_quantity": int(data.get("bidQty", data.get("bid_quantity", 0))),
                    "ask_quantity": int(data.get("askQty", data.get("ask_quantity", 0))),
                    "volume": int(data.get("volume", data.get("tradedQty", 0))),
                    "upper_circuit": float(data.get("upperCircuit", data.get("upper_circuit", 0))),
                    "prev_close": float(data.get("previousClose", data.get("prevClose", data.get("prev_close", 0.0)))),
                    "source": "naasa_x_network",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
        return None

    async def stage_order(self, symbol: str, quantity: int, price: float) -> bool:
        """Pre-fill the order form with scrip, quantity, and limit price."""
        if self.simulate:
            logger.info("simulated_naasa_order_staged_successfully", symbol=symbol, price=price)
            return True

        if not self._page or self._page.is_closed():
            self.session.mark_logged_out()
            await self.session.ensure_session(self.login)

        if not self._page:
            raise BrokerError("Browser not initialized")

        sym = symbol.upper()
        if not hasattr(self, "_symbol_pages"):
            self._symbol_pages = {}

        if sym not in self._symbol_pages:
            if not self._symbol_pages:
                self._symbol_pages[sym] = self._page
                page = self._page
                logger.info("allocated_main_page_for_symbol", symbol=sym)
            else:
                try:
                    page = await self._context.new_page()
                    await page.route("**/*", self._route_filter)
                    page.on("request", self.network.on_request)
                    page.on("response", lambda r: asyncio.create_task(self.network.on_response(r)))
                    page.on("websocket", self.network.on_websocket)
                    self._symbol_pages[sym] = page
                    logger.info("allocated_new_tab_for_symbol", symbol=sym)
                except Exception as exc:
                    logger.error("failed_to_create_new_tab_for_symbol", symbol=sym, error=str(exc))
                    page = self._page
        else:
            page = self._symbol_pages[sym]

        logger.info("naasa_staging_order", symbol=sym, quantity=quantity, price=price)
        try:
            order_url = self._order_config.get(
                "direct_url",
                self._order_url or "https://x.naasasecurities.com.np/MarketOrder/Order",
            )
            if "MarketOrder" in page.url:
                reset_sel = self.selectors.get("reset_button", "#btnReset")
                try:
                    if await page.locator(reset_sel).count() > 0:
                        await page.click(reset_sel)
                        await asyncio.sleep(0.3)
                except Exception:
                    pass
            else:
                await page.goto(order_url, wait_until="domcontentloaded")

            symbol_sel = self.selectors.get("order_symbol", "#searchStock")
            qty_sel = self.selectors.get("order_quantity", "#OrdertxtQty")
            price_sel = self.selectors.get("order_price", "#OrdertxtPrice")

            await page.wait_for_selector(symbol_sel, timeout=self.timeout)

            # Buy-only: always use buy tab
            buy_tab = self.selectors.get("buy_side_tab", "a.buy_frm_order")
            if await page.locator(buy_tab).count() > 0:
                await page.click(buy_tab)

            # Enter scrip — clear field and type reliably to trigger autocomplete
            await page.locator(symbol_sel).click()
            await page.locator(symbol_sel).press("Control+A")
            await page.locator(symbol_sel).press("Backspace")
            await asyncio.sleep(0.2)
            await page.locator(symbol_sel).type(sym, delay=120)
            await asyncio.sleep(1.2)

            dropdown_sel = self._order_config.get("symbol_dropdown_item", ".ui-autocomplete li:first-child, .autocomplete-item:first-child, li.ui-menu-item:first-child")
            try:
                await page.wait_for_selector(dropdown_sel, timeout=3000)
                await page.click(dropdown_sel)
            except Exception:
                await page.press(symbol_sel, "ArrowDown")
                await asyncio.sleep(0.2)
                await page.press(symbol_sel, "Enter")
            await asyncio.sleep(0.5)

            await page.fill(qty_sel, str(quantity))

            # Select limit order type (LMT) and enter price (using force=True as the input element may be styled/hidden)
            await page.locator(self.selectors.get("order_type_limit", "#chkOrderTypeLMT")).click(force=True)
            await page.fill(price_sel, str(price))

            logger.info("naasa_order_staged_successfully", symbol=sym, price=price)
            return True
        except Exception as exc:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            path = self._screenshot_dir / f"naasa_stage_error_{sym}_{timestamp}.png"
            try:
                await page.screenshot(path=str(path), full_page=True)
                logger.info("screenshot_captured", path=str(path))
            except Exception:
                pass
            logger.error("naasa_order_staging_failed", symbol=sym, error=str(exc))
            return False

    async def fast_trigger_buy(
        self,
        symbol: str,
        quantity: int,
        price: float,
        kill_switch: bool = True,
        scrip_id: str | None = None,
        exchange: str | None = None,
        cookies: dict | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        """
        Submit order directly via POST request bypassing Playwright clicks entirely.
        """
        if self.simulate:
            if kill_switch:
                logger.warning("fast_trigger_skipped_kill_switch_active")
                return {"success": False, "error": "Kill switch active"}
            logger.info("simulated_naasa_fast_trigger_buy_success", symbol=symbol, price=price)
            return {
                "success": True,
                "status": "submitted",
                "message": "Simulated fast trigger buy success",
                "order_id": f"SIM-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            }

        symbol_page = getattr(self, "_symbol_pages", {}).get(symbol.upper(), self._page)
        if not symbol_page or symbol_page.is_closed():
            return {"success": False, "error": "Browser not initialized or closed"}

        if kill_switch:
            logger.warning("fast_trigger_skipped_kill_switch_active")
            return {"success": False, "error": "Kill switch active"}

        try:
            # 1. Extract dynamic variables from page context
            if not scrip_id:
                scrip_id = await symbol_page.evaluate("Selected_scrip")
            if not exchange:
                exchange = await symbol_page.evaluate("Selected_Exchange")
            
            if not scrip_id or not exchange:
                logger.warning("missing_dynamic_scrip_id_or_exchange", scrip_id=scrip_id, exchange=exchange)
                return {"success": False, "reason": "staged_order_not_fully_resolved"}

            # 2. Extract active cookies from browser context
            if not cookies:
                playwright_cookies = await self._context.cookies()
                cookies = {c["name"]: c["value"] for c in playwright_cookies if "naasasecurities.com.np" in c["domain"]}

            # 3. Get the user agent from browser to match headers
            if not user_agent:
                user_agent = await symbol_page.evaluate("navigator.userAgent")

            # 4. Build headers
            headers = {
                "Content-Type": "application/json; charset=utf-8",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://x.naasasecurities.com.np/MarketOrder/Order",
                "User-Agent": user_agent,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "en-US,en;q=0.9",
                "Origin": "https://x.naasasecurities.com.np",
            }

            # 6. Build the payload matching the extracted JS template
            payload = {
                "TradingAccount": "CNC",
                "Exchange": exchange,
                "Scrip": str(scrip_id),
                "Quantity": str(quantity),
                "Price": str(price),
                "Market": "0" if price > 0.0 else "1",
                "OrderTerms": "DAY",
                "BuySellIndicator": "B",
                "BuySellType": "Buy",
                "DeliveryTerms": "D",
                "MarketSegment": "RL",
                "OrderCategory": "NORMAL",
                "OrderType": "NORMAL",
                "AccRefCode": "SELF",
                "TermValidity": "",
                "ProductType": "CASH",
                "DisclosedQuantity": "",
                "isSquareOff": 0
            }

            logger.info(
                "fast_trigger_sending_api_request",
                symbol=symbol,
                scrip_id=scrip_id,
                exchange=exchange,
                quantity=quantity,
                price=price
            )

            # 7. Execute direct HTTP POST request
            if not hasattr(self, "_http_client") or self._http_client is None:
                self._http_client = httpx.AsyncClient(timeout=10.0)

            response = await self._http_client.post(
                "https://x.naasasecurities.com.np/MarketOrder/Order",
                json=payload,
                cookies=cookies,
                headers=headers,
            )

            # 8. Handle Response
            if response.status_code != 200:
                logger.warning("fast_trigger_api_http_error", status_code=response.status_code, body=response.text[:200])
                return {"success": False, "reason": "http_error", "message": f"HTTP status {response.status_code}"}

            try:
                res_json = response.json()
            except ValueError:
                logger.warning("fast_trigger_api_non_json_response", body=response.text[:200])
                return {"success": False, "reason": "non_json_response", "message": response.text[:200]}

            error_code = res_json.get("errorCode")
            if error_code is None:
                error_code = res_json.get("ErrorCode")

            message = res_json.get("message") or res_json.get("Message") or ""
            data = res_json.get("data") or res_json.get("Data") or res_json.get("TranId") or ""

            msg_lower = (str(message) + " " + str(data)).lower()
            is_success = error_code == 0 or any(w in msg_lower for w in ("success", "placed", "submitted", "accepted"))
            is_rejected = any(w in msg_lower for w in ("error", "fail", "reject", "invalid", "insufficient", "cannot", "not enough", "exceeded", "closed"))

            if is_success and not (is_rejected and error_code != 0):
                logger.critical("fast_trigger_api_order_success", message=message, data=data)
                return {
                    "success": True,
                    "status": "submitted",
                    "message": message,
                    "order_id": data if data else f"NAASA-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
                }
            else:
                reason = "broker_api_error"
                if "closed" in msg_lower:
                    reason = "market_closed"
                logger.warning("fast_trigger_api_order_failed", errorCode=error_code, message=message, data=data, response_json=res_json)
                return {
                    "success": False,
                    "reason": reason,
                    "message": f"{message} {data}".strip()
                }

        except Exception as exc:
            logger.error("fast_trigger_api_exception", error=str(exc))
            return {"success": False, "error": str(exc)}



    async def _check_order_confirmation_fast(self) -> dict[str, Any]:
        """Detect confirmation instantly without sleeping."""
        if not self._page:
            return {"success": False, "message": "No page"}

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

        # Check page text
        try:
            body = (await self._page.inner_text("body")).lower()
            if any(w in body for w in ("order placed", "order submitted", "successfully")):
                return {"success": True, "status": "submitted", "message": "Order submitted",
                        "order_id": f"NAASA-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"}
        except Exception:
            pass

        return {"success": False, "status": "pending"}


def create_broker_client(event_bus: EventBus, simulate: bool = False) -> BrokerClient:
    """Factory: return broker client for configured profile."""
    settings = get_settings()
    profile = settings.broker_profile

    if profile == "naasa":
        return NaasaBrokerClient(event_bus, profile_name="naasa", simulate=simulate)
    return BrokerClient(event_bus, profile_name=profile or "default", simulate=simulate)
