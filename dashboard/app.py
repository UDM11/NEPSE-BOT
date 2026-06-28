"""FastAPI dashboard with WebSocket live updates."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from core.logging_config import get_logger
from core.metrics import metrics
from market_data.models import WatchlistItem

logger = get_logger("dashboard")

STATIC_DIR = Path(__file__).parent / "static"


class ConnectionManager:
    """Manage WebSocket connections for live dashboard updates."""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active:
            self.active.remove(websocket)

    async def broadcast(self, data: dict) -> None:
        message = json.dumps(data, default=str)
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


async def _get_live_nepse_index(broker) -> dict:
    """Fetch live NEPSE & SENSIND indices, points change, volume, turnover and market status from NAASA API."""
    out = {
        "nepse": None,
        "sensitive": None,
        "market_status": "CLOSE",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    if not broker:
        return out
    try:
        page = getattr(broker, "_page", None)
        if not page or page.is_closed():
            return out

        # 1. Fetch indices from /MarketOrder/Indices
        result = await page.evaluate(
            """async () => {
                try {
                    const r = await fetch('/MarketOrder/Indices', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: JSON.stringify({})
                    });
                    return await r.json();
                } catch(e) { return null; }
            }"""
        )

        if result and isinstance(result, dict) and "data" in result:
            import json as _json
            data_str = result["data"]
            rows = _json.loads(data_str) if isinstance(data_str, str) else data_str
            for row in rows:
                if not isinstance(row, dict):
                    continue
                ticker = str(row.get("ticker", row.get("indexName", row.get("name", "")))).upper()
                
                # Check for main NEPSE Index
                is_nepse = "NEPSE" in ticker and "SENSITIVE" not in ticker and "FLOAT" not in ticker and "SENSIND" not in ticker
                # Check for SENSITIVE Index
                is_sensitive = "SENSITIVE" in ticker or "SENSIND" in ticker

                if is_nepse or is_sensitive:
                    try:
                        ltp = float(str(row.get("LTP", row.get("currentValue", row.get("value", 0.0)))).replace(",", ""))
                        close = float(str(row.get("Close", row.get("previousClose", 0.0))).replace(",", ""))
                    except Exception:
                        ltp = 0.0
                        close = 0.0

                    chg_val = row.get("%Change") or row.get("percentChange") or row.get("change")
                    try:
                        if chg_val and str(chg_val).strip():
                            change = float(str(chg_val).replace(",", ""))
                        else:
                            change = ((ltp - close) / close * 100.0) if close > 0.0 else 0.0
                    except Exception:
                        change = 0.0

                    points_change = ltp - close if ltp > 0.0 and close > 0.0 else 0.0

                    try:
                        volume = float(str(row.get("TTQ", row.get("totalTradeQuantity", 0))).replace(",", ""))
                    except Exception:
                        volume = 0.0

                    try:
                        turnover = float(str(row.get("Volume", row.get("TTV", row.get("totalTradedValue", 0)))).replace(",", ""))
                    except Exception:
                        turnover = 0.0

                    index_data = {
                        "value": ltp,
                        "change": change,
                        "points_change": points_change,
                        "volume": volume,
                        "turnover": turnover
                    }

                    if is_nepse:
                        out["nepse"] = index_data
                    elif is_sensitive:
                        out["sensitive"] = index_data

        # Fallback to /Home/MarketSummary if NEPSE is still missing
        if not out["nepse"]:
            summary_res = await page.evaluate(
                """async () => {
                    try {
                        const r = await fetch('/Home/MarketSummary', {
                            headers: {'X-Requested-With': 'XMLHttpRequest'}
                        });
                        return await r.json();
                    } catch(e) { return null; }
                }"""
            )
            if summary_res and isinstance(summary_res, dict) and "data" in summary_res:
                import json as _json
                data_str = summary_res["data"]
                rows = _json.loads(data_str) if isinstance(data_str, str) else data_str
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    ticker = str(row.get("ticker", row.get("indexName", row.get("name", "")))).upper()
                    if "NEPSE" in ticker and "SENSITIVE" not in ticker and "FLOAT" not in ticker and "SENSIND" not in ticker:
                        try:
                            ltp = float(str(row.get("LTP", row.get("currentValue", row.get("value", 0.0)))).replace(",", ""))
                        except Exception:
                            ltp = 0.0
                        try:
                            volume = float(str(row.get("TTQ", row.get("totalTradeQuantity", 0))).replace(",", ""))
                        except Exception:
                            volume = 0.0
                        try:
                            turnover = float(str(row.get("TTV", row.get("totalTradedValue", row.get("Volume", 0)))).replace(",", ""))
                        except Exception:
                            turnover = 0.0

                        out["nepse"] = {
                            "value": ltp,
                            "change": 0.0,
                            "points_change": 0.0,
                            "volume": volume,
                            "turnover": turnover
                        }
                        break

        # 2. Fetch live market status from /MarketWatch/GetMarketStatus
        status_res = await page.evaluate(
            """async () => {
                try {
                    const r = await fetch('/MarketWatch/GetMarketStatus', {
                        headers: {'X-Requested-With': 'XMLHttpRequest'}
                    });
                    const res = await r.json();
                    return res && res.data ? res.data : null;
                } catch(e) { return null; }
            }"""
        )
        if status_res:
            out["market_status"] = str(status_res).upper()

    except Exception as e:
        logger.debug("nepse_index_fetch_error", error=str(e))

    return out


def create_dashboard_app(bot_state: dict | None = None) -> FastAPI:
    """Create FastAPI dashboard application."""
    app = FastAPI(title="NEPSE Trading Bot Dashboard", version="1.0.0")
    manager = ConnectionManager()
    state = bot_state or {}

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index():
        html_path = STATIC_DIR / "index.html"
        if html_path.exists():
            return HTMLResponse(html_path.read_text(encoding="utf-8"))
        return HTMLResponse(_fallback_html())

    @app.get("/api/health")
    async def health():
        return {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "uptime": state.get("uptime", "unknown"),
        }

    @app.get("/api/time")
    async def get_server_time():
        """Return high-precision server UTC timestamp for NTP-style clock sync."""
        import time
        now_utc = datetime.now(timezone.utc)
        return {
            "utc": now_utc.isoformat(),
            "unix_ms": int(time.time() * 1000),
        }

    @app.get("/api/watchlist")
    async def watchlist():
        monitor = state.get("market_monitor")
        if monitor:
            ticks = monitor.get_all_ticks()
            return {"symbols": [t.to_dict() for t in ticks.values()]}
        return {"symbols": []}

    @app.get("/api/orders")
    async def orders():
        db_repo = state.get("db_repo")
        if db_repo:
            recent = await db_repo.get_recent_orders(50)
            return {
                "orders": [
                    {
                        "id": o.id,
                        "symbol": o.symbol,
                        "side": o.side,
                        "quantity": o.quantity,
                        "price": o.price,
                        "status": o.status.value,
                        "created_at": o.created_at.replace(tzinfo=timezone.utc).isoformat() if o.created_at.tzinfo is None else o.created_at.isoformat(),
                        "executed_at": o.executed_at.replace(tzinfo=timezone.utc).isoformat() if o.executed_at and o.executed_at.tzinfo is None else (o.executed_at.isoformat() if o.executed_at else None),
                        "latency_ms": o.latency_ms,
                    }
                    for o in recent
                ]
            }
        return {"orders": []}

    @app.get("/api/signals")
    async def signals():
        db_repo = state.get("db_repo")
        if db_repo:
            recent = await db_repo.get_recent_signals(50)
            return {
                "signals": [
                    {
                        "id": s.id,
                        "symbol": s.symbol,
                        "strategy": s.strategy_name,
                        "action": s.action,
                        "trigger_price": s.trigger_price,
                        "approved": s.approved,
                        "created_at": s.created_at.replace(tzinfo=timezone.utc).isoformat() if s.created_at.tzinfo is None else s.created_at.isoformat(),
                    }
                    for s in recent
                ]
            }
        return {"signals": []}

    @app.get("/api/metrics")
    async def get_metrics():
        return metrics.generate_report()

    @app.get("/api/risk")
    async def risk_status():
        risk = state.get("risk_manager")
        if risk:
            return risk.get_status()
        return {}

    @app.get("/api/collateral")
    async def get_collateral():
        bot = state.get("bot")
        broker = state.get("broker")
        if broker:
            symbol = "YMHL"
            if bot and bot.watchlist and bot.watchlist._items:
                symbol = list(bot.watchlist._items.keys())[0]
            try:
                balance = await broker.get_collateral_balance(symbol, force_refresh=False)
                cost = 0.0
                if bot and bot.watchlist and bot.watchlist._items:
                    for item in bot.watchlist._items.values():
                        if item.enabled:
                            target_price = item.upper_circuit_price or (item.prev_close * (1 + item.circuit_percentage / 100))
                            cost += item.quantity * target_price
                return {"collateral": balance, "staging_cost": cost}
            except Exception as e:
                return {"collateral": 0.0, "staging_cost": 0.0, "error": str(e)}
        return {"collateral": 0.0, "staging_cost": 0.0}

    @app.get("/api/nepse-index")
    async def nepse_index():
        """Fetch live NEPSE & SENSIND indices and watchlist scrips from NAASA API."""
        broker = state.get("broker")
        res = await _get_live_nepse_index(broker)
        
        # Enrich with watchlist scrips ticks
        scrips_list = []
        monitor = state.get("market_monitor")
        if monitor:
            ticks = monitor.get_all_ticks()
            for t in ticks.values():
                scrips_list.append({
                    "symbol": t.symbol,
                    "ltp": t.ltp,
                    "change": t.change_percentage,
                })
        res["scrips"] = scrips_list
        return res

    @app.get("/api/system")
    async def system_status():
        broker = state.get("broker")
        return {
            "broker": broker.get_status() if broker else {},
            "risk": state.get("risk_manager").get_status() if state.get("risk_manager") else {},
            "metrics": metrics.get_counters(),
            "events": len(state.get("event_bus").get_recent_events(100)) if state.get("event_bus") else 0,
        }

    @app.get("/api/screenshot")
    async def get_screenshot():
        broker = state.get("broker")
        if broker:
            img_bytes = await broker.capture_live_screenshot()
            if img_bytes:
                return Response(content=img_bytes, media_type="image/png")
        
        # Return placeholder SVG if no screenshot is available
        placeholder_svg = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 450" width="100%" height="100%">
            <rect width="100%" height="100%" fill="#0a0f1d"/>
            <text x="50%" y="45%" dominant-baseline="middle" text-anchor="middle" font-family="system-ui, sans-serif" font-size="20" fill="#64748b" font-weight="bold">Live Browser View Unavailable</text>
            <text x="50%" y="55%" dominant-baseline="middle" text-anchor="middle" font-family="system-ui, sans-serif" font-size="14" fill="#475569">(Browser not initialized or running in simulation mode)</text>
        </svg>"""
        return Response(content=placeholder_svg, media_type="image/svg+xml")

    @app.get("/api/logs")
    async def get_logs(limit: int = 150):
        log_path = Path("logs/nepse_bot.log")
        if not log_path.exists():
            return {"logs": ["Log file not found."]}
        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                tail_lines = [line.strip() for line in lines[-limit:]]
                return {"logs": tail_lines}
        except Exception as e:
            return {"logs": [f"Error reading logs: {e}"]}

    @app.post("/api/kill-switch/activate")
    async def activate_kill_switch():
        risk = state.get("risk_manager")
        if risk:
            risk.activate_kill_switch("Manual activation via dashboard")
            return {"status": "activated"}
        return {"status": "error", "message": "Risk manager not available"}

    @app.post("/api/kill-switch/deactivate")
    async def deactivate_kill_switch():
        risk = state.get("risk_manager")
        if risk:
            risk.deactivate_kill_switch()
            return {"status": "deactivated"}
        return {"status": "error"}

    @app.get("/api/watchlist/config")
    async def get_watchlist_config():
        watchlist_mgr = state.get("bot").watchlist if state.get("bot") else None
        if watchlist_mgr:
            return {
                "symbols": [
                    {
                        "symbol": item.symbol,
                        "prev_close": item.prev_close,
                        "quantity": item.quantity,
                        "circuit_percentage": item.circuit_percentage,
                        "enabled": item.enabled,
                        "is_ipo": item.is_ipo,
                        "strategy": item.strategy,
                    }
                    for item in watchlist_mgr._items.values()
                ]
            }
        return {"symbols": []}

    @app.post("/api/watchlist/config")
    async def save_watchlist_config(data: dict):
        bot = state.get("bot")
        if not bot or not bot.watchlist:
            return {"status": "error", "message": "Watchlist manager not available"}
        
        symbols_data = data.get("symbols", [])
        bot.watchlist._items.clear()
        for s in symbols_data:
            item = WatchlistItem(
                symbol=s["symbol"].upper(),
                prev_close=float(s.get("prev_close", 0)),
                quantity=int(s.get("quantity", 10)),
                circuit_percentage=float(s.get("circuit_percentage", 15)),
                enabled=bool(s.get("enabled", True)),
                is_ipo=bool(s.get("is_ipo", True)),
                strategy=s.get("strategy", "ipo_daily_circuit"),
            )
            bot.watchlist.set(item)
            
        bot.watchlist.save()
        return {"status": "success", "message": "Watchlist saved successfully"}

    @app.post("/api/execute")
    async def execute_bot():
        bot = state.get("bot")
        if bot:
            if bot.watchlist:
                bot.watchlist.load()
            if bot.market_monitor:
                await bot.market_monitor.refresh_symbols()
            await bot.start_staging_orchestrators()
            return {"status": "success", "message": "Bot executed/armed successfully for all symbols"}
        return {"status": "error", "message": "Bot instance not found"}

    @app.get("/api/system/warnings")
    async def get_system_warnings():
        bot = state.get("bot")
        if bot and hasattr(bot, "active_warnings"):
            return {"warnings": bot.active_warnings}
        return {"warnings": []}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        
        queue = asyncio.Queue()
        event_bus = state.get("event_bus")
        
        async def on_event(event):
            await queue.put(event)
            
        if event_bus:
            event_bus.subscribe_all(on_event)
            
        try:
            # Send initial update
            initial_payload = {
                "type": "update",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metrics": metrics.get_all_stats(),
                "counters": metrics.get_counters(),
            }
            monitor = state.get("market_monitor")
            if monitor:
                initial_payload["watchlist"] = [
                    t.to_dict() for t in monitor.get_all_ticks().values()
                ]
            await websocket.send_text(json.dumps(initial_payload, default=str))
            
            # Send periodic heartbeats every 1.5 seconds to keep metrics fresh if no events are firing
            async def heartbeat_loop():
                try:
                    while True:
                        await asyncio.sleep(1.5)
                        payload = {
                            "type": "update",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "metrics": metrics.get_all_stats(),
                            "counters": metrics.get_counters(),
                        }
                        monitor = state.get("market_monitor")
                        if monitor:
                            payload["watchlist"] = [
                                t.to_dict() for t in monitor.get_all_ticks().values()
                            ]
                        # Fetch NEPSE index every heartbeat
                        try:
                            broker = state.get("broker")
                            if broker:
                                nepse_data = await _get_live_nepse_index(broker)
                                if nepse_data:
                                    scrips_list = []
                                    if monitor:
                                        ticks = monitor.get_all_ticks()
                                        for t in ticks.values():
                                            scrips_list.append({
                                                "symbol": t.symbol,
                                                "ltp": t.ltp,
                                                "change": t.change_percentage,
                                            })
                                    nepse_data["scrips"] = scrips_list
                                    payload["nepse_index"] = nepse_data
                        except Exception:
                            pass
                        await websocket.send_text(json.dumps(payload, default=str))
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass

            heartbeat_task = asyncio.create_task(heartbeat_loop())
            
            while True:
                # Wait for any EventBus event
                event = await queue.get()
                
                # Get latest ticks list to include as watchlist
                watchlist_data = []
                monitor = state.get("market_monitor")
                if monitor:
                    watchlist_data = [t.to_dict() for t in monitor.get_all_ticks().values()]
                
                payload = {
                    "type": "event",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": {
                        "type": event.type.value,
                        "data": event.data,
                    },
                    "metrics": metrics.get_all_stats(),
                    "counters": metrics.get_counters(),
                    "watchlist": watchlist_data,
                }
                await websocket.send_text(json.dumps(payload, default=str))
                queue.task_done()
                
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            if 'heartbeat_task' in locals():
                heartbeat_task.cancel()
            if event_bus:
                event_bus.unsubscribe_all(on_event)
            manager.disconnect(websocket)

    app.state.connection_manager = manager
    app.state.bot_state = state
    return app


def _fallback_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEPSE Trading Bot</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh}
.header{background:linear-gradient(135deg,#1e293b,#0f172a);padding:1.5rem 2rem;border-bottom:1px solid #334155}
.header h1{font-size:1.5rem;font-weight:700}.header p{color:#94a3b8;margin-top:.25rem}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:1rem;padding:1.5rem}
.card{background:#1e293b;border-radius:12px;padding:1.25rem;border:1px solid #334155}
.card h2{font-size:.875rem;text-transform:uppercase;letter-spacing:.05em;color:#94a3b8;margin-bottom:1rem}
.metric{font-size:2rem;font-weight:700;color:#38bdf8}
.metric-label{font-size:.75rem;color:#64748b;margin-top:.25rem}
table{width:100%;border-collapse:collapse;font-size:.875rem}
th{text-align:left;padding:.5rem;color:#94a3b8;border-bottom:1px solid #334155}
td{padding:.5rem;border-bottom:1px solid #1e293b}
.status-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:.5rem}
.status-dot.green{background:#22c55e}.status-dot.red{background:#ef4444}
.btn{padding:.5rem 1rem;border-radius:8px;border:none;cursor:pointer;font-weight:600;font-size:.875rem}
.btn-danger{background:#ef4444;color:#fff}.btn-success{background:#22c55e;color:#fff}
#events{max-height:300px;overflow-y:auto;font-family:monospace;font-size:.75rem}
.event-line{padding:.25rem 0;border-bottom:1px solid #1e293b}
</style></head>
<body>
<div class="header">
<h1>NEPSE IPO Upper-Circuit Trading Bot</h1>
<p>Real-time monitoring dashboard</p>
</div>
<div class="grid">
<div class="card"><h2>System Health</h2><div class="metric" id="health-status">--</div><div class="metric-label">Connection Status</div></div>
<div class="card"><h2>End-to-End Latency (p95)</h2><div class="metric" id="latency-p95">--</div><div class="metric-label">milliseconds</div></div>
<div class="card"><h2>Orders Today</h2><div class="metric" id="orders-count">0</div><div class="metric-label">submitted</div></div>
<div class="card"><h2>Risk Status</h2><div id="risk-status">Loading...</div>
<button class="btn btn-danger" onclick="killSwitch()" style="margin-top:1rem">Kill Switch</button></div>
</div>
<div class="grid">
<div class="card" style="grid-column:span 2"><h2>Live Watchlist</h2>
<table><thead><tr><th>Symbol</th><th>LTP</th><th>Bid Qty</th><th>Ask Qty</th><th>Volume</th><th>Circuit</th><th>Status</th></tr></thead>
<tbody id="watchlist-body"></tbody></table></div>
<div class="card"><h2>Latency Metrics</h2><div id="metrics-panel"></div></div>
</div>
<script>
const ws=new WebSocket(`ws://${location.host}/ws`);
ws.onmessage=(e)=>{const d=JSON.parse(e.data);updateDashboard(d)};
ws.onopen=()=>{document.getElementById('health-status').innerHTML='<span class="status-dot green"></span>Connected'};
ws.onclose=()=>{document.getElementById('health-status').innerHTML='<span class="status-dot red"></span>Disconnected'};
function updateDashboard(d){
if(d.watchlist){const tb=document.getElementById('watchlist-body');tb.innerHTML='';
d.watchlist.forEach(s=>{tb.innerHTML+=`<tr><td>${s.symbol}</td><td>${s.ltp}</td><td>${s.bid_quantity}</td><td>${s.ask_quantity}</td><td>${s.volume}</td><td>${s.upper_circuit}</td><td>${s.is_at_upper_circuit?'<span class="status-dot red"></span>CIRCUIT':'Normal'}</td></tr>`})}
if(d.metrics){let html='';for(const[k,v]of Object.entries(d.metrics)){html+=`<div style="margin-bottom:.5rem"><strong>${k}</strong>: p50=${v.p50?.toFixed(1)||0}ms p95=${v.p95?.toFixed(1)||0}ms (${v.count})</div>`}
document.getElementById('metrics-panel').innerHTML=html;
const e2e=d.metrics.end_to_end_latency;if(e2e)document.getElementById('latency-p95').textContent=e2e.p95?.toFixed(1)||'--'}
if(d.counters)document.getElementById('orders-count').textContent=d.counters.orders_executed||0}
async function killSwitch(){if(confirm('Activate kill switch?')){await fetch('/api/kill-switch/activate',{method:'POST'});alert('Kill switch activated')}}
fetch('/api/risk').then(r=>r.json()).then(d=>{document.getElementById('risk-status').innerHTML=d.kill_switch_active?'<span class="status-dot red"></span>KILL SWITCH ACTIVE':'<span class="status-dot green"></span>Normal'});
</script></body></html>"""
