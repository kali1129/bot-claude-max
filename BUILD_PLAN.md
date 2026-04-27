# BUILD_PLAN.md — Step-by-step build order for Claude

> Execute these phases in order. Do not skip ahead. After each phase, run the
> verification command and stop if it fails. Each phase is small enough that a
> single Claude session can complete it.

Assumptions (already true on the operator's machine):

- Windows 10/11 with WSL2 Ubuntu 22.04
- Python 3.11 in WSL **and** Python 3.11 in Windows native
- MetaTrader 5 installed, logged into a demo broker, "Allow algo trading" ON
- Claude Desktop installed with Pro Max subscription
- Docker Desktop OR a native MongoDB install reachable on `localhost:27017`
- This repository cloned into `~/bot-claude-max/` (WSL path)

If any of those is false: stop, ask the user.

---

## Phase 0 — Repo bring-up (WSL)

Goal: dashboard backend + frontend running locally, all tests green.

```bash
# In WSL
cd ~/bot-claude-max

# Backend
cd backend
cp .env.example .env
# user fills DASHBOARD_TOKEN with: python -c "import secrets;print(secrets.token_urlsafe(32))"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Mongo (if not already)
docker run -d --name mongo -p 27017:27017 mongo:7

# Run tests
pytest tests/test_server.py -v

# Start the API
uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

In a second terminal:

```bash
cd ~/bot-claude-max/frontend
cp .env.example .env  # set REACT_APP_BACKEND_URL=http://localhost:8000
yarn install
yarn start
# → http://localhost:3000 should render the Bloomberg-themed dashboard
```

**Verification**: dashboard loads, Risk Calculator returns lots for $800/1%/EURUSD/20-pip-SL, Trade Journal shows empty list, Architecture Docs section renders all 11 doc IDs.

---

## Phase 1 — Shared rules module

Goal: a single Python module both `risk-mcp` and `trading-mt5-mcp` import. No duplicated constants.

Read `docs/09-SHARED-RULES.md` and create:

```
~/mcp/_shared/
├── __init__.py
├── rules.py            # constants + helpers
└── tests/test_rules.py # property tests
```

Then add `~/mcp/_shared` to `PYTHONPATH` in each MCP's startup. Do not vendor-copy `rules.py` into each MCP — they all import from the same place.

**Verification**: `pytest ~/mcp/_shared/tests` passes.

---

## Phase 2 — Kill-switch wiring

Goal: a file-based abort that any MCP can check in O(1).

Read `docs/10-KILL-SWITCH.md`. Implement `~/mcp/_shared/halt.py` with:

- `is_halted() -> bool`
- `halt(reason: str) -> None` (writes `~/mcp/.HALT` with timestamp + reason)
- `resume() -> None` (deletes the file)

Then add a button to the dashboard `Overview.jsx` that calls a new backend endpoint `POST /api/halt` and `DELETE /api/halt`. Backend writes/deletes the same file path (configurable via `HALT_FILE` env).

**Verification**: clicking "HALT TRADING" creates the file; `python -c "from halt import is_halted; print(is_halted())"` returns True.

---

## Phase 3 — risk-mcp

Read `docs/04-MCP-RISK.md` end to end. Build:

```
~/mcp/risk-mcp/
├── server.py
├── requirements.txt   (copy from mcp-scaffolds/risk-mcp/)
├── .env               (copy from .env.example, fill in)
├── lib/
│   ├── state_manager.py
│   ├── day_reset.py
│   ├── sizing.py
│   └── stats.py
├── state.json         (auto-created)
├── deals.jsonl        (auto-created)
└── tests/
    ├── test_state.py
    ├── test_drawdown.py
    └── test_sizing_property.py   (hypothesis-based)
```

**Sizing property tests are mandatory.** They must verify, for arbitrary
`balance ∈ [10, 1_000_000]`, `risk_pct ∈ (0, 5]`, `entry > 0`, `sl > 0,
sl != entry`, that:

- `actual_risk_dollars <= balance * risk_pct/100 * 1.001` (rounding tolerance)
- `lots == 0` when raw lots < min_lot, never silently floors
- `state.json` round-trips: read → modify → write → read returns same dict

**Verification**: `pytest ~/mcp/risk-mcp/tests/ -v` — at least 30 tests pass, including hypothesis. Smoke: `python ~/mcp/risk-mcp/server.py` starts and exits cleanly on Ctrl+C.

---

## Phase 4 — analysis-mcp

Read `docs/03-MCP-ANALYSIS.md`. Build with the same scaffold pattern. No
network, no state. Pure functions over OHLCV arrays.

Property tests for indicators (RSI bounded [0, 100], EMA monotonic on monotonic
input, etc.) are required.

**Verification**: `pytest ~/mcp/analysis-mcp/tests/ -v` passes; manual call returns score 0..100 for a synthetic OHLCV.

---

## Phase 5 — news-mcp

Read `docs/01-MCP-NEWS.md`. Build with API keys from the user.

If the user has no Finnhub/NewsAPI keys: write the MCP anyway, but make those
backends optional — return `{"ok": false, "reason": "NO_API_KEY"}` from the
relevant tools. ForexFactory scraping should still work.

**Verification**: `python ~/mcp/news-mcp/server.py` starts; `tools/test_decision.py` covers blackout windows.

---

## Phase 6 — trading-mt5-mcp ⚠️ CRITICAL

Read `docs/02-MCP-TRADING.md` twice. Then `CLAUDE.md` once more for the invariants.

This MCP runs on **Windows native Python**, not WSL. Build it inside WSL but
target paths the user copies to `C:\Users\<user>\mcp\trading-mt5-mcp\`.

Wire in this order:

1. Connection manager (`lib/connection.py`) with auto-retry.
2. Read-only tools (`get_account_info`, `get_open_positions`, `get_rates`, `get_tick`, `get_trade_history`).
3. Pre-trade guards (`lib/guards.py`) — import constants from `_shared.rules`. Tests for each guard with adversarial inputs.
4. Kill-switch check at the **top** of `place_order` (before all other guards).
5. Idempotency: `lib/idempotency.py` with a 60-second TTL cache keyed by `client_order_id`. Tests.
6. `place_order` itself, behind a `TRADING_MODE` switch:
   - `paper`: log to `paper_orders.jsonl`, return a synthetic ticket, do not call `mt5.order_send`.
   - `demo` / `live`: real `mt5.order_send`.
7. Sync hook: after a successful order or detected close, POST to dashboard `/api/journal` with bearer token. See `docs/07-MT5-SYNC.md`.

**Verification matrix** (must all pass before user goes near demo, let alone live):

- Guards: 7 tests, one per check, each rejects with the right reason code.
- Idempotency: same `client_order_id` returns the same ticket; different ids do not.
- Kill-switch: when `~/mcp/.HALT` exists, `place_order` returns `HALTED` and never calls MT5.
- Paper mode: 100 simulated orders, all logged, MT5 untouched (assert via mock).
- Sync: a deal close in demo posts a single row to the dashboard journal with `source: "mt5-sync"`.

---

## Phase 7 — Dashboard sync poller

Read `docs/07-MT5-SYNC.md`. Add a background job inside `trading-mt5-mcp` that
polls `mt5.history_deals_get` every 30s and POSTs new closed deals to the
dashboard. Idempotency key: `mt5-deal-<ticket>`.

**Verification**: open and close a paper-mode order; within 60s, dashboard
`/api/journal` shows it with `source: "mt5-sync"`.

---

## Phase 8 — Discipline metric

Read `docs/08-DISCIPLINE-METRICS.md`. The backend already exposes
`GET /api/discipline/score` (see `backend/server.py`). Add a small card to the
dashboard `Overview.jsx` that fetches and displays the score with traffic-light
colour: `>= 95 green, 80..95 amber, < 80 red`.

---

## Phase 9 — Claude Desktop config

Edit `%APPDATA%\Claude\claude_desktop_config.json` (per `docs/06-SETUP-WSL-MT5-CLAUDE.md`). Use:

- `wsl python` for `news`, `analysis`, `risk` (running inside Ubuntu).
- Native `python.exe` for `trading` (Windows-only because of the `MetaTrader5` package).

Restart Claude Desktop, confirm 4 MCPs show up.

---

## Phase 10 — Acceptance test

Run end-to-end with `TRADING_MODE=paper` for **at least 1 trading day**:

1. Morning: dashboard checklist 100%, `news.is_tradeable_now("EURUSD")` returns true.
2. Build a setup, ask Claude to `analysis.score_setup(...)` — must return >= 70 to proceed.
3. Ask Claude to size and place a paper order. Verify it appears in dashboard within 60s.
4. Ask Claude to close it. Verify journal updates, equity curve moves.
5. End of day: `risk.expectancy(last_n=1)` returns sane numbers, no warnings.

Only **after** this passes does the user flip `TRADING_MODE=demo` and run another 2 weeks. Only after demo metrics meet the bar in `docs/02-MCP-TRADING.md` does live get touched.

---

## Phase rollback

If any phase fails verification: do not patch around it. Stop, surface the
failure to the user, propose a fix, and re-run the phase verification. The
build order matters; a broken kill-switch in Phase 2 will leak into Phase 6 and
get masked by other guards.
