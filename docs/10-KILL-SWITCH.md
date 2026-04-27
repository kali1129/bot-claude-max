# 10 — Kill-switch + modos de trading (paper / demo / live)

> Dos mecanismos baratos que evitan los dos peores escenarios:
> 1. Claude alucina en bucle y manda 50 órdenes (kill-switch).
> 2. Pruebas un cambio en el MCP y la primera orden ya es real (modos).

## El kill-switch en 30 segundos

Un archivo en disco. Si existe, el `trading-mt5-mcp` se niega a colocar
cualquier orden. Punto.

```
~/mcp/.HALT
```

Contenido (texto plano):

```json
{"halted_at": "2026-04-27T15:32:11Z", "reason": "manual halt from dashboard"}
```

`place_order` lo verifica como **primera** guarda, antes que cualquier otra:

```python
def place_order(symbol, side, lots, sl, tp, comment, client_order_id=None):
    if halt.is_halted():
        return reject("HALTED", f"Kill-switch activo: {halt.reason()}")
    # … resto de guardas
```

Ventajas:
- Latencia cero, no requiere red ni IPC con el dashboard.
- Funciona aunque el dashboard esté muerto.
- El usuario lo puede crear desde terminal: `touch ~/mcp/.HALT`.
- Un script de cron puede activarlo: "si la equity baja >5% en 1h → touch HALT".

## Implementación de `~/mcp/_shared/halt.py`

```python
"""File-based kill-switch shared by all MCPs."""
import json
import os
from datetime import datetime, timezone
from typing import Optional

HALT_FILE = os.path.expanduser(os.environ.get("HALT_FILE", "~/mcp/.HALT"))


def is_halted() -> bool:
    return os.path.exists(HALT_FILE)


def reason() -> Optional[str]:
    if not is_halted():
        return None
    try:
        with open(HALT_FILE) as f:
            data = json.load(f)
            return data.get("reason", "no reason given")
    except (json.JSONDecodeError, OSError):
        return "halt file present but unreadable"


def halt(reason: str) -> dict:
    os.makedirs(os.path.dirname(HALT_FILE), exist_ok=True)
    payload = {
        "halted_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason or "no reason",
    }
    tmp = HALT_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, HALT_FILE)
    return {"ok": True, "halted": True, **payload}


def resume() -> dict:
    if not is_halted():
        return {"ok": True, "was_halted": False}
    os.remove(HALT_FILE)
    return {"ok": True, "was_halted": True, "resumed_at": datetime.now(timezone.utc).isoformat()}
```

## Tests obligatorios

```python
def test_halt_creates_file(tmp_path, monkeypatch):
    monkeypatch.setattr("halt.HALT_FILE", str(tmp_path / ".HALT"))
    assert not halt.is_halted()
    halt.halt("test")
    assert halt.is_halted()
    halt.resume()
    assert not halt.is_halted()


def test_halt_survives_corrupt_file(tmp_path, monkeypatch):
    p = tmp_path / ".HALT"
    p.write_text("not-json")
    monkeypatch.setattr("halt.HALT_FILE", str(p))
    assert halt.is_halted()
    assert "unreadable" in halt.reason()
```

## Endpoints en el dashboard

Añadir a `backend/server.py`:

```python
HALT_FILE = os.path.expanduser(os.environ.get("HALT_FILE", "~/mcp/.HALT"))

@api_router.post("/halt", dependencies=[Depends(require_token)])
async def halt_now(reason: str = "dashboard button"):
    os.makedirs(os.path.dirname(HALT_FILE), exist_ok=True)
    with open(HALT_FILE, "w") as f:
        json.dump({"halted_at": datetime.now(timezone.utc).isoformat(), "reason": reason}, f)
    return {"halted": True}

@api_router.delete("/halt", dependencies=[Depends(require_token)])
async def halt_resume():
    if os.path.exists(HALT_FILE):
        os.remove(HALT_FILE)
        return {"resumed": True}
    return {"resumed": False, "reason": "not halted"}

@api_router.get("/halt")
async def halt_status():
    if os.path.exists(HALT_FILE):
        with open(HALT_FILE) as f:
            return {"halted": True, "info": json.load(f)}
    return {"halted": False}
```

Y un botón rojo grande en `Overview.jsx`:

```jsx
<button
  data-testid="halt-trading-button"
  onClick={async () => {
    if (!window.confirm("HALT all trading? trading-mcp will refuse orders until resumed.")) return;
    await axios.post(`${API}/halt`, { reason: "dashboard manual" });
    setHalted(true);
  }}
  className="bg-red-600 text-white font-bold px-6 py-3 rounded">
  🛑 HALT TRADING
</button>
```

## Modos de trading

Variable de entorno **única**:

```
TRADING_MODE=paper   # default
TRADING_MODE=demo    # explicit opt-in, MT5 demo account
TRADING_MODE=live    # explicit opt-in, MT5 real account
```

### `paper` (default — siempre el modo de arranque tras un cambio)

- `place_order` **no llama** `mt5.order_send`.
- Genera un ticket sintético (`int(time.time() * 1000)`).
- Loggea en `paper_orders.jsonl` (esquema idéntico a `orders.jsonl`).
- Devuelve `{ok: true, ticket: <fake>, mode: "paper"}`.
- Sync hook al dashboard sigue funcionando: el journal recibe el deal con `source: "paper"`.

```python
def place_order(...):
    # … (after kill-switch and all guards)
    if MODE == "paper":
        ticket = int(time.time() * 1000)
        log_paper({"client_order_id": coid, "symbol": symbol, "lots": lots, ...,
                   "ticket": ticket, "mode": "paper"})
        return {"ok": True, "ticket": ticket, "mode": "paper", "filled_at": entry}
    # MODE in ("demo", "live")
    result = mt5.order_send(request)
    ...
```

### `demo` (entrenamiento real con datos del broker)

- Idéntico a `live`, pero apunta al servidor demo.
- Sirve para validar latencia, slippage, comisiones reales.

### `live`

- Solo después de pasar la batería de validación de `docs/02-MCP-TRADING.md`.
- Primera semana: `MAX_RISK_PER_TRADE_PCT = 0.5` (override **manual** en `_shared/rules.py`, con reset programado en 7 días).

## Cómo cambiar de modo de forma segura

1. **Pre-flight** (antes de cualquier cambio):
   ```bash
   touch ~/mcp/.HALT  # bloquear órdenes mientras configuras
   ```
2. Editar `.env` del `trading-mt5-mcp`. Cambiar `TRADING_MODE`.
3. Reiniciar Claude Desktop (relee el `.env`).
4. Verificar:
   ```
   trading.health()
   → {"version": "...", "mode": "demo", "connected": true}
   ```
5. **Resume** sólo cuando estés listo:
   ```bash
   rm ~/mcp/.HALT
   ```

## Anti-patrones explícitos

```python
# ❌ Modo "auto" que decide por sí solo cuándo es real
TRADING_MODE = "demo" if datetime.now().hour > 9 else "live"

# ❌ Sin kill-switch
def place_order(...):
    # check guards but no halt check
    return mt5.order_send(...)

# ❌ Kill-switch que se ignora "porque es DEMO"
if MODE != "live" or halt.is_halted():
    return reject(...)
# La guarda debe correr SIEMPRE; el modo no la exime.
```

## Por qué este doc existe

Cuando el sistema falla en producción, el operador tiene segundos para parar
todo. No tendrá tiempo de:
- abrir el editor JSON de Claude Desktop,
- recordar cómo se reinicia el MCP,
- esperar que la dashboard cargue.

Pero `touch ~/mcp/.HALT` lo puede correr con los ojos cerrados desde cualquier
terminal abierta. Eso es la diferencia entre perder $40 y perder los $800.
