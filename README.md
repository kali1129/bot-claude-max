# bot-claude-max

> Architectural blueprint for an AI-assisted futures trading workstation that
> runs on Windows + WSL + MetaTrader 5, orchestrated by Claude Pro Max through
> 4 custom MCP servers, with a local React + FastAPI dashboard as the
> human-in-the-loop control panel. Capital target: **$800 USD real**.
> Discipline target: **never violated**.

## ⚡ Estado actual de esta instalación

- **Dashboard** corriendo en http://localhost:3000 (React) + :8001 (FastAPI) + Mongo en WSL.
- **4 MCPs** construidos y testeados (`trading-mt5-mcp`, `risk-mcp`, `analysis-mcp`, `news-mcp`) — 117 tests passing + 12 live tests autoskip cuando MT5 está caído.
- **MT5 desconectado** (esperando recuperación de password). El dashboard renderiza con balance fallback `$0` (configurable vía `CAPITAL_FALLBACK_USD` en `backend/.env`).

## 🔑 Cuando recuperes la password de MT5

Un solo comando hace todo (login en MT5, prueba 14 nombres de server distintos, escribe la password al `.env` cifrado, refresca el dashboard):

```bash
backend/.venv/Scripts/python.exe connect_account.py
```

El script te pedirá la password (sin echo). Si la cuenta autentica, en menos de 10 segundos verás tu balance real en el dashboard.

Si no quieres usar el script, manualmente:
1. Edita `mcp-scaffolds/trading-mt5-mcp/.env` y pon `MT5_PASSWORD=<tu password>`
2. Restart del backend (yo lo automatizo si me lo pides).
3. El bridge re-autentica solo y el dashboard refresca cada 8 segundos.

---

This repo is the **plan**, not the runtime. When you clone it on your machine,
hand it to Claude Code (or Desktop) and say: *"build this following
`CLAUDE.md` and `BUILD_PLAN.md`"*. Claude reads the docs, generates the MCP
servers, configures Claude Desktop, and runs the verification suite at every
phase.

## What's in the box

```
bot-claude-max/
├── CLAUDE.md                     ← invariants Claude must respect (read first)
├── BUILD_PLAN.md                 ← phase-by-phase build script
├── README.md                     ← (this file)
│
├── backend/                      ← reference implementation: dashboard API
│   ├── server.py                 (FastAPI + Motor, 17 endpoints, lifespan, auth, idempotent)
│   ├── plan_content.py           (single source of truth for plan text)
│   ├── tests/test_server.py      (in-process tests with mongomock — 30 tests)
│   ├── tests/backend_test.py     (integration tests against deployed env)
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/                     ← reference implementation: dashboard UI
│   ├── src/Dashboard.jsx + 10 sections
│   └── .env.example
│
├── docs/                         ← the actual blueprint (~3500 lines of spec)
│   ├── 00-OVERVIEW.md            system block diagram
│   ├── 01-MCP-NEWS.md            news + economic calendar
│   ├── 02-MCP-TRADING.md         MT5 trading (the only MCP that touches money)
│   ├── 03-MCP-ANALYSIS.md        pure-compute technical analysis
│   ├── 04-MCP-RISK.md            account guardian + position sizing
│   ├── 05-DASHBOARD.md           dashboard UX/UI spec
│   ├── 06-SETUP-WSL-MT5-CLAUDE.md install/config guide
│   ├── 07-MT5-SYNC.md            MT5 → journal idempotent sync
│   ├── 08-DISCIPLINE-METRICS.md  rule-adherence scoring
│   ├── 09-SHARED-RULES.md        single source of truth for hard limits
│   └── 10-KILL-SWITCH.md         file-based abort + paper/demo/live modes
│
├── mcp-scaffolds/                ← empty folders + .env.example for each MCP
│   ├── news-mcp/
│   ├── trading-mt5-mcp/
│   ├── analysis-mcp/
│   └── risk-mcp/
│
├── memory/PRD.md                 product requirements document
├── tests/, test_reports/         iteration test artifacts
└── design_guidelines.json        Bloomberg-terminal theme spec
```

## Architecture in 30 seconds

```
                        ┌──────────────────┐
                        │  Claude Pro Max  │
                        │  (orchestrator)  │
                        └────────┬─────────┘
              ┌──────────────────┼──────────────────┐
              │ MCP stdio        │                  │
   ┌──────────▼────┐  ┌──────────▼─────┐  ┌─────────▼──────┐  ┌────────────┐
   │  news-mcp     │  │  analysis-mcp  │  │  risk-mcp      │  │ trading-   │
   │  (WSL)        │  │  (WSL)         │  │  (WSL)         │  │ mt5-mcp    │
   │               │  │  pure compute  │  │  state.json    │  │ (WIN nat.) │
   └───────────────┘  └────────────────┘  └────────────────┘  └─────┬──────┘
                                                  ▲                 │
                                                  │ shared rules    │ MT5 IPC
                                                  │ kill-switch     │
                                            ┌─────┴─────────┐  ┌────▼─────┐
                                            │ ~/mcp/_shared │  │   MT5    │
                                            │ rules.py      │  │ Terminal │
                                            │ halt.py       │  └──────────┘
                                            └───────────────┘
                                                  ▲
                                  HTTP + Bearer   │
                       ┌──────────────────────────┴───────────────────┐
                       │                                              │
              ┌────────▼─────────┐                          ┌─────────▼────────┐
              │ FastAPI backend  │ ◀── React frontend ───── │ Browser dashboard │
              │ 127.0.0.1:8000   │                          │  localhost:3000   │
              │ MongoDB local    │                          └───────────────────┘
              └──────────────────┘
```

## Quick start

You probably want to read `CLAUDE.md` and then hand the repo to Claude. But if
you want to bring up the dashboard alone:

```bash
# WSL Ubuntu
git clone https://github.com/kali1129/bot-claude-max.git
cd bot-claude-max/backend
cp .env.example .env  # set DASHBOARD_TOKEN
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
docker run -d --name mongo -p 27017:27017 mongo:7
pytest tests/test_server.py -v   # 30 tests, no Mongo required
uvicorn server:app --host 127.0.0.1 --port 8000 --reload

# new terminal
cd ../frontend
cp .env.example .env
yarn install && yarn start       # → http://localhost:3000
```

## License & disclaimer

Personal project. **Not financial advice.** A $800 account is 100% risk capital.
The only edge this system gives you is forced consistency; the market gives you
nothing else.
