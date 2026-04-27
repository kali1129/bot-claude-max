# 08 — Métricas de adherencia (Discipline Score)

> El P&L te dice si estás ganando dinero. La adherencia te dice si lo estás
> ganando **por la razón correcta**. Una racha de buena suerte con disciplina
> rota se evapora; una expectancy modesta con disciplina perfecta compone.
> Este doc define la métrica que mide lo segundo.

## Objetivo

Una sola métrica entre 0 y 100 que responde: **"¿qué porcentaje de mis trades
respetaron las reglas duras?"**. Visible en la dashboard, calculada por el
backend, alimentada por el journal (que a su vez se alimenta del sync MT5).

## Definición operativa

Un trade cerrado **viola la disciplina** si cumple cualquiera de:

| Código | Regla | Detección |
|---|---|---|
| `SL_RUNAWAY` | `r_multiple < -1.05` | el SL no se respetó (slippage o hold-and-hope). El 1.05 da margen para slippage normal. |
| `OVER_RISK` | `risk_dollars / balance > 1.01%` | tomado riesgo > 1%. Calculado retroactivamente con `lots * sl_distance * pip_value`. |
| `RR_BELOW_MIN` | `tp_distance / sl_distance < 2.0` cuando `status != closed-be` | salida temprana en ganancia con R:R < 2:1. |
| `BLOCKED_HOUR_TRADE` | `created_at.hour ∈ blocked_hours` | trade colocado en horario blackout. |
| `OVERTRADING_DAY` | día con `> MAX_TRADES_PER_DAY` trades | excedió el cap diario. |

Adherencia = `(1 - violations / total_closed) * 100`.

## Endpoint backend

Ya implementado en `backend/server.py`:

```python
GET /api/discipline/score
→ {
    "adherence_pct": 96.7,
    "checked": 30,
    "violations": [
        {"id": "...", "rule": "SL_RUNAWAY", "r": -2.3},
        ...
    ]
}
```

La versión de referencia detecta solo `SL_RUNAWAY`. Cuando armes el sistema
completo, expande la función `discipline_score` para detectar las otras 4 reglas.
El esqueleto está pensado para que cada regla sea un `def detect_<rule>(trade,
context) -> Optional[Violation]` y la función principal itere todas.

```python
RULES = [
    detect_sl_runaway,
    detect_over_risk,
    detect_rr_below_min,
    detect_blocked_hour_trade,
    detect_overtrading_day,
]

def discipline_score(trades: list[dict]) -> dict:
    closed = [t for t in trades if t["status"] != "open"]
    by_day: dict[str, int] = {}
    for t in closed:
        by_day[t["date"]] = by_day.get(t["date"], 0) + 1

    violations = []
    for t in closed:
        ctx = {"day_count": by_day[t["date"]]}
        for rule in RULES:
            v = rule(t, ctx)
            if v:
                violations.append(v)

    pct = (1 - len(violations) / len(closed)) * 100 if closed else 100.0
    return {"adherence_pct": round(pct, 1), "violations": violations, "checked": len(closed)}
```

## UI en el dashboard

Card en `Overview.jsx` (top-right, junto al P&L):

```jsx
<DisciplineCard score={score} />
```

```jsx
function DisciplineCard({ score }) {
  const color = score >= 95 ? "text-emerald-400" :
                score >= 80 ? "text-amber-400" : "text-red-400";
  return (
    <div data-testid="discipline-card" className="rounded-md p-4 bg-zinc-900">
      <div className="text-xs text-zinc-400 uppercase tracking-wider">Adherence</div>
      <div className={`text-3xl font-mono ${color}`}>{score.toFixed(1)}%</div>
      <div className="text-[11px] text-zinc-500">last {checked} trades</div>
    </div>
  );
}
```

## Por qué esta métrica importa más que el P&L

- **El P&L es ruidoso**: 10 trades pueden estar en racha por suerte de mercado.
- **La adherencia es señal directa**: si bajo del 95% en 30 trades, mi disciplina
  empeoró. No tengo que adivinar.
- **Es accionable**: cada violación lleva un `id` y una `rule`. Click en la
  card → modal con la lista → click en cada uno → trade journal entry.

## Property tests

```python
import pytest

@pytest.mark.parametrize("trades,expected_pct", [
    ([], 100.0),
    ([trade(r=2.0)], 100.0),
    ([trade(r=-1.0)], 100.0),  # at limit, not violation
    ([trade(r=-1.5)], 0.0),
    ([trade(r=2.0), trade(r=-2.0)], 50.0),
])
def test_discipline_pct_invariants(trades, expected_pct):
    res = discipline_score(trades)
    assert res["adherence_pct"] == expected_pct


def test_discipline_overtrading_day():
    # 6 trades same day → all flagged once for OVERTRADING
    same_day = [trade(date="2026-01-15", r=1.0) for _ in range(6)]
    res = discipline_score(same_day)
    over = [v for v in res["violations"] if v["rule"] == "OVERTRADING_DAY"]
    assert len(over) == 6
```

## Política de uso

- Si **adherencia ≥ 95% en últimos 30 trades**: mantienes los privilegios
  actuales. Puedes operar live con 1% riesgo.
- Si **80–94%**: el `trading-mt5-mcp` debe loggear cada `place_order` con un
  warning visible, y el risk-mcp pasa el `MAX_RISK_PER_TRADE_PCT` efectivo a
  0.5% temporalmente (modo entrenamiento).
- Si **< 80%**: kill-switch automático. El usuario debe revisar el journal,
  identificar el patrón roto, y resetear manualmente con
  `DELETE /api/halt` después de un commit explicando qué hábito va a corregir.

Esta política se implementa como un poller en el dashboard backend que cada
hora calcula la adherencia y actualiza un registro `discipline_state` en
Mongo. Si baja el umbral, llama al endpoint `POST /api/halt` con
`reason: "auto: adherence dropped to X%"`.
