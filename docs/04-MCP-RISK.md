# 04 — MCP de Gestión de Riesgo (Guardian)

> El **guardia de la cuenta**. Calcula tamaño de posición, monitorea drawdown del día, bloquea trading tras 3 pérdidas seguidas o -3% diario, lleva contabilidad de equity y emite señal de STOP. Persiste estado en `state.json`.

## Propósito

Aunque Claude se equivoque o el `trading-mcp` falle, este MCP debe **gritar STOP** cuando toque. Es el último eslabón antes de que la cuenta de $800 se vuelva ceros. Su trabajo es decir "no" más veces que "sí".

---

## Filosofía de diseño

1. **Estado persistente**: el guardian no puede olvidar. Si el MCP se reinicia, debe recordar P&L del día y consecutive losses.
2. **Auto-reset diario UTC**: cada 00:00 UTC el contador se reinicia.
3. **Lockout fuerte**: cuando se hit -3% del día, el MCP queda lockeado hasta el día siguiente. No hay "reabrir manual".
4. **Read-only frente a MT5**: este MCP **NO ejecuta órdenes**. Solo informa y bloquea. La ejecución vive en `trading-mcp`.

---

## Arquitectura

```
┌──────────────────────────────────────────┐
│  risk-mcp                                │
│                                          │
│  ┌────────────────────────────────────┐  │
│  │ State (persistent)                  │  │
│  │   ~/mcp/risk-mcp/state.json        │  │
│  │   {                                 │  │
│  │     starting_balance_today: 800,    │  │
│  │     deals_today: [...],             │  │
│  │     consecutive_losses: 0,          │  │
│  │     locked_until_utc: null,         │  │
│  │     last_reset_date: "2026-01-15"   │  │
│  │   }                                 │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ History (append-only)               │  │
│  │   ~/mcp/risk-mcp/deals.jsonl        │  │
│  │   1 line per closed deal            │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ Day Reset Engine                    │  │
│  │   auto-runs on every tool call      │  │
│  └────────────────────────────────────┘  │
│  ┌────────────────────────────────────┐  │
│  │ Tools                               │  │
│  │   calc_position_size()              │  │
│  │   daily_status()                    │  │
│  │   should_stop_trading()             │  │
│  │   register_trade()                  │  │
│  │   expectancy()                      │  │
│  │   reset_day()  [admin]              │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
```

---

## Estructura de archivos

```
risk-mcp/
├── server.py
├── requirements.txt
├── state.json                # se crea al primer run
├── deals.jsonl               # append-only history
├── lib/
│   ├── state_manager.py      # load/save atómico
│   ├── day_reset.py          # auto-reset UTC
│   ├── sizing.py             # calc_position_size logic
│   └── stats.py              # expectancy
└── tests/
    ├── test_state.py
    ├── test_drawdown.py
    └── test_expectancy.py
```

## Dependencies

```
mcp>=1.0.0
pydantic>=2.6
python-dotenv>=1.0.1
```

(Mínimas. Cero red.)

## Variables de entorno

| Var | Default | Descripción |
|---|---|---|
| `STARTING_BALANCE` | `800` | Solo se usa la primera vez |
| `MAX_RISK_PER_TRADE_PCT` | `1.0` | Default para `calc_position_size` |
| `MAX_DAILY_LOSS_PCT` | `3.0` | Threshold de halt diario |
| `MAX_CONSECUTIVE_LOSSES` | `3` | Después de N en línea, halt |
| `MAX_TRADES_PER_DAY` | `5` | Anti-overtrading |
| `STATE_FILE` | `./state.json` | Path del state |

---

## State schema (`state.json`)

```json
{
  "starting_balance_today": 800.0,
  "current_equity": 802.50,
  "deals_today": [
    {
      "ts": "2026-01-15T08:30:00Z",
      "symbol": "EURUSD",
      "side": "buy",
      "profit": -8.0,
      "r_multiple": -1.0
    },
    {
      "ts": "2026-01-15T11:45:00Z",
      "symbol": "XAUUSD",
      "side": "sell",
      "profit": 18.5,
      "r_multiple": 2.3
    }
  ],
  "consecutive_losses": 0,
  "locked_until_utc": null,
  "last_reset_date": "2026-01-15"
}
```

### Persistencia atómica

```python
def save_state(state: dict, path: str = STATE_FILE):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, path)  # atomic on POSIX/NTFS
```

Garantiza que ningún crash deja `state.json` corrompido.

---

## Day Reset Engine

```python
def maybe_reset_day(state: dict) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    if state["last_reset_date"] != today:
        # Append día anterior a deals.jsonl
        for deal in state["deals_today"]:
            append_to_history(deal)
        # Reset del día
        state["starting_balance_today"] = state["current_equity"]
        state["deals_today"] = []
        state["consecutive_losses"] = 0
        state["locked_until_utc"] = None
        state["last_reset_date"] = today
    return state
```

Esta función se llama al INICIO de cada tool. Garantiza que nunca opere lockeado al día siguiente.

---

## Tools expuestas (6)

### 1. `calc_position_size(...)`

Calcula lotaje exacto.

**Args:**
- `balance` (float) — balance actual cuenta
- `risk_pct` (float) — default `MAX_RISK_PER_TRADE_PCT`
- `entry` (float)
- `sl` (float)
- `contract_size` (float) — del `symbol_info` MT5
- `tick_value` (float)
- `tick_size` (float)
- `lot_step` (float, default `0.01`)
- `min_lot` (float, default `0.01`)
- `max_lot` (float, default `0.5`)

**Lógica:**
```python
def calc_position_size(balance, risk_pct, entry, sl, tick_value, tick_size, lot_step=0.01, min_lot=0.01, max_lot=0.5):
    if entry == sl:
        return {"error": "entry == sl"}
    risk_dollars = balance * (risk_pct / 100)
    sl_distance = abs(entry - sl)
    sl_ticks = sl_distance / tick_size
    dollars_per_lot = sl_ticks * tick_value
    raw_lots = risk_dollars / dollars_per_lot
    snapped = max(min_lot, round(raw_lots / lot_step) * lot_step)
    capped = min(snapped, max_lot)

    actual_risk = capped * sl_ticks * tick_value
    warnings = []
    if capped < snapped:
        warnings.append(f"Lots capped from {snapped:.2f} to {capped:.2f}")
    if risk_pct > 1.0:
        warnings.append(f"⚠️ Risk {risk_pct}% > regla 1%")
    if sl_ticks * tick_size < entry * 0.0005:
        warnings.append("SL muy cerca, riesgo de stop hunt")

    return {
        "lots": round(capped, 4),
        "risk_dollars": round(actual_risk, 2),
        "risk_pct_actual": round(actual_risk / balance * 100, 3),
        "sl_distance": round(sl_distance, 5),
        "sl_ticks": round(sl_ticks, 2),
        "warnings": warnings,
    }
```

### 2. `daily_status() → dict`

Estado del día actual.

```json
{
  "date": "2026-01-15",
  "starting_balance": 800.00,
  "current_equity": 802.50,
  "trades_count": 2,
  "wins_today": 1,
  "losses_today": 1,
  "consecutive_losses": 0,
  "daily_pl_usd": 2.50,
  "daily_pl_pct": 0.31,
  "max_dd_intraday_pct": -1.0,
  "can_trade": true,
  "locked": false,
  "reasons": []
}
```

### 3. `should_stop_trading() → dict` ⭐ TOOL CRÍTICA

La pregunta del millón: **¿podemos seguir hoy?**

**Reglas evaluadas (en orden, OR):**

| Regla | Threshold | Razón |
|---|---|---|
| `daily_pl_pct <= -3.0` | -3% | Daily drawdown limit hit |
| `consecutive_losses >= 3` | 3 | Loss streak — emocional |
| `trades_count >= 5` | 5 | Anti-overtrading |
| Hora UTC en `BLOCKED_HOURS` | 21:00–07:00 | Sesión nocturna ilíquida |
| `locked_until_utc` no expirado | — | Lockout previo activo |

```python
def should_stop_trading() -> dict:
    state = maybe_reset_day(load_state())
    reasons = []
    pl_pct = (state["current_equity"] - state["starting_balance_today"]) / state["starting_balance_today"] * 100

    if pl_pct <= -MAX_DAILY_LOSS_PCT:
        reasons.append(("DAILY_LOSS_LIMIT", f"DD {pl_pct:.2f}% <= -{MAX_DAILY_LOSS_PCT}%"))
    if state["consecutive_losses"] >= MAX_CONSECUTIVE_LOSSES:
        reasons.append(("LOSS_STREAK", f"{state['consecutive_losses']} pérdidas consecutivas"))
    if len(state["deals_today"]) >= MAX_TRADES_PER_DAY:
        reasons.append(("OVERTRADING", f"{len(state['deals_today'])} trades hoy"))

    hour = datetime.now(timezone.utc).hour
    if hour >= 21 or hour < 7:
        reasons.append(("BLOCKED_HOUR", f"{hour}:00 UTC en blackout"))

    if state["locked_until_utc"]:
        unlock = datetime.fromisoformat(state["locked_until_utc"])
        if datetime.now(timezone.utc) < unlock:
            reasons.append(("LOCKED", f"Lockout activo hasta {state['locked_until_utc']}"))

    stop = len(reasons) > 0
    return {
        "stop": stop,
        "reasons": reasons,
        "resume_at_utc": next_day_utc_iso() if stop else None,
    }
```

### 4. `register_trade(profit, r_multiple, symbol, side) → dict`

Llamado **después** de cerrar una posición. Actualiza state.

```python
def register_trade(profit: float, r_multiple: float, symbol: str, side: str) -> dict:
    state = maybe_reset_day(load_state())
    deal = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "side": side,
        "profit": profit,
        "r_multiple": r_multiple,
    }
    state["deals_today"].append(deal)
    state["current_equity"] += profit

    # Loss streak tracking
    if profit < 0:
        state["consecutive_losses"] += 1
    elif profit > 0:
        state["consecutive_losses"] = 0
    # profit == 0 (BE) no cambia streak

    # Lockout if -3% hit
    pl_pct = (state["current_equity"] - state["starting_balance_today"]) / state["starting_balance_today"] * 100
    if pl_pct <= -MAX_DAILY_LOSS_PCT:
        state["locked_until_utc"] = next_day_utc_iso()

    save_state(state)
    return {"registered": True, "current_equity": state["current_equity"], "consecutive_losses": state["consecutive_losses"]}
```

### 5. `expectancy(last_n=30) → dict`

Calcula expectancy desde `deals.jsonl`.

```python
def expectancy(last_n: int = 30) -> dict:
    deals = load_history()[-last_n:]
    if not deals:
        return {"win_rate": 0, "avg_R": 0, "expectancy": 0, "n": 0}
    wins = [d for d in deals if d["profit"] > 0]
    losses = [d for d in deals if d["profit"] < 0]
    wr = len(wins) / len(deals)
    avg_win_R = mean(d["r_multiple"] for d in wins) if wins else 0
    avg_loss_R = mean(d["r_multiple"] for d in losses) if losses else 0  # negativo
    expectancy_R = wr * avg_win_R + (1 - wr) * avg_loss_R
    return {
        "n": len(deals),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(wr * 100, 1),
        "avg_win_R": round(avg_win_R, 2),
        "avg_loss_R": round(avg_loss_R, 2),
        "expectancy": round(expectancy_R, 2),
        "verdict": "POSITIVE" if expectancy_R > 0.3 else "MARGINAL" if expectancy_R > 0 else "NEGATIVE",
    }
```

### 6. `reset_day()` (admin)

Solo para casos excepcionales. Reinicia state. Logs a stderr.

⚠️ **No la uses para "borrar pérdidas"**. Eso es la peor forma de auto-engaño en trading.

---

## Server skeleton

```python
"""risk-mcp v1.0.0 — Account guardian and position sizer."""
import os
import sys
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

from lib.state_manager import load_state, save_state
from lib.day_reset import maybe_reset_day
from lib.sizing import calc_position_size as _calc
from lib.stats import expectancy as _expectancy

load_dotenv()
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
log = logging.getLogger("risk-mcp")

mcp = FastMCP("risk")

@mcp.tool()
def calc_position_size(
    balance: float,
    risk_pct: float,
    entry: float,
    sl: float,
    tick_value: float,
    tick_size: float,
    lot_step: float = 0.01,
    min_lot: float = 0.01,
    max_lot: float = 0.5,
) -> dict:
    return _calc(balance, risk_pct, entry, sl, tick_value, tick_size, lot_step, min_lot, max_lot)

@mcp.tool()
def daily_status() -> dict:
    state = maybe_reset_day(load_state())
    save_state(state)
    # … return formatted dict (ver schema arriba)
    ...

@mcp.tool()
def should_stop_trading() -> dict:
    # … (ver lógica arriba)
    ...

@mcp.tool()
def register_trade(profit: float, r_multiple: float, symbol: str, side: str) -> dict:
    # … (ver lógica arriba)
    ...

@mcp.tool()
def expectancy(last_n: int = 30) -> dict:
    return _expectancy(last_n)

@mcp.tool()
def reset_day() -> dict:
    log.warning("reset_day called manually — auditoría!")
    state = {
        "starting_balance_today": load_state()["current_equity"],
        "current_equity": load_state()["current_equity"],
        "deals_today": [],
        "consecutive_losses": 0,
        "locked_until_utc": None,
        "last_reset_date": datetime.now(timezone.utc).date().isoformat(),
    }
    save_state(state)
    return {"reset": True}


if __name__ == "__main__":
    mcp.run()
```

---

## Configuración Claude Desktop

```json
{
  "mcpServers": {
    "risk": {
      "command": "python",
      "args": ["C:\\Users\\TU_USUARIO\\mcp\\risk-mcp\\server.py"],
      "env": {
        "STARTING_BALANCE": "800",
        "MAX_RISK_PER_TRADE_PCT": "1.0",
        "MAX_DAILY_LOSS_PCT": "3.0",
        "STATE_FILE": "C:\\Users\\TU_USUARIO\\mcp\\risk-mcp\\state.json"
      }
    }
  }
}
```

---

## Testing

```python
# tests/test_drawdown.py
def test_lockout_after_3pct_loss(tmp_path):
    state_file = tmp_path / "state.json"
    os.environ["STATE_FILE"] = str(state_file)
    # Setup: balance 800
    initial_state = {
        "starting_balance_today": 800,
        "current_equity": 800,
        "deals_today": [],
        "consecutive_losses": 0,
        "locked_until_utc": None,
        "last_reset_date": today_iso(),
    }
    save_state(initial_state)

    # Simulate 3% loss in one trade
    register_trade(profit=-25, r_multiple=-3, symbol="EURUSD", side="buy")

    # Should be locked
    status = should_stop_trading()
    assert status["stop"] is True
    assert any(r[0] == "DAILY_LOSS_LIMIT" for r in status["reasons"])
```

---

## Patrones de uso desde Claude

```
Tú: "Antes de operar, ¿cómo está la cuenta hoy?"

Claude: risk.daily_status()
        → "Equity $805. P&L día: +$5 (+0.6%). 1 trade hoy. Puedes operar."

Tú: "Cierro mi trade EURUSD con +$15"

Claude: risk.register_trade(profit=15, r_multiple=1.8, symbol="EURUSD", side="buy")
        → "Registrado. Equity actual $820. Streak: 1 win."

Tú: "Calcula lotaje EURUSD entry 1.0850 SL 1.0830"

Claude: trading.get_account_info() → balance $820
        risk.calc_position_size(balance=820, risk_pct=1, entry=1.0850, sl=1.0830, …)
        → "0.04 lots. Riesgo $8.20."

Tú: "¿Y cuál es mi expectancy?"

Claude: risk.expectancy(last_n=30)
        → "30 trades. WR 56%. Avg win 1.8R, avg loss -1.0R. Expectancy +0.45R. POSITIVE ✅"
```

---

## Edge cases / troubleshooting

| Problema | Causa | Fix |
|---|---|---|
| `state.json` corrompido | crash mid-write | Restauración manual desde `deals.jsonl` |
| Reset diario no funciona | TZ local en vez de UTC | Asegura `datetime.now(timezone.utc)` |
| Lockout no se levanta | `locked_until_utc` malformado | Validar ISO con `dateutil` |
| `register_trade` doble | Claude llama 2 veces por error | Idempotency key opcional con `trade_id` |
| Lots cap dispara siempre | `MAX_LOTS_PER_TRADE` muy bajo | Revisa relación SL distance vs balance |

---

## Lo que este MCP NO hace (deliberadamente)

- ❌ No envía órdenes (eso vive en `trading-mcp`)
- ❌ No analiza setups (eso vive en `analysis-mcp`)
- ❌ No tiene UI (eso vive en el dashboard web)
- ❌ No te deja saltarte reglas porque "esta vez es distinto"

Si quieres añadir features, primero pregúntate: **¿esto refuerza la disciplina o la afloja?**. Si afloja, no lo añadas.

---

## Checklist de validación

- [ ] `state.json` se crea al primer run con valores default
- [ ] Auto-reset funciona al cambiar de día UTC
- [ ] `should_stop_trading` devuelve `true` con `consecutive_losses=3`
- [ ] `register_trade` con profit<0 incrementa streak; con profit>0 lo resetea
- [ ] `calc_position_size` con risk_pct=2 devuelve warning
- [ ] Lockout persiste tras reinicio del MCP
- [ ] `expectancy(30)` calcula correctamente con fixture de 30 deals
- [ ] No requiere conexión a internet ni a MT5
