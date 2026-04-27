# CLAUDE.md — Read this first

> Manifesto for Claude (Code, Desktop, or Web) when this repository is dropped
> on a local machine and you are asked to "build this". You are not improvising.
> You are following an architectural blueprint that has been thought through.
> Your job is to materialise it without negotiating away the safety guarantees.

## What this repository is

A **blueprint** for an AI-assisted futures trading workstation:

- 1 dashboard web (React + FastAPI + MongoDB) — already implemented, lives in `backend/` and `frontend/`. **Code here is reference quality. Match its patterns when you write the MCPs.**
- 4 MCP servers (Python, MCP protocol over stdio) — specs only. Empty scaffolds in `mcp-scaffolds/`. You build them by reading `docs/01..04`.
- Cross-cutting modules — `docs/07..10` (sync, discipline, shared rules, kill-switch). These are not optional; they are how the system stays alive.

## Target operator environment

- **Windows 10/11 host** (where MetaTrader 5 lives — already installed and logged in).
- **WSL2 Ubuntu 22.04** (where the dashboard backend, frontend, and 3 of the 4 MCPs run).
- **Claude Desktop** on Windows (orchestrator).
- **MongoDB** local (`docker run -p 27017:27017 -d mongo:7` or native install).

You can assume MT5 is installed, logged into a demo broker, and "Allow algorithmic trading" is enabled. Do not redo those steps.

## Reading order (mandatory)

1. `BUILD_PLAN.md` — the prompt-by-prompt build order. This is the script you execute.
2. `docs/00-OVERVIEW.md` — the system block diagram. Memorise the boundaries.
3. `docs/09-SHARED-RULES.md` — the single source of truth for hard limits. **All MCPs import from here.** No copy-pasting constants.
4. `docs/10-KILL-SWITCH.md` — the abort mechanism. Wire it before writing `place_order`.
5. `docs/02-MCP-TRADING.md` — the only MCP that touches money. Read twice.
6. The other docs in any order.

## Non-negotiable invariants

These are the ones that, if you violate them, cost real dollars:

- **`risk-mcp` and `trading-mt5-mcp` import constants from a single shared module** (`docs/09-SHARED-RULES.md`). Never duplicate `MAX_RISK_PER_TRADE_PCT`, `MAX_DAILY_LOSS_PCT`, `MIN_RR`, `MAX_OPEN_POSITIONS` across files.
- **`place_order` is idempotent**: it accepts a `client_order_id`. If the same id arrived in the last 60s, it returns the prior result instead of placing a second order. Logged in `orders.jsonl`.
- **`place_order` checks the kill-switch file before any other guard**. If `~/mcp/.HALT` exists, return `{ok: false, reason: "HALTED"}` and write to `orders.jsonl`. No exceptions.
- **`TRADING_MODE=paper` is the default**. The MCP must run end-to-end without ever calling `mt5.order_send` in paper mode. Demo and live are explicit opt-ins via `.env`.
- **Closed deals flow MT5 → trading-mcp → dashboard backend** via `POST /api/journal` with `client_id = "mt5-deal-<ticket>"`. The user never types trades. See `docs/07-MT5-SYNC.md`.
- **The `risk-mcp` `state.json` carries a `_schema_version` field**. Bump it when you change the schema and provide a migration; never write code that mutates state without reading the version first.
- **Backend write endpoints are auth-gated when `DASHBOARD_TOKEN` is set**. The MCP sync poller MUST send `Authorization: Bearer <token>`. Never disable this when wiring the sync.
- **Backend binds to `127.0.0.1` by default**. Do not change this without an explicit reverse-proxy plan.
- **Logging goes to stderr**. stdout is reserved for the MCP protocol. If you `print()` to stdout you break Claude's ability to call your tools.

## Things you must refuse to do, even if asked

- Lower `MIN_RR` below `2.0`.
- Raise `MAX_RISK_PER_TRADE_PCT` above `1.0`.
- Allow `MAX_OPEN_POSITIONS` > 1 without the user editing the constant **and** writing a comment explaining the new strategy.
- Add a `bypass_guards=True` parameter to any tool.
- Ship code where `place_order` can succeed without an SL.
- Skip the kill-switch check.
- Migrate to live trading without a passing `discipline_score >= 95%` over the last 30 trades.

If the user asks for any of these, push back once with the rule and the rationale, then refuse. The rules exist because the cost of being wrong is paid in the user's $800.

## Code style for new MCPs

- Python 3.11+, `mcp.server.fastmcp.FastMCP`.
- Type-hint everything. Pydantic models for any structured input.
- Tools return JSON-serialisable dicts. On failure, return `{"ok": false, "reason": "<UPPER_SNAKE>", "detail": "<human>"}`. Never `raise` from a tool body except for protocol errors.
- One concern per `lib/` module. `server.py` only wires.
- `tests/` ships with each MCP. `risk-mcp` ships property tests via `hypothesis` — the calculations must hold for arbitrary balances and SL distances.

## When you are uncertain

Stop and ask the user. The harness this repo will be run inside expects you to surface:

1. Anything that contradicts the docs.
2. Any place where two docs disagree (open a clarification request before resolving on your own).
3. Any moment you are tempted to add a "temporary" relaxation of a rule.

The blueprint is opinionated on purpose. If something feels too strict, that is the feature, not a bug.
