# 09 — Módulo de reglas compartidas

> Un único módulo Python que define los límites duros del sistema. **Tanto
> `risk-mcp` como `trading-mt5-mcp` lo importan**. Si dos MCPs tienen su propia
> copia de `MAX_RISK_PER_TRADE_PCT`, alguno se va a quedar atrás cuando lo
> ajustes y el sistema mentirá sobre su disciplina.

## Propósito

Single source of truth para las constantes que no se negocian. Vive fuera del
árbol de cualquier MCP individual:

```
~/mcp/_shared/
├── __init__.py
├── rules.py
├── halt.py            (ver doc 10)
└── tests/
    ├── test_rules.py
    └── test_halt.py
```

Cada MCP arranca con `~/mcp/_shared` en su `PYTHONPATH` (ver más abajo).

## Contenido de `rules.py`

```python
"""Shared invariants for the trading stack.

Edit ONLY when the user explicitly raises the rule in the dashboard's
Rules section *and* commits the change. Do not import this module and
shadow values locally — the whole point is one place to look.
"""
from dataclasses import dataclass

__version__ = "1.0.0"

# Hard-coded ceilings. These are not env-overridable.
MAX_RISK_PER_TRADE_PCT: float = 1.0
MAX_DAILY_LOSS_PCT:     float = 3.0
MAX_OPEN_POSITIONS:     int   = 1
MIN_RR:                 float = 2.0
MAX_TRADES_PER_DAY:     int   = 5
MAX_CONSECUTIVE_LOSSES: int   = 3

# Time-based blackout (UTC). Inclusive start, exclusive end.
BLOCKED_HOUR_START_UTC: int = 21  # 21:00 UTC
BLOCKED_HOUR_END_UTC:   int =  7  # 07:00 UTC


@dataclass(frozen=True)
class RuleSnapshot:
    """Immutable snapshot of all rule values for logging/auditing."""
    version: str
    max_risk_per_trade_pct: float
    max_daily_loss_pct: float
    max_open_positions: int
    min_rr: float
    max_trades_per_day: int
    max_consecutive_losses: int
    blocked_hours: tuple[int, int]


def snapshot() -> RuleSnapshot:
    return RuleSnapshot(
        version=__version__,
        max_risk_per_trade_pct=MAX_RISK_PER_TRADE_PCT,
        max_daily_loss_pct=MAX_DAILY_LOSS_PCT,
        max_open_positions=MAX_OPEN_POSITIONS,
        min_rr=MIN_RR,
        max_trades_per_day=MAX_TRADES_PER_DAY,
        max_consecutive_losses=MAX_CONSECUTIVE_LOSSES,
        blocked_hours=(BLOCKED_HOUR_START_UTC, BLOCKED_HOUR_END_UTC),
    )


def is_blocked_hour(utc_hour: int) -> bool:
    """Wrap-around aware. 21..6 → blocked."""
    if BLOCKED_HOUR_START_UTC <= BLOCKED_HOUR_END_UTC:
        return BLOCKED_HOUR_START_UTC <= utc_hour < BLOCKED_HOUR_END_UTC
    return utc_hour >= BLOCKED_HOUR_START_UTC or utc_hour < BLOCKED_HOUR_END_UTC


def rr(entry: float, sl: float, tp: float) -> float:
    """Reward-to-risk ratio. Positive number; 0 if invalid geometry."""
    risk = abs(entry - sl)
    if risk == 0:
        return 0.0
    reward = abs(tp - entry)
    return reward / risk


def passes_rr(entry: float, sl: float, tp: float, min_rr: float = MIN_RR) -> bool:
    return rr(entry, sl, tp) >= min_rr


def max_risk_dollars(balance: float, risk_pct: float | None = None) -> float:
    pct = risk_pct if risk_pct is not None else MAX_RISK_PER_TRADE_PCT
    if pct > MAX_RISK_PER_TRADE_PCT:
        pct = MAX_RISK_PER_TRADE_PCT
    return round(balance * pct / 100.0, 2)
```

## Tests obligatorios (`tests/test_rules.py`)

```python
import pytest
from rules import (
    MIN_RR, MAX_RISK_PER_TRADE_PCT,
    rr, passes_rr, is_blocked_hour, max_risk_dollars, snapshot,
)


def test_constants_are_within_safe_envelope():
    # Smoke: if any of these moves, a human must approve the change.
    assert MIN_RR >= 2.0
    assert MAX_RISK_PER_TRADE_PCT <= 1.0


@pytest.mark.parametrize("entry,sl,tp,expected", [
    (1.0850, 1.0830, 1.0890, 2.0),
    (1.0850, 1.0830, 1.0870, 1.0),
    (1.0850, 1.0850, 1.0870, 0.0),  # zero risk → 0
])
def test_rr(entry, sl, tp, expected):
    assert rr(entry, sl, tp) == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("entry,sl,tp,ok", [
    (1.0850, 1.0830, 1.0890, True),   # 1:2 exact
    (1.0850, 1.0830, 1.0889, False),  # 1:1.95
])
def test_passes_rr_boundary(entry, sl, tp, ok):
    assert passes_rr(entry, sl, tp) is ok


@pytest.mark.parametrize("h,blocked", [
    (0, True), (3, True), (6, True),
    (7, False), (12, False), (20, False),
    (21, True), (23, True),
])
def test_is_blocked_hour(h, blocked):
    assert is_blocked_hour(h) is blocked


def test_max_risk_dollars_caps_above_rule():
    assert max_risk_dollars(800, 5.0) == 8.0  # capped to 1%
    assert max_risk_dollars(800, 0.5) == 4.0  # below cap honoured


def test_snapshot_is_frozen():
    s = snapshot()
    with pytest.raises(Exception):
        s.max_risk_per_trade_pct = 99.0  # type: ignore
```

## Cómo cada MCP lo consume

```python
# trading-mt5-mcp/server.py  (encabezado)
import sys, os
sys.path.insert(0, os.path.expanduser("~/mcp/_shared"))
from rules import (
    MAX_RISK_PER_TRADE_PCT, MAX_DAILY_LOSS_PCT, MAX_OPEN_POSITIONS,
    MIN_RR, is_blocked_hour, passes_rr, max_risk_dollars, snapshot,
)

# … usar las constantes y helpers, NUNCA redefinirlas.
```

```python
# risk-mcp/server.py  (idéntico patrón)
import sys, os
sys.path.insert(0, os.path.expanduser("~/mcp/_shared"))
from rules import (
    MAX_RISK_PER_TRADE_PCT, MAX_DAILY_LOSS_PCT,
    MAX_CONSECUTIVE_LOSSES, MAX_TRADES_PER_DAY,
    is_blocked_hour, max_risk_dollars,
)
```

## Cómo el dashboard lo consume

El dashboard FastAPI ya define las mismas constantes en
`backend/plan_content.py`. Cuando armes el sistema, edita ese archivo para que
**lea desde** `~/mcp/_shared/rules.py` cuando el path exista (path opcional
porque el dashboard puede correr sin los MCPs en una máquina dev). Si no
existe, fallback a las constantes locales actuales.

```python
# backend/plan_content.py
import sys, os, importlib.util

_shared_path = os.path.expanduser("~/mcp/_shared/rules.py")
if os.path.exists(_shared_path):
    spec = importlib.util.spec_from_file_location("rules", _shared_path)
    _rules = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_rules)
    MAX_RISK_PER_TRADE_PCT = _rules.MAX_RISK_PER_TRADE_PCT
    MAX_DAILY_LOSS_PCT = _rules.MAX_DAILY_LOSS_PCT
    MAX_CONSECUTIVE_LOSSES = _rules.MAX_CONSECUTIVE_LOSSES
    MIN_RR = _rules.MIN_RR
else:
    MAX_RISK_PER_TRADE_PCT = 1.0
    # … etc fallback
```

## Cómo cambiar una regla (procedimiento)

1. Editar `~/mcp/_shared/rules.py`.
2. Bump `__version__` (semver). Cualquier cambio a un valor numérico es minor; cambio a un nombre o función es major.
3. Correr `pytest ~/mcp/_shared/tests/`.
4. Reiniciar Claude Desktop (los MCPs releen el módulo al arrancar).
5. Editar `Rules.jsx` del dashboard si la regla es visible al usuario, así el plan UI no miente.

⚠️ **Lo que NO se hace**: variables de entorno que sobrescriban estos valores.
Si lo necesitas, el sistema está mal: estás intentando bajar el listón sin
que quede registro.

## Por qué este módulo importa más que cualquier otro

Si hay UN único bug que puede convertir tu cuenta de $800 en cero más rápido
que ningún otro, es:

> el `risk-mcp` calcula `max_risk_dollars(balance, 1.0)` con su copia de la
> constante `MAX_RISK_PER_TRADE_PCT = 1.0`, pero el `trading-mt5-mcp` quedó con
> una copia vieja `MAX_RISK_PER_TRADE_PCT = 2.0` después de un copy-paste, y la
> guarda 7 (`risk_usd > max_risk_usd * 1.05`) pasa una orden con el doble de
> tamaño.

Ese bug **no puede existir** si ambos MCPs leen del mismo módulo. Por eso
existe este doc.
