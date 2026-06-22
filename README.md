# NEPSE IPO Upper-Circuit Trading Bot

Production-grade automated trading system for the Nepal Stock Exchange (NEPSE) that monitors IPO shares and executes buy orders when upper-circuit conditions are met. Operates through broker TMS web platforms via Playwright browser automation combined with direct HTTP API execution.

---

## Key Features

- **Dual-Check Preemptive Trigger**: Triggers automatically when either:
  - The LTP enters NEPSE's dynamic `±3%` price band of the target limit (`ltp >= target_price / 1.03`).
  - The broker order entry page updates the allowed High limit directly to the target price.
- **Connection Pooled HTTP API Submission**: Pre-resolves order session parameters (scrip ID, exchange, cookies, user-agent) once and submits orders directly via POST requests using a persistent `httpx.AsyncClient`. This bypasses browser DOM interaction entirely for **sub-millisecond** execution times.
- **Smart watch list table filtering**: Utilizes the regular Market Watch table search input (`#searchInput`) to isolate and load target scrip data, ensuring the page receives real-time SockJS WebSocket ticks.
- **Real-time WebSocket Caching**: Inspects, decodes, and caches incoming SockJS WebSocket frames in-memory (`O(1)` dict lookups) for latency-free price checks.
- **Async Concurrency Lock**: Features a mutex execution lock to prevent parallel browser page scrapes, avoiding browser thread freezing.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        main.py (Orchestrator)                    │
├──────────┬──────────┬──────────┬──────────┬──────────┬────────┤
│ Market   │ Strategy │   Risk   │  Order   │  Broker  │  WS    │
│ Monitor  │  Engine  │ Manager  │ Executor │  Client  │ Cache  │
├──────────┴──────────┴──────────┴──────────┴──────────┴────────┤
│                     Event Bus (Async Pub/Sub)                    │
├─────────────────────────────────────────────────────────────────┤
│              Database (SQLite/PostgreSQL) + Metrics              │
├─────────────────────────────────────────────────────────────────┤
│           Dashboard (FastAPI + WebSocket Live Updates)           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Project Structure

```
project/
├── broker/              # Playwright automation, network analyzer, connection pooling
├── config/              # YAML settings, strategies, watchlist
├── core/                # Config, events, metrics, security, logging
├── dashboard/           # FastAPI web dashboard
├── data/                # Database and persistence (gitignored db files)
├── database/            # SQLAlchemy models, repository
├── logs/                # Structured JSON logs, screenshots (gitignored logs)
├── market_data/         # Watchlist, monitoring engine, tick models
├── order_engine/        # Validation, execution, retry logic
├── risk_management/     # Capital limits, kill switch, dedup
├── scripts/             # Utility scripts for selector discovery
├── strategies/          # Configurable strategy framework
├── main.py              # Application entry point
├── Dockerfile
└── docker-compose.yml
```

---

## Quick Start

### 1. Prerequisites

- Python 3.12+
- Playwright browsers (`playwright install chromium`)

### 2. Setup

```bash
# Clone and enter project
cd BOT

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/Mac

# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Configure environment
copy .env.example .env
# Edit .env with broker credentials and risk settings
```

### 3. Configure Watchlist & Strategy

Edit `config/watchlist.yaml` with the real NEPSE symbol and previous close price:

```yaml
symbols:
  - symbol: TPKHL
    prev_close: 345             # <-- UPDATE THIS daily with previous day closing price
    circuit_percentage: 15     # NEPSE IPO daily band (do not change)
    use_dynamic_circuit: true
    enabled: true
    strategy: ipo_daily_circuit
    is_ipo: true
```

### 4. Run

```bash
# Start bot with dashboard
python main.py

# Start without dashboard
python main.py --no-dashboard

# Start in simulation mode for dry run
python main.py --simulate --no-dashboard

# Dashboard available at http://localhost:8080
```

---

## Trading Flow

```
Market Tick Detected (WebSocket / Scraping)
                     ↓
Preemptive Check? (LTP in band OR High Limit updated) ──No──→ Continue Monitoring
                     ↓ Yes
Strategy Evaluation (YAML-configured conditions)
                     ↓
Risk Management Checks (capital, exposure, dedup, kill switch)
                     ↓
Order Tokens Pre-Resolution (cookies, user-agent, scrip ID)
                     ↓
Direct API POST Injection (sub-millisecond loop via connection pool)
                     ↓
Execution Confirmation & Structured Log Output
```

---

## Risk Management

| Control | Default | Config Key |
|---------|---------|------------|
| Daily capital limit | NPR 50,000 | `risk.daily_capital_limit` |
| Max qty per order | 20 | `risk.max_quantity_per_order` |
| Max exposure | NPR 100,000 | `risk.max_exposure` |
| Max orders/symbol/day | 3 | `risk.max_orders_per_symbol_per_day` |
| Duplicate window | 30 seconds | `risk.duplicate_order_window_seconds` |
| Kill switch | Active | `risk.kill_switch` |

> [!WARNING]
> Ensure `RISK_KILL_SWITCH=false` is set in your `.env` to place real live orders on NEPSE.

---

## Performance Metrics

Tracked automatically with microsecond precision:

- **Detection Latency** — tick capture to circuit detection.
- **Decision Latency** — strategy evaluation time.
- **Order Submission Latency** — time taken for direct connection-pooled POST request (sub-milliseconds).
- **Execution Latency** — time to receive server confirmation.

View metrics via the live dashboard or `GET /api/metrics`.

---

## Disclaimer

This software is for educational and research purposes. Automated trading on NEPSE carries significant financial risk. Ensure compliance with NEPSE regulations, broker terms of service, and applicable securities laws before deploying with real capital.
