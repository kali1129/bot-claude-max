# 02 — MCP de Trading (MetaTrader 5)

> El MCP que **toca el dinero real**. Conecta con MT5 vía la librería oficial Python `MetaTrader5`, expone tools para account info, market data y ejecución de órdenes — pero con guardas pre-trade hardcodeadas. Un solo bug aquí = $800 menos.

## Propósito

Ser la única vía por la que Claude puede afectar la cuenta. Todas las otras integraciones son lectura. Esta envía órdenes. Por eso:

1. **Hardcodea** las reglas críticas (1% riesgo, max 1 posición, R:R ≥ 1:2).
2. **Loggea** cada intento de orden (aceptado o rechazado) en `orders.jsonl`.
3. **Falla cerrado**: si cualquier check falla → no envía orden. Mejor perder oportunidad que dinero.

---

## ¿Por qué corre en Windows nativo (no en WSL)?

La librería `MetaTrader5` (PyPI) usa DLLs del terminal MT5 instalado en Windows. **No existe versión Linux/Mac**. Por eso:

```
WSL  ─ news-mcp        OK
WSL  ─ analysis-mcp    OK
WSL  ─ risk-mcp        OK
WIN  ─ trading-mt5-mcp ← OBLIGATORIO Windows nativo
```

El `command` en `claude_desktop_config.json` apunta al `python.exe` de Windows, no al de WSL.

---

## Arquitectura interna

```
┌──────────────────────────────────────────────┐
│   trading-mt5-mcp                            │
│                                              │
│   ┌────────────────────────────────────────┐ │
│   │ MT5 Connection Manager                 │ │
│   │   mt5.initialize() / shutdown()        │ │
│   └────────────────────────────────────────┘ │
│   ┌────────────────────────────────────────┐ │
│   │ Tools (read-only)                      │ │
│   │  - get_account_info()                  │ │
│   │  - get_open_positions()                │ │
│   │  - get_rates() / get_tick()            │ │
│   │  - get_trade_history()                 │ │
│   └────────────────────────────────────────┘ │
│   ┌────────────────────────────────────────┐ │
│   │ Pre-trade Guards (the safety belt)     │ │
│   │  1. daily_pl_pct check                 │ │
│   │  2. open_positions count <= 1          │ │
│   │  3. SL & TP both required              │ │
│   │  4. R:R ≥ 2.0 enforced                 │ │
│   │  5. lots <= MAX_LOTS_PER_TRADE         │ │
│   │  6. hour UTC not in BLOCKED_HOURS      │ │
│   │  7. risk_calculated <= 1% balance      │ │
│   └────────────────────────────────────────┘ │
│   ┌────────────────────────────────────────┐ │
│   │ Tools (write)                          │ │
│   │  - place_order()  ← guardas activas    │ │
│   │  - close_position()                    │ │
│   │  - modify_sl_tp()  (solo a favor)      │ │
│   └────────────────────────────────────────┘ │
│   ┌────────────────────────────────────────┐ │
│   │ Logger → ~/mcp/logs/orders.jsonl       │ │
│   └────────────────────────────────────────┘ │
└──────────────────────────────────────────────┘
                   │
                   ▼
            ┌──────────────┐
            │  MT5 Terminal │  ← Windows
            │  (broker)     │
            └──────────────┘
```

---

## Estructura de archivos

```
trading-mt5-mcp/
├── server.py
├── requirements.txt
├── .env                      # MT5_LOGIN, MT5_PASSWORD, MT5_SERVER
├── .env.example
├── lib/
│   ├── connection.py         # connect/reconnect logic
│   ├── guards.py             # 7 pre-trade checks
│   ├── orders.py             # send_order wrapper
│   └── logger.py             # JSONL logger
└── tests/
    └── test_guards.py        # tests aislados de guardas (sin tocar MT5)
```

## Dependencies

```
mcp>=1.0.0
MetaTrader5>=5.0.45
pandas>=2.2
python-dotenv>=1.0.1
pydantic>=2.6
```

## Variables de entorno

| Var | Obligatoria | Notas |
|---|---|---|
| `MT5_LOGIN` | sí | ID numérico de cuenta |
| `MT5_PASSWORD` | sí | **Contraseña Investor** si quieres modo lectura, master para trading |
| `MT5_SERVER` | sí | ej: `Pepperstone-Demo`, `ICMarketsSC-Live01` |
| `MT5_PATH` | no | path al `terminal64.exe` si tienes varios MT5 instalados |
| `MAX_LOTS_PER_TRADE` | no | cap absoluto, default `0.5` |
| `BLOCKED_HOURS_UTC` | no | rangos donde NO operar, default `21:00-07:00` |
| `LOG_LEVEL` | no | `INFO` |

⚠️ Empieza con cuenta DEMO. **NO toques `.env` de cuenta real hasta haber pasado 2 semanas / 40 trades demo con expectancy > +0.30R.**

---

## Constantes hardcodeadas (no se sobrescriben con env)

```python
# Estas NO se exponen como env. Son la última línea de defensa.
MAX_RISK_PER_TRADE_PCT = 1.0      # nunca arriesgar más de 1%
MAX_DAILY_LOSS_PCT     = 3.0      # halt diario al -3%
MAX_OPEN_POSITIONS     = 1        # nunca más de 1 abierta
MIN_RR                 = 2.0      # R:R mínimo 1:2
```

Cambiar estos requeriría editar el código y recompilar el MCP. Eso es deliberado.

---

## Tools expuestas (8)

### 1. `initialize_mt5() → dict`
Conecta al terminal. Llamada idempotente (auto-skip si ya conectado).

```json
{
  "connected": true,
  "account": {
    "login": 12345678,
    "server": "Pepperstone-Demo",
    "broker": "Pepperstone Group Ltd",
    "currency": "USD",
    "leverage": 30
  }
}
```

### 2. `get_account_info() → dict`
Estado actual de cuenta + P&L del día calculado desde deals.

```json
{
  "balance": 800.00,
  "equity": 812.50,
  "margin_free": 805.40,
  "margin_level": 4350.0,
  "profit": 12.50,                  // unrealized
  "daily_pl_usd": 12.50,            // realized + unrealized today
  "daily_pl_pct": 1.56,
  "open_positions_count": 1
}
```

### 3. `get_open_positions() → list`
Lista normalizada (debería tener ≤ 1 elemento siempre).

```json
[{
  "ticket": 123456789,
  "symbol": "EURUSD",
  "side": "buy",
  "lots": 0.03,
  "entry": 1.0850,
  "current": 1.0865,
  "sl": 1.0830,
  "tp": 1.0890,
  "profit_usd": 4.50,
  "open_time_utc": "2026-01-15T13:45:00Z"
}]
```

### 4. `get_rates(symbol, timeframe="M15", n=200) → list`
OHLCV. Timeframe acepta: `M1, M5, M15, M30, H1, H4, D1`.

```json
[
  {"time": "2026-01-15T13:45:00Z", "open": 1.0850, "high": 1.0858, "low": 1.0848, "close": 1.0855, "volume": 1245},
  ...
]
```

### 5. `get_tick(symbol) → dict`
Precio actual con bid/ask/spread.

### 6. `place_order(...)` ⚠️ TOOL CRÍTICA

**Args:**
- `symbol` (str)
- `side` ("buy" | "sell")
- `lots` (float)
- `sl` (float) — **obligatorio**
- `tp` (float) — **obligatorio**
- `comment` (str, default `"claude"`)

**Pre-checks (en orden):**
```python
def place_order(symbol, side, lots, sl, tp, comment):
    log_attempt({"symbol": symbol, "side": side, "lots": lots, ...})

    # CHECK 1: SL & TP requeridos
    if sl is None or tp is None:
        return reject("SL_TP_REQUIRED", "SL y TP obligatorios")

    # CHECK 2: hora permitida
    hour = datetime.now(timezone.utc).hour
    if hour in BLOCKED_HOURS:
        return reject("BLOCKED_HOUR", f"Hora {hour} UTC en blackout")

    # CHECK 3: máximo 1 posición
    positions = get_open_positions()
    if len(positions) >= MAX_OPEN_POSITIONS:
        return reject("MAX_POSITIONS", "Ya hay 1 posición abierta")

    # CHECK 4: daily drawdown
    acc = get_account_info()
    if acc["daily_pl_pct"] <= -MAX_DAILY_LOSS_PCT:
        return reject("DAILY_LOSS_LIMIT", f"DD del día {acc['daily_pl_pct']}%")

    # CHECK 5: lotaje cap
    if lots > MAX_LOTS_PER_TRADE:
        return reject("LOTS_CAP", f"Lotaje {lots} > cap {MAX_LOTS_PER_TRADE}")

    # CHECK 6: R:R mínimo
    tick = get_tick(symbol)
    entry = tick["ask"] if side == "buy" else tick["bid"]
    sl_dist = abs(entry - sl)
    tp_dist = abs(tp - entry)
    if sl_dist == 0:
        return reject("SL_INVALID", "SL == entry")
    rr = tp_dist / sl_dist
    if rr < MIN_RR:
        return reject("RR_TOO_LOW", f"R:R {rr:.2f} < {MIN_RR}")

    # CHECK 7: lados de SL/TP correctos
    if side == "buy" and (sl >= entry or tp <= entry):
        return reject("SL_TP_SIDE", "SL debe ser < entry, TP > entry para buy")
    if side == "sell" and (sl <= entry or tp >= entry):
        return reject("SL_TP_SIDE", "SL debe ser > entry, TP < entry para sell")

    # CHECK 8: riesgo en USD <= 1% balance
    sym_info = mt5.symbol_info(symbol)
    risk_usd = lots * (sl_dist / sym_info.trade_tick_size) * sym_info.trade_tick_value
    max_risk_usd = acc["balance"] * MAX_RISK_PER_TRADE_PCT / 100
    if risk_usd > max_risk_usd * 1.05:  # 5% tolerancia por redondeo
        return reject("RISK_EXCEEDED", f"${risk_usd:.2f} > ${max_risk_usd:.2f}")

    # ENVÍO REAL
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lots,
        "type": mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL,
        "price": entry,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": 20260115,
        "comment": comment[:31],
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    result = mt5.order_send(request)
    log_result(result)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        return reject("MT5_REJECTED", f"retcode={result.retcode}: {result.comment}")
    return {"ok": True, "ticket": result.order, "filled_at": result.price}
```

**Returns (success):**
```json
{"ok": true, "ticket": 123456789, "filled_at": 1.08502}
```

**Returns (rejected):**
```json
{"ok": false, "reason": "RR_TOO_LOW", "detail": "R:R 1.45 < 2.0"}
```

### 7. `close_position(ticket) → dict`
Cierra posición por ticket. Sin guardas (cerrar siempre debe poder).

### 8. `modify_sl_tp(ticket, sl, tp) → dict`
**Guarda especial**: solo permite mover SL **a favor** (nunca alejarlo).

```python
def modify_sl_tp(ticket, sl, tp):
    pos = get_position(ticket)
    if pos["side"] == "buy":
        if sl is not None and sl < pos["sl"]:
            return reject("SL_AGAINST", "No mover SL en contra (alejarlo)")
    else:  # sell
        if sl is not None and sl > pos["sl"]:
            return reject("SL_AGAINST", "No mover SL en contra (alejarlo)")
    # … aplicar
```

---

## Logging

Cada llamada a `place_order` (aceptada o rechazada) se escribe en `~/mcp/logs/orders.jsonl`:

```jsonl
{"ts":"2026-01-15T13:50:11Z","tool":"place_order","input":{"symbol":"EURUSD","side":"buy","lots":0.03,"sl":1.083,"tp":1.089},"result":{"ok":false,"reason":"RR_TOO_LOW","detail":"R:R 1.85 < 2.0"}}
{"ts":"2026-01-15T14:02:33Z","tool":"place_order","input":{"symbol":"EURUSD","side":"buy","lots":0.03,"sl":1.0830,"tp":1.0890},"result":{"ok":true,"ticket":123456789}}
```

Esto te permite auditar **POR QUÉ** se rechazaron órdenes (clave para debugging y para que tú aprendas en qué momentos Claude se desvía).

---

## Configuración Claude Desktop

```json
{
  "mcpServers": {
    "trading": {
      "command": "C:\\Python311\\python.exe",
      "args": ["C:\\Users\\TU_USUARIO\\mcp\\trading-mt5-mcp\\server.py"],
      "env": {
        "MT5_LOGIN": "12345678",
        "MT5_PASSWORD": "tu_password",
        "MT5_SERVER": "Pepperstone-Demo"
      }
    }
  }
}
```

⚠️ El `command` apunta al python.exe de Windows. Si lo apuntas al de WSL fallará al importar `MetaTrader5`.

---

## Flujo de testing manual

1. **Solo conexión** (DEMO):
   ```
   Tú: "Verifica conexión MT5 y dame estado de cuenta"
   Claude: trading.initialize_mt5() → connected
           trading.get_account_info() → balance $10000 (demo)
   ```

2. **Lectura de mercado**:
   ```
   Tú: "Trae las últimas 50 velas M15 de EURUSD"
   Claude: trading.get_rates("EURUSD", "M15", 50) → [...]
   ```

3. **Test de guardas (sin enviar orden)**:
   ```
   Tú: "Prueba enviar una orden con R:R 1:1 a ver si la rechaza"
   Claude: trading.place_order(...) → {ok: false, reason: "RR_TOO_LOW"}
   ```
   ✅ Si la rechaza → guardas funcionan.

4. **Trade real demo**:
   ```
   Tú: "Setup ORB en NAS100 long, entry 18250, SL 18230, TP 18310, lots 0.1"
   Claude: trading.place_order(...) → {ok: true, ticket: ...}
   ```

---

## Migración a cuenta REAL ($800)

Solo cuando:
- ✅ ≥40 trades en demo documentados
- ✅ expectancy > +0.30R sobre últimos 30
- ✅ 0 violaciones de regla en 2 semanas seguidas
- ✅ Te sientes ABURRIDO ejecutando

Cambios:
1. Edita `.env`:
   ```
   MT5_LOGIN=tu_cuenta_real
   MT5_PASSWORD=tu_password_real
   MT5_SERVER=tu_broker_live
   ```
2. **Primera semana real**: usa `MAX_RISK_PER_TRADE_PCT = 0.5` (no 1%). Edita esa constante en `server.py`. Después de 7 días sin violaciones, sube a 1%.
3. Reinicia Claude Desktop.

---

## Edge cases / troubleshooting

| Problema | Causa | Fix |
|---|---|---|
| `mt5.initialize()` devuelve `False` | terminal MT5 cerrado | Abre el terminal manualmente y reintenta |
| `IPC timeout` | terminal MT5 freezeado | Cierra terminal, reabre, reinicia MCP |
| `Invalid stops` retcode 10016 | SL/TP demasiado cerca del precio | Respeta `symbol_info.trade_stops_level` |
| `Trade disabled` retcode 10017 | "Allow algorithmic trading" desactivado | MT5 → Tools → Options → Expert Advisors → check ✅ |
| Posición no abre | spread excesivo en news | Pre-check de spread vs `symbol_info.spread` |
| `place_order` lento (>3s) | conexión broker lenta | Ajusta `deviation` y mejora red |

---

## Checklist de validación

- [ ] Conecta a DEMO sin errores
- [ ] Las 7 guardas rechazan correctamente (test cada una con caso adversarial)
- [ ] `modify_sl_tp` rechaza alejar SL
- [ ] `orders.jsonl` registra cada intento
- [ ] Usa `magic` number único (para diferenciar trades del MCP de otros)
- [ ] `.env` excluido de git
- [ ] Tests automáticos en `tests/test_guards.py` pasan en CI o local

---

## NUNCA hacer esto

```python
# ❌ DESACTIVAR GUARDA "TEMPORALMENTE"
# if BYPASS_GUARDS:
#     return mt5.order_send(...)

# ❌ ACEPTAR R:R DINÁMICO < 2.0
# MIN_RR = 1.5  ← NO

# ❌ MULTIPLES POSICIONES
# MAX_OPEN_POSITIONS = 3  ← NO

# ❌ MAGIC NUMBER GENÉRICO
# request["magic"] = 0  ← imposible de filtrar después
```

Si estás tentado de hacer cualquiera de las anteriores, **para de operar y revisa por qué quieres saltarte la regla**. Esa pulsión es exactamente lo que perdió tus miles antes.
