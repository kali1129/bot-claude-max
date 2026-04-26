# 03 — MCP de Análisis Técnico

> Servidor MCP que **no toca red ni MT5**. Recibe arrays OHLCV como argumentos y devuelve indicadores, estructura de mercado, soportes/resistencias, patrones de vela y un score 0-100 del setup. Es el cerebro analítico, puro y testeable.

## Propósito

Centralizar TODO el análisis técnico en un solo módulo, separado de:
- la fuente de datos (lo provee `trading-mcp`),
- la decisión de operar (lo decide la orquestación + `risk-mcp`).

Así puedes:
1. Testearlo offline con CSVs.
2. Reemplazar internals (ej: cambiar de `pandas-ta` a `talib`) sin afectar nadie.
3. Llamarlo desde scripts de backtest.

---

## Arquitectura interna

```
┌──────────────────────────────────────────────┐
│  analysis-mcp (puro, sin estado, sin red)    │
│                                              │
│  Inputs: list[{time, open, high, low,        │
│                close, volume}]               │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │ Indicators                              │  │
│  │   EMA, SMA, RSI, ATR, MACD, BB,         │  │
│  │   VWAP, SuperTrend                      │  │
│  └────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────┐  │
│  │ Market Structure                        │  │
│  │   swing detection (pivots N velas)      │  │
│  │   classify HH/HL/LH/LL                  │  │
│  │   trend / range / breakout              │  │
│  └────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────┐  │
│  │ Support / Resistance                    │  │
│  │   clustering de máximos y mínimos       │  │
│  │   touches counter                       │  │
│  └────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────┐  │
│  │ Candlestick Patterns                    │  │
│  │   pin bar, engulfing, doji, inside,     │  │
│  │   fakey                                 │  │
│  └────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────┐  │
│  │ Multi-Timeframe Bias                    │  │
│  │   H4 trend + M15 alignment              │  │
│  └────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────┐  │
│  │ Setup Scorer (the gate)                 │  │
│  │   suma ponderada → 0-100                │  │
│  │   < 70: SKIP                            │  │
│  │   ≥ 70: TAKE                            │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  Output: structured JSON                     │
└──────────────────────────────────────────────┘
```

### Por qué "sin estado, sin red"
Todo input viene como argumento. Toda salida es deterministica. Esto es un MCP que puedes llamar 1000 veces sin importar el orden, sin contención y sin timeouts. Es una librería de cálculo expuesta vía MCP.

---

## Estructura de archivos

```
analysis-mcp/
├── server.py
├── requirements.txt
├── lib/
│   ├── indicators.py
│   ├── structure.py
│   ├── sr.py
│   ├── candles.py
│   ├── mtf.py
│   └── scorer.py
└── tests/
    ├── fixtures/
    │   ├── eurusd_m15_trending.csv
    │   ├── xauusd_m15_range.csv
    │   └── nas100_m15_breakout.csv
    └── test_*.py
```

## Dependencies

```
mcp>=1.0.0
pandas>=2.2
numpy>=1.26
pandas-ta>=0.3.14b
pydantic>=2.6
```

> Alternativa: `TA-Lib` es más rápido pero requiere build C. `pandas-ta` es Python puro y suficiente para todos los indicadores que usaremos.

## Variables de entorno

Ninguna. Este MCP es puro. La única "config" son los hyperparámetros de scoring (ver `scorer.py`).

---

## Tools expuestas (6)

### 1. `indicators(ohlcv, periods=None) → dict`

Calcula todos los indicadores de un golpe. Devuelve valores actuales y anteriores (para detectar cruces).

**Args:**
- `ohlcv`: lista de dicts ordenada cronológicamente (más vieja primero)
- `periods` (opcional): override de períodos default

**Default periods:**
```python
DEFAULTS = {
    "ema_fast": 20,
    "ema_mid": 50,
    "ema_slow": 200,
    "rsi": 14,
    "atr": 14,
    "macd": (12, 26, 9),
    "bb": (20, 2),
    "supertrend": (10, 3),
}
```

**Returns:**
```json
{
  "current": {
    "close": 1.0855,
    "ema20": 1.0850,
    "ema50": 1.0840,
    "ema200": 1.0810,
    "rsi14": 58.2,
    "atr14": 0.00045,
    "macd": 0.00012,
    "macd_signal": 0.00008,
    "macd_hist": 0.00004,
    "bb_upper": 1.0865,
    "bb_lower": 1.0835,
    "vwap": 1.0848,
    "supertrend": 1.0820,
    "supertrend_dir": "up"
  },
  "previous": { ... },
  "crossovers": {
    "ema20_above_50": true,
    "macd_above_signal": true,
    "rsi_crossed_50": "up"
  }
}
```

### 2. `market_structure(ohlcv, swing_n=5) → dict`

Detecta swings y clasifica la estructura.

**Args:**
- `ohlcv`: lista
- `swing_n`: cuantas velas a cada lado para confirmar pivote (default 5)

**Lógica:**
- Pivote alto: vela cuyo `high` > N velas a izquierda y derecha.
- Pivote bajo: análogo con `low`.
- Tomamos los últimos 4 swings y clasificamos:

| Patrón | Estructura |
|---|---|
| HH+HL+HH+HL | uptrend |
| LL+LH+LL+LH | downtrend |
| HH+LL alternado | range |
| HH→LH (cambio) | possible reversal |

**Returns:**
```json
{
  "trend": "uptrend",
  "last_4_swings": [
    {"type": "HL", "price": 1.0800, "time": "..."},
    {"type": "HH", "price": 1.0860, "time": "..."},
    {"type": "HL", "price": 1.0830, "time": "..."},
    {"type": "HH", "price": 1.0875, "time": "..."}
  ],
  "last_swing_high": 1.0875,
  "last_swing_low": 1.0830,
  "breakout_zone": {"upper": 1.0875, "lower": 1.0830}
}
```

### 3. `support_resistance(ohlcv, min_touches=2, tolerance_pct=0.15) → list`

Identifica niveles donde el precio ha rebotado o roto múltiples veces.

**Algoritmo:**
1. Extrae todos los swing highs y swing lows.
2. Clúster por proximidad (tolerance_pct del precio).
3. Cuenta touches por cluster.
4. Filtra por `min_touches`.
5. Ordena por fuerza (touches * recencia).

**Returns:**
```json
[
  {"level": 1.0875, "type": "resistance", "touches": 4, "last_touch": "...", "strength": 8.4},
  {"level": 1.0830, "type": "support",    "touches": 3, "last_touch": "...", "strength": 6.1},
  {"level": 1.0810, "type": "support",    "touches": 2, "last_touch": "...", "strength": 3.0}
]
```

### 4. `candlestick_patterns(ohlcv) → dict`

Detecta patrones en las últimas 3 velas.

**Patrones soportados:**
- **Pin bar**: cuerpo pequeño + mecha larga (>= 2x cuerpo) en una dirección
- **Engulfing**: vela2 cubre completamente cuerpo de vela1 en sentido opuesto
- **Doji**: cuerpo < 10% rango total
- **Inside bar**: vela2 contenida dentro de vela1
- **Fakey**: inside bar + ruptura falsa

**Returns:**
```json
{
  "pattern": "bullish_engulfing",
  "bias_implied": "buy",
  "confidence": 0.75,
  "candle_index": -1,
  "context_note": "En zona de soporte, formato limpio"
}
```

### 5. `mtf_bias(ohlcv_h4, ohlcv_m15) → dict`

El "Multi-Time-Frame bias": pregunta clave del análisis profesional. ¿M15 está en la dirección de H4?

**Lógica:**
```python
def mtf_bias(h4, m15):
    h4_close = h4[-1]["close"]
    h4_ema200 = ema(h4, 200)[-1]
    h4_bias = "bullish" if h4_close > h4_ema200 else "bearish"

    m15_struct = market_structure(m15)
    m15_bias = m15_struct["trend"]

    aligned = (
        (h4_bias == "bullish" and m15_bias == "uptrend") or
        (h4_bias == "bearish" and m15_bias == "downtrend")
    )
    return {
        "h4_bias": h4_bias,
        "m15_bias": m15_bias,
        "aligned": aligned,
        "side": "buy" if aligned and h4_bias == "bullish" else
                "sell" if aligned and h4_bias == "bearish" else None,
    }
```

**Returns:**
```json
{
  "h4_bias": "bullish",
  "m15_bias": "uptrend",
  "aligned": true,
  "side": "buy",
  "confidence": "high"
}
```

### 6. `score_setup(ohlcv, side, entry, sl, tp, h4_ohlcv=None) → dict` ⭐ TOOL CLAVE

El **gate** del sistema. Solo si score ≥ 70 → recommendation = TAKE.

**Rúbrica de scoring:**

| Criterio | Puntos | Cómo |
|---|---|---|
| Trend M15 alineado con `side` | +25 | uptrend & buy, o downtrend & sell |
| MTF bias aligned (H4 + M15) | +20 | si h4_ohlcv provisto |
| Entry en zona S/R con ≥ 2 touches | +15 | distancia < 0.3 ATR del nivel |
| Patrón de vela en favor | +10 | engulfing/pin bar/fakey en dirección |
| RSI no extremo (30-70) en pullback | +10 | evita overbought/oversold |
| R:R ≥ 2.5 | +10 | premia trades con buen R:R |
| ATR no en mínimos (mercado activo) | +10 | atr14 ≥ 0.7× promedio últimos 50 |

Total max: 100 puntos.

**Returns:**
```json
{
  "score": 78,
  "breakdown": {
    "trend_aligned": 25,
    "mtf_aligned": 20,
    "in_sr_zone": 15,
    "candle_pattern": 10,
    "rsi_healthy": 0,
    "rr_premium": 0,
    "atr_active": 8
  },
  "recommendation": "TAKE",
  "reasoning": [
    "Trend M15 uptrend alineado con BUY",
    "H4 también bullish — MTF aligned",
    "Entry a 8 pips del soporte 1.0830 (4 touches)",
    "Bullish engulfing en vela actual",
    "R:R 2.0 (no premium pero válido)",
    "RSI 72 (overbought) — no suma puntos",
    "ATR activo (1.2× promedio)"
  ]
}
```

**Recommendation:**
- `score >= 70` → `"TAKE"`
- `60 <= score < 70` → `"WAIT"` (puede mejorar)
- `score < 60` → `"SKIP"`

---

## Server skeleton

```python
"""analysis-mcp v1.0.0 — Pure technical analysis."""
import logging
import sys
from typing import List, Dict, Optional
from mcp.server.fastmcp import FastMCP

from lib.indicators import compute_indicators
from lib.structure import detect_market_structure
from lib.sr import find_sr_levels
from lib.candles import detect_pattern
from lib.mtf import compute_mtf
from lib.scorer import score

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
log = logging.getLogger("analysis-mcp")

mcp = FastMCP("analysis")


@mcp.tool()
def indicators(ohlcv: List[Dict], periods: Optional[Dict] = None) -> Dict:
    """Computes EMA, RSI, MACD, ATR, BB, VWAP, SuperTrend."""
    return compute_indicators(ohlcv, periods or {})


@mcp.tool()
def market_structure(ohlcv: List[Dict], swing_n: int = 5) -> Dict:
    return detect_market_structure(ohlcv, swing_n)


@mcp.tool()
def support_resistance(ohlcv: List[Dict], min_touches: int = 2, tolerance_pct: float = 0.15) -> List[Dict]:
    return find_sr_levels(ohlcv, min_touches, tolerance_pct)


@mcp.tool()
def candlestick_patterns(ohlcv: List[Dict]) -> Dict:
    return detect_pattern(ohlcv)


@mcp.tool()
def mtf_bias(ohlcv_h4: List[Dict], ohlcv_m15: List[Dict]) -> Dict:
    return compute_mtf(ohlcv_h4, ohlcv_m15)


@mcp.tool()
def score_setup(
    ohlcv: List[Dict],
    side: str,
    entry: float,
    sl: float,
    tp: float,
    ohlcv_h4: Optional[List[Dict]] = None,
) -> Dict:
    return score(ohlcv, side, entry, sl, tp, ohlcv_h4)


if __name__ == "__main__":
    mcp.run()
```

---

## Configuración Claude Desktop

```json
{
  "mcpServers": {
    "analysis": {
      "command": "python",
      "args": ["C:\\Users\\TU_USUARIO\\mcp\\analysis-mcp\\server.py"]
    }
  }
}
```

(Sin `env`. No necesita keys.)

---

## Testing offline

Como este MCP no tiene red ni MT5, puedes testearlo con CSVs:

```python
# tests/test_score_real_setup.py
import pandas as pd
from lib.scorer import score

def test_eurusd_uptrend_pullback_setup():
    df = pd.read_csv("fixtures/eurusd_m15_trending.csv")
    ohlcv = df.to_dict("records")
    result = score(
        ohlcv=ohlcv,
        side="buy",
        entry=1.0850,
        sl=1.0830,
        tp=1.0890,
    )
    assert result["score"] >= 70
    assert result["recommendation"] == "TAKE"
```

CSVs los puedes exportar desde MT5 con `File → Export Data` o desde el `trading-mcp` con `get_rates`.

---

## Patrones de uso desde Claude

```
Tú: "Analiza EURUSD M15 y dime si vale entrar long en 1.0850"

Claude:
  1. trading.get_rates("EURUSD", "M15", 200) → [...]
  2. trading.get_rates("EURUSD", "H4", 100)  → [...]
  3. analysis.indicators(m15)                → RSI 58, ATR 0.00045
  4. analysis.mtf_bias(h4, m15)              → aligned=true, side=buy
  5. analysis.support_resistance(m15)        → soporte 1.0830 (3 touches)
  6. analysis.candlestick_patterns(m15)      → bullish engulfing
  7. analysis.score_setup(m15, "buy", 1.0850, 1.0830, 1.0890)
     → score 78, recommendation TAKE

Claude responde:
  "Setup A+ (score 78). Trend, MTF, S/R y patrón alineados.
   R:R 2.0. Si quieres entrar, el lotaje correcto sería..."
```

---

## Hyperparámetros tunables

En `lib/scorer.py`:

```python
WEIGHTS = {
    "trend_aligned": 25,
    "mtf_aligned": 20,
    "in_sr_zone": 15,
    "candle_pattern": 10,
    "rsi_healthy": 10,
    "rr_premium": 10,
    "atr_active": 10,
}
TAKE_THRESHOLD = 70
WAIT_THRESHOLD = 60
RR_PREMIUM = 2.5
SR_MAX_DISTANCE_ATR = 0.3
```

**No los cambies caprichosamente.** Si quieres ajustar, primero corre backtests con CSVs históricos y compara expectancy. Si no puedes medir el cambio, no lo hagas.

---

## Edge cases / troubleshooting

| Problema | Causa | Fix |
|---|---|---|
| Score siempre 0 | OHLCV mal ordenado (descendiente) | Ordena ascendente por `time` |
| `pandas-ta` falla en M1 | datasets cortos | Asegura ≥ 200 velas para EMA200 |
| MTF dice aligned pero precio cae | M15 puede invertirse antes que H4 | Es expected, MTF no es predicción |
| Patrones nunca detectados | tolerance demasiado estricta | Revisa `body_to_range_ratio` thresholds |

---

## Checklist de validación

- [ ] Tests con 3 fixtures (trending, range, breakout) pasan
- [ ] `score_setup` devuelve TAKE en setups conocidos buenos
- [ ] `score_setup` devuelve SKIP en setups counter-trend
- [ ] Sin dependencias de red en runtime
- [ ] Tipos compatibles con MCP protocol (dict, list, primitives)
