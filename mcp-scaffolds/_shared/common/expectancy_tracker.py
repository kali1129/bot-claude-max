"""Walk-forward expectancy tracker — la "memoria" del bot sobre qué combinaciones
(strategy × symbol × hour) producen edge real.

Cada trade cerrado se registra y agrupa por combo. Se mantienen estadísticas
rolling sobre los últimos N trades por combo: WR, avg_R, expectancy.

Uso desde auto_trader y guards:

  - ``register_close(strategy_id, symbol, r_multiple, ...)`` después de cerrar.
  - ``edge_status(strategy_id, symbol)`` antes de abrir → retorna
    {"verdict": "PROVEN" | "UNCERTAIN" | "NEGATIVE", "n": ..., "expectancy": ...}.
  - Guard puede saltear trades sobre combos NEGATIVE con n suficiente.

Persistencia: ``state/expectancy_tracker.json``. Atomic write.
"""
from __future__ import annotations

import json
import os
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_FILE = Path(os.path.expanduser(
    os.environ.get("EXPECTANCY_FILE",
                   "/opt/trading-bot/state/expectancy_tracker.json")
))

# Tamaño de la ventana rolling por combo
_WINDOW = int(os.environ.get("EXPECTANCY_WINDOW", "50"))

# Mínimo de trades antes de declarar verdict
_MIN_N_FOR_VERDICT = int(os.environ.get("EXPECTANCY_MIN_N", "15"))

# Threshold de expectancy para verdict
_EXPECTANCY_PROVEN = float(os.environ.get("EXPECTANCY_PROVEN_R", "0.10"))
_EXPECTANCY_NEGATIVE = float(os.environ.get("EXPECTANCY_NEGATIVE_R", "-0.05"))

_lock = threading.Lock()


def _key(strategy_id: str, symbol: str) -> str:
    return f"{strategy_id}:{symbol}"


def _key_hour(strategy_id: str, symbol: str, utc_hour: int) -> str:
    return f"{strategy_id}:{symbol}:{utc_hour:02d}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict:
    if not _FILE.exists():
        return {"schema_version": 1, "combos": {}, "hour_combos": {}}
    try:
        return json.loads(_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "combos": {}, "hour_combos": {}}


def _save(data: dict) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
    os.replace(tmp, _FILE)


def _summarize(r_list: list) -> dict:
    """De una lista de R-multiples, calcula stats."""
    n = len(r_list)
    if n == 0:
        return {"n": 0, "wr": 0.0, "avg_r": 0.0, "avg_win_r": 0.0,
                "avg_loss_r": 0.0, "expectancy_r": 0.0, "profit_factor": 0.0,
                "sum_r": 0.0}
    wins = [r for r in r_list if r > 0]
    losses = [r for r in r_list if r < 0]
    n_wins = len(wins)
    n_losses = len(losses)
    sum_r = sum(r_list)
    sum_win = sum(wins)
    sum_loss = sum(abs(r) for r in losses)
    wr = n_wins / n
    avg_win_r = (sum_win / n_wins) if n_wins else 0.0
    avg_loss_r = -(sum_loss / n_losses) if n_losses else 0.0
    expectancy = wr * avg_win_r + (1 - wr) * avg_loss_r
    profit_factor = (sum_win / sum_loss) if sum_loss > 0 else \
        (float("inf") if sum_win > 0 else 0.0)
    return {
        "n": n,
        "wr": round(wr, 4),
        "avg_r": round(sum_r / n, 4),
        "avg_win_r": round(avg_win_r, 4),
        "avg_loss_r": round(avg_loss_r, 4),
        "expectancy_r": round(expectancy, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else None,
        "sum_r": round(sum_r, 4),
    }


def register_close(*, strategy_id: str, symbol: str, r_multiple: float,
                    pnl_usd: float = 0.0, utc_hour: int | None = None,
                    extra: dict | None = None) -> dict:
    """Registra un trade cerrado en la memoria de expectancy."""
    with _lock:
        data = _load()
        ts = _now_iso()
        if utc_hour is None:
            utc_hour = datetime.now(timezone.utc).hour

        # Combo (strategy:symbol)
        combos = data.setdefault("combos", {})
        k = _key(strategy_id, symbol)
        combo = combos.setdefault(k, {"r_history": [], "trades": []})
        combo["r_history"].append(float(r_multiple))
        combo["r_history"] = combo["r_history"][-_WINDOW:]
        combo["trades"].append({
            "ts": ts, "r": float(r_multiple),
            "pnl_usd": round(float(pnl_usd), 2),
            "utc_hour": int(utc_hour),
            **(extra or {}),
        })
        combo["trades"] = combo["trades"][-_WINDOW:]
        combo["last_updated"] = ts
        combo["stats"] = _summarize(combo["r_history"])

        # Hour combo (strategy:symbol:hour) — opcional, para heatmap
        hour_combos = data.setdefault("hour_combos", {})
        kh = _key_hour(strategy_id, symbol, utc_hour)
        hcombo = hour_combos.setdefault(kh, {"r_history": []})
        hcombo["r_history"].append(float(r_multiple))
        hcombo["r_history"] = hcombo["r_history"][-_WINDOW:]
        hcombo["last_updated"] = ts
        hcombo["stats"] = _summarize(hcombo["r_history"])

        _save(data)
        return combo["stats"]


def edge_status(strategy_id: str, symbol: str) -> dict:
    """Verdict sobre si la combinación tiene edge probado.

    Retorna:
      - {"verdict": "PROVEN", ...} → expectancy > THRESHOLD_PROVEN con n suficiente
      - {"verdict": "NEGATIVE", ...} → expectancy < THRESHOLD_NEGATIVE con n suficiente → BLOCK
      - {"verdict": "UNCERTAIN", ...} → no hay datos suficientes (default safe)
    """
    data = _load()
    combos = data.get("combos", {})
    k = _key(strategy_id, symbol)
    combo = combos.get(k)
    if combo is None:
        return {"verdict": "UNCERTAIN", "reason": "NO_HISTORY", "n": 0,
                "expectancy_r": 0.0}
    stats = combo.get("stats") or _summarize(combo.get("r_history", []))
    n = stats["n"]
    expectancy = stats["expectancy_r"]

    if n < _MIN_N_FOR_VERDICT:
        return {"verdict": "UNCERTAIN", "reason": "INSUFFICIENT_N",
                "n": n, "min_n": _MIN_N_FOR_VERDICT,
                "expectancy_r": expectancy}
    if expectancy < _EXPECTANCY_NEGATIVE:
        return {"verdict": "NEGATIVE", "reason": "NEG_EXPECTANCY",
                "n": n, "expectancy_r": expectancy,
                "wr": stats["wr"]}
    if expectancy > _EXPECTANCY_PROVEN:
        return {"verdict": "PROVEN", "n": n,
                "expectancy_r": expectancy, "wr": stats["wr"]}
    return {"verdict": "UNCERTAIN", "reason": "MID_RANGE",
            "n": n, "expectancy_r": expectancy, "wr": stats["wr"]}


def list_combos(min_n: int = 0) -> dict:
    """Lista todos los combos con sus stats — útil para dashboard / Telegram."""
    data = _load()
    out = {}
    for k, c in (data.get("combos") or {}).items():
        s = c.get("stats") or {"n": 0}
        if s.get("n", 0) >= min_n:
            out[k] = s
    # Ordenar por expectancy descendente
    return dict(sorted(out.items(), key=lambda kv: -kv[1].get("expectancy_r", 0)))


def hour_heatmap(strategy_id: str, symbol: str) -> dict:
    """Para un strategy:symbol, retorna stats por hora UTC. Útil para
    descubrir las horas malas y bloquearlas."""
    data = _load()
    out = {}
    prefix = f"{strategy_id}:{symbol}:"
    for k, h in (data.get("hour_combos") or {}).items():
        if not k.startswith(prefix):
            continue
        hour = int(k.rsplit(":", 1)[1])
        out[hour] = h.get("stats") or {"n": 0}
    return dict(sorted(out.items()))
