"""Network traffic analysis for WebSocket and XHR monitoring."""

from __future__ import annotations

import json
import base64
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.config import PROJECT_ROOT
from core.logging_config import get_logger

DEFAULT_SCHEMAS = {
    "1": ["LTP", "LTQ", "LastTradeTime", "TTQ", "WeightedAverage", "BidPrice", "OfferPrice", "BidQty", "OfferQty", "TotalBuyQty", "TotalSellQty", "High", "Low", "Open", "Close"],
    "75": ["LTP", "LTQ", "LastTradeTime", "TTQ", "WeightedAverage", "BidPrice", "OfferPrice", "BidQty", "OfferQty", "TotalBuyQty", "TotalSellQty", "High", "Low", "Open", "Close"],
    "78": ["LowerCKTLimit", "UpperCKTLimit", "52WeekHigh", "52WeekLow"],
    "74": ["TTQ", "TTV", "TradedSymbolCount", "LTP", "High", "Low", "Open", "Close"],
    "77": ["LTP", "High", "Low", "Open", "Close", "52WeekHigh", "52WeekLow", "TTQ", "TTV", "LTV", "TradedSymbolCount", "LastTradeTime"],
    "2": ["BestBuyRate", "BestBuyQty", "BuyOrders", "BestSellRate", "BestSellQty", "SellOrders"],
    "76": ["BestBuyRate", "BestBuyQty", "BuyOrders", "BestSellRate", "BestSellQty", "SellOrders"]
}

logger = get_logger("network_analyzer")


@dataclass
class CapturedRequest:
    """Captured HTTP/WebSocket request metadata."""

    url: str
    method: str
    resource_type: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    request_headers: dict[str, str] = field(default_factory=dict)
    request_body: str | None = None
    response_status: int | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    response_body: str | None = None
    auth_token: str | None = None


@dataclass
class EndpointReport:
    """Technical report for a discovered API endpoint."""

    url: str
    method: str
    resource_type: str
    auth_method: str = "unknown"
    request_structure: dict | None = None
    response_structure: dict | None = None
    sample_count: int = 0
    is_websocket: bool = False
    is_market_data: bool = False


class NetworkAnalyzer:
    """
    Inspect WebSocket traffic, monitor XHR requests,
    capture API endpoints, and analyze authentication tokens.
    """

    MARKET_DATA_PATTERNS = [
        "market", "quote", "ltp", "depth", "ticker", "price",
        "nepse", "stock", "symbol", "orderbook",
    ]
    AUTH_HEADER_PATTERNS = ["authorization", "x-auth", "token", "bearer", "session"]

    def __init__(self, report_dir: Path | None = None, event_bus: Any = None):
        self.report_dir = report_dir or PROJECT_ROOT / "logs" / "network_reports"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self._captured: list[CapturedRequest] = []
        self._endpoints: dict[str, EndpointReport] = {}
        self._ws_messages: list[dict] = []
        self._auth_tokens: dict[str, str] = {}
        self.ws_cache: dict[str, dict] = {}
        self.event_bus = event_bus
        self.full_bearer_token: str | None = None
        self.last_auth_headers: dict[str, str] = {}
        self._schemas: dict[str, list[str]] = {}

    def on_request(self, request) -> None:
        """Playwright request handler."""
        try:
            headers = dict(request.headers) if request.headers else {}
            auth_token = self._extract_auth(headers)

            # Capture full bearer token if present
            for key, val in headers.items():
                if key.lower() == 'authorization' and val.lower().startswith('bearer '):
                    self.full_bearer_token = val
                    self.last_auth_headers = headers.copy()

            captured = CapturedRequest(
                url=request.url,
                method=request.method,
                resource_type=request.resource_type,
                request_headers=headers,
                auth_token=auth_token,
            )

            if auth_token:
                self._auth_tokens[request.url] = auth_token

            self._captured.append(captured)
            self._update_endpoint_report(captured)

        except Exception as exc:
            logger.debug("request_capture_error", error=str(exc))

    async def on_response(self, response) -> None:
        """Playwright response handler."""
        try:
            request = response.request
            url = request.url

            # Find matching captured request
            for cap in reversed(self._captured):
                if cap.url == url and cap.response_status is None:
                    cap.response_status = response.status
                    cap.response_headers = dict(response.headers) if response.headers else {}

                    content_type = cap.response_headers.get("content-type", "")
                    if "json" in content_type and response.status < 400:
                        try:
                            body = await response.text()
                            cap.response_body = body[:10000]  # Limit size
                            self._update_response_structure(cap, body)
                        except Exception:
                            pass
                    break

        except Exception as exc:
            logger.debug("response_capture_error", error=str(exc))

    def on_websocket(self, ws) -> None:
        """Playwright WebSocket handler."""
        url = ws.url
        logger.info("websocket_detected", url=url)

        endpoint_key = f"WS:{url}"
        if endpoint_key not in self._endpoints:
            self._endpoints[endpoint_key] = EndpointReport(
                url=url,
                method="WEBSOCKET",
                resource_type="websocket",
                is_websocket=True,
                is_market_data=self._is_market_data_url(url),
                auth_method=self._detect_ws_auth(url),
            )

        def decode_payload(payload) -> str:
            if isinstance(payload, bytes):
                try:
                    return payload.decode("utf-8", errors="ignore")
                except Exception:
                    return str(payload)
            return str(payload)

        def on_frame_sent(payload):
            payload_str = decode_payload(payload)
            self._ws_messages.append({
                "direction": "sent",
                "url": url,
                "payload": payload_str[:5000],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            if len(self._ws_messages) > 500:
                self._ws_messages = self._ws_messages[-500:]

        def on_frame_received(payload):
            payload_str = decode_payload(payload)
            self._ws_messages.append({
                "direction": "received",
                "url": url,
                "payload": payload_str[:5000],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            if len(self._ws_messages) > 500:
                self._ws_messages = self._ws_messages[-500:]
            self._endpoints[endpoint_key].sample_count += 1

            # Parse and cache WebSocket messages in real-time
            try:
                frames_to_process = []
                if payload_str.startswith('a['):
                    try:
                        outer_msg = json.loads(payload_str[1:])
                        if isinstance(outer_msg, list):
                            frames_to_process.extend(outer_msg)
                    except Exception:
                        pass
                elif payload_str.startswith('{') or payload_str.startswith('['):
                    try:
                        inner_data = json.loads(payload_str)
                        self._cache_json_msg(inner_data)
                    except Exception:
                        pass
                else:
                    frames_to_process.append(payload_str)

                for frame in frames_to_process:
                    if not isinstance(frame, str):
                        continue
                    
                    decompressed_text = None
                    # Check if compressed with caret prefix e.g., "102^eJx..." or "101^..."
                    if "^" in frame:
                        parts = frame.split("^", 1)
                        b64_str = parts[1]
                        
                        # Add padding if needed
                        missing_padding = len(b64_str) % 4
                        if missing_padding:
                            b64_str += '=' * (4 - missing_padding)
                            
                        try:
                            compressed_bytes = base64.b64decode(b64_str)
                            try:
                                decompressed_text = zlib.decompress(compressed_bytes).decode("utf-8", errors="ignore")
                            except Exception:
                                decompressed_text = zlib.decompress(compressed_bytes, -zlib.MAX_WBITS).decode("utf-8", errors="ignore")
                        except Exception as e:
                            logger.debug("websocket_frame_decompress_error", error=str(e))
                            continue
                    else:
                        decompressed_text = frame
                        
                    if not decompressed_text:
                        continue
                        
                    # Process decompressed lines (might be multiple, separated by newline)
                    for line in decompressed_text.splitlines():
                        line = line.strip()
                        if not line:
                            continue
                            
                        # Schema definition line (e.g. "75#LTP^High^..." or "75#LTP^...|76#...")
                        if "#" in line and not line.startswith("1$") and not line.startswith("2$"):
                            sub_parts = line.split("|")
                            for sp in sub_parts:
                                if "#" in sp:
                                    sp_id, sp_fields = sp.split("#", 1)
                                    self._schemas[sp_id] = [f.strip() for f in sp_fields.split("^") if f.strip()]
                            continue
                            
                        # Data update line (e.g. "1$75$25.1!HBL$datetime$value1^value2...")
                        if line.startswith("1$") or line.startswith("2$"):
                            parts = line.split("$")
                            if len(parts) >= 5:
                                action = parts[0]
                                schema_id = parts[1]
                                symbol_raw = parts[2]
                                server_time = parts[3]
                                values_str = parts[4]
                                
                                symbol = symbol_raw
                                if "!" in symbol_raw:
                                    symbol = symbol_raw.split("!")[-1]
                                symbol = symbol.upper()
                                
                                fields = self._schemas.get(schema_id) or DEFAULT_SCHEMAS.get(schema_id)
                                if fields and values_str:
                                    values = values_str.split("^")
                                    data_dict = {}
                                    for idx, field in enumerate(fields):
                                        if idx < len(values):
                                            data_dict[field] = values[idx]
                                    
                                    # Normalize data dict to standard keys
                                    normalized = {
                                        "symbol": symbol,
                                        "ltp": float(str(data_dict.get("LTP", 0.0)).replace(",", "")) if data_dict.get("LTP") else 0.0,
                                        "bid_quantity": int(str(data_dict.get("TotalBuyQty", data_dict.get("BidQty", 0))).replace(",", "")) if data_dict.get("TotalBuyQty") or data_dict.get("BidQty") else 0,
                                        "ask_quantity": int(str(data_dict.get("TotalSellQty", data_dict.get("OfferQty", 0))).replace(",", "")) if data_dict.get("TotalSellQty") or data_dict.get("OfferQty") else 0,
                                        "volume": int(str(data_dict.get("TTQ", data_dict.get("Volume", 0))).replace(",", "")) if data_dict.get("TTQ") or data_dict.get("Volume") else 0,
                                        "prev_close": float(str(data_dict.get("Close", 0.0)).replace(",", "")) if data_dict.get("Close") else 0.0,
                                        "upper_circuit": float(str(data_dict.get("UpperCKTLimit", 0.0)).replace(",", "")) if data_dict.get("UpperCKTLimit") else 0.0,
                                        "lower_circuit": float(str(data_dict.get("LowerCKTLimit", 0.0)).replace(",", "")) if data_dict.get("LowerCKTLimit") else 0.0,
                                        "source": "naasa_x_websocket",
                                        "timestamp": datetime.now(timezone.utc),
                                    }
                                    
                                    self.ws_cache[symbol] = {
                                        "data": normalized,
                                        "timestamp": datetime.now(timezone.utc),
                                    }
                                    
                                    if self.event_bus:
                                        import asyncio
                                        from core.events import Event, EventType
                                        event_data = {
                                            "symbol": symbol,
                                            "ltp": normalized["ltp"],
                                            "bid_quantity": normalized["bid_quantity"],
                                            "ask_quantity": normalized["ask_quantity"],
                                            "volume": normalized["volume"],
                                            "prev_close": normalized["prev_close"],
                                            "upper_circuit": normalized["upper_circuit"],
                                            "lower_circuit": normalized["lower_circuit"],
                                            "source": normalized["source"],
                                            "timestamp": normalized["timestamp"].isoformat(),
                                        }
                                        event = Event(
                                            type=EventType.MARKET_DATA_UPDATE,
                                            source="network_analyzer",
                                            data=event_data,
                                        )
                                        try:
                                            loop = asyncio.get_running_loop()
                                            loop.create_task(self.event_bus.publish(event))
                                        except Exception as e:
                                            logger.debug("failed_to_publish_ws_tick_event", symbol=symbol, error=str(e))
            except Exception as exc:
                logger.debug("websocket_frame_parse_error", error=str(exc))

        def on_close():
            logger.warning("websocket_closed", url=url)

        def on_error(err):
            logger.error("websocket_socket_error", url=url, error=str(err))

        ws.on("framesent", on_frame_sent)
        ws.on("framereceived", on_frame_received)
        ws.on("close", on_close)
        ws.on("socketerror", on_error)

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

    def _cache_json_msg(self, data: Any) -> None:
        """Recursively search and cache JSON messages containing symbol information."""
        if isinstance(data, dict):
            symbol = None
            for k in ("symbol", "scrip", "securityCode", "security", "sym"):
                if k in data:
                    symbol = str(data[k]).upper()
                    break
            if symbol:
                self.ws_cache[symbol] = {
                    "data": data,
                    "timestamp": datetime.now(timezone.utc),
                }
                logger.debug("websocket_message_cached", symbol=symbol, data=data)
                
                # Direct event-driven latency upgrade
                if self.event_bus:
                    parsed = self._parse_naasa_quote(symbol, data)
                    if parsed:
                        import asyncio
                        from core.events import Event, EventType
                        event = Event(
                            type=EventType.MARKET_DATA_UPDATE,
                            source="network_analyzer",
                            data=parsed,
                        )
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(self.event_bus.publish(event))
                        except Exception as e:
                            logger.warning("failed_to_publish_ws_tick_event", symbol=symbol, error=str(e))
        elif isinstance(data, list):
            for item in data:
                self._cache_json_msg(item)

    def _extract_auth(self, headers: dict) -> str | None:
        for key, value in headers.items():
            if any(p in key.lower() for p in self.AUTH_HEADER_PATTERNS):
                return value[:50] + "..." if len(value) > 50 else value
        return None

    def _is_market_data_url(self, url: str) -> bool:
        url_lower = url.lower()
        return any(p in url_lower for p in self.MARKET_DATA_PATTERNS)

    def _detect_ws_auth(self, url: str) -> str:
        if "token=" in url or "auth=" in url:
            return "query_param"
        if self._auth_tokens:
            return "header_bearer"
        return "unknown"

    def _update_endpoint_report(self, captured: CapturedRequest) -> None:
        key = f"{captured.method}:{captured.url}"
        if key not in self._endpoints:
            self._endpoints[key] = EndpointReport(
                url=captured.url,
                method=captured.method,
                resource_type=captured.resource_type,
                auth_method="bearer" if captured.auth_token else "none",
                is_market_data=self._is_market_data_url(captured.url),
            )
        self._endpoints[key].sample_count += 1

    def _update_response_structure(self, captured: CapturedRequest, body: str) -> None:
        key = f"{captured.method}:{captured.url}"
        try:
            parsed = json.loads(body)
            if key in self._endpoints:
                self._endpoints[key].response_structure = self._describe_structure(parsed)
        except json.JSONDecodeError:
            pass

    def _describe_structure(self, obj: Any, depth: int = 0) -> Any:
        """Generate structural description of JSON response."""
        if depth > 3:
            return "..."
        if isinstance(obj, dict):
            return {k: self._describe_structure(v, depth + 1) for k, v in list(obj.items())[:20]}
        if isinstance(obj, list):
            if obj:
                return [self._describe_structure(obj[0], depth + 1)]
            return []
        return type(obj).__name__

    def generate_report(self) -> dict:
        """Generate comprehensive network analysis report."""
        market_endpoints = [
            ep for ep in self._endpoints.values() if ep.is_market_data
        ]
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_requests": len(self._captured),
            "total_endpoints": len(self._endpoints),
            "websocket_messages": len(self._ws_messages),
            "auth_tokens_detected": len(self._auth_tokens),
            "market_data_endpoints": [
                {
                    "url": ep.url,
                    "method": ep.method,
                    "auth_method": ep.auth_method,
                    "is_websocket": ep.is_websocket,
                    "sample_count": ep.sample_count,
                    "response_structure": ep.response_structure,
                }
                for ep in market_endpoints
            ],
            "all_endpoints": [
                {
                    "url": ep.url,
                    "method": ep.method,
                    "resource_type": ep.resource_type,
                    "auth_method": ep.auth_method,
                    "request_structure": ep.request_structure,
                    "response_structure": ep.response_structure,
                    "sample_count": ep.sample_count,
                }
                for ep in self._endpoints.values()
            ],
        }

    def save_report(self, filename: str = "network_analysis.json") -> Path:
        """Save report to file."""
        report_path = self.report_dir / filename
        report = self.generate_report()
        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        logger.info("network_report_saved", path=str(report_path))
        return report_path

    def get_market_data_streams(self) -> list[EndpointReport]:
        return [ep for ep in self._endpoints.values() if ep.is_market_data]

    def clear(self) -> None:
        self._captured.clear()
        self._endpoints.clear()
        self._ws_messages.clear()
