# MCP Scaffolds

Empty stub directories with `.env.example`, `requirements.txt` and dependency lists for each
MCP. Claude reads `docs/01..04` for the full spec, then materialises `server.py` + `lib/*`
inside each scaffold under `~/mcp/<name>/` on Windows.

| Folder | Spec | Runs on | Network |
|---|---|---|---|
| `news-mcp/` | `docs/01-MCP-NEWS.md` | WSL or Windows | yes (Finnhub, NewsAPI, ForexFactory) |
| `trading-mt5-mcp/` | `docs/02-MCP-TRADING.md` | **Windows nativo** | local IPC to MT5 only |
| `analysis-mcp/` | `docs/03-MCP-ANALYSIS.md` | WSL or Windows | none (pure compute) |
| `risk-mcp/` | `docs/04-MCP-RISK.md` | WSL or Windows | none (state.json only) |

Shared cross-cutting concerns live in:

- `docs/09-SHARED-RULES.md` — single module both MCP-trading and risk-MCP import.
- `docs/10-KILL-SWITCH.md` — file-based abort for trading-MCP.
- `docs/07-MT5-SYNC.md` — how trading-MCP streams closed deals into the dashboard journal.
