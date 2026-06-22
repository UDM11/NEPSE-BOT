"""FastAPI dashboard with WebSocket live updates."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from core.logging_config import get_logger
from core.metrics import metrics

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
                        "created_at": o.created_at.isoformat(),
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
                        "created_at": s.created_at.isoformat(),
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

    @app.get("/api/system")
    async def system_status():
        broker = state.get("broker")
        return {
            "broker": broker.get_status() if broker else {},
            "risk": state.get("risk_manager").get_status() if state.get("risk_manager") else {},
            "metrics": metrics.get_counters(),
            "events": len(state.get("event_bus").get_recent_events(100)) if state.get("event_bus") else 0,
        }

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

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await manager.connect(websocket)
        try:
            while True:
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
                await websocket.send_text(json.dumps(payload, default=str))
                await asyncio.sleep(1)
        except WebSocketDisconnect:
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
