"""Capital ledger — fuente de verdad sobre cuánto capital tiene la cuenta.

Reemplaza el patrón anterior de "balance hardcodeado $800" porque mezclaba
3 conceptos distintos:

  - **target_capital**: la meta del plan (siempre $800 en este proyecto). Nunca cambia.
  - **starting_balance**: el balance al inicio de la sesión actual de trading.
    Cambia cuando el usuario hace `/reset_balance` (recargó cuenta demo, reset).
  - **current_balance**: el balance live de MT5 (lo que importa para sizing).
  - **peak_equity**: el equity máximo alcanzado (para drawdown all-time).

Además registra eventos explícitos de **deposit** y **withdrawal** para que
el bot no confunda "el balance subió de $200 a $1000" (un depósito) con
"hicimos $800 en una hora" (sería sospechoso).

Persistencia: ``state/capital_ledger.json``. Atomic write tmp+rename.
Cualquier MCP/proceso lo lee — uso seguro desde múltiples procesos.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LEDGER_FILE = Path(os.path.expanduser(
    os.environ.get("CAPITAL_LEDGER_FILE",
                   "/opt/trading-bot/state/capital_ledger.json")
))

_DEFAULT_TARGET = float(os.environ.get("TARGET_CAPITAL_USD", "800"))
_TOLERANCE_PCT = 0.5  # diff % entre balance y expected → marcar evento sospechoso

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    os.replace(tmp, path)


def _empty_ledger(target: float = _DEFAULT_TARGET) -> dict:
    """Estructura inicial del ledger."""
    return {
        "schema_version": 1,
        "target_capital_usd": float(target),
        "starting_balance_usd": None,        # se setea al primer load_or_init con balance
        "starting_at": None,
        "peak_equity_usd": None,
        "peak_equity_at": None,
        "current_balance_usd": None,
        "current_balance_at": None,
        "events": [],   # [{type: deposit|withdrawal|reset|trade_close, amount, balance_after, ts, note}]
    }


def load() -> dict:
    """Lee el ledger desde disco. Si no existe, retorna estructura vacía."""
    with _lock:
        if not _LEDGER_FILE.exists():
            return _empty_ledger()
        try:
            return json.loads(_LEDGER_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty_ledger()


def save(ledger: dict) -> None:
    with _lock:
        _atomic_write(_LEDGER_FILE, ledger)


def init_if_empty(current_balance: float, target: float | None = None) -> dict:
    """Inicializa el ledger con el balance actual si está vacío.
    Llamado típicamente al primer arranque del bot o tras un reset."""
    ledger = load()
    target_v = float(target) if target is not None else _DEFAULT_TARGET
    if ledger.get("starting_balance_usd") is None:
        ts = _now_iso()
        ledger.update({
            "target_capital_usd": target_v,
            "starting_balance_usd": float(current_balance),
            "starting_at": ts,
            "peak_equity_usd": float(current_balance),
            "peak_equity_at": ts,
            "current_balance_usd": float(current_balance),
            "current_balance_at": ts,
        })
        ledger["events"].append({
            "type": "init",
            "amount": float(current_balance),
            "balance_after": float(current_balance),
            "ts": ts,
            "note": "ledger initialized",
        })
        save(ledger)
    return ledger


def update_balance(current_balance: float, equity: float | None = None) -> dict:
    """Actualiza ``current_balance`` y ``peak_equity`` (si aplica).

    NO infiere deposits/withdrawals automáticamente — el usuario debe
    declararlos via ``record_deposit`` / ``record_withdrawal`` para evitar
    falsos positivos por trades pendientes / swap fees / commission.
    """
    ledger = load()
    if ledger.get("starting_balance_usd") is None:
        return init_if_empty(current_balance)

    ts = _now_iso()
    ledger["current_balance_usd"] = float(current_balance)
    ledger["current_balance_at"] = ts

    eq = float(equity) if equity is not None else float(current_balance)
    if ledger.get("peak_equity_usd") is None or eq > ledger["peak_equity_usd"]:
        ledger["peak_equity_usd"] = eq
        ledger["peak_equity_at"] = ts

    save(ledger)
    return ledger


def reset(new_starting_balance: float, note: str = "") -> dict:
    """Reset session — el usuario recargó la cuenta demo o quiere empezar
    a medir desde cero. Mantiene ``target_capital`` y el histórico de
    ``events`` (no se borra historial, solo se agrega un evento RESET y se
    actualiza ``starting_balance``)."""
    ledger = load()
    if ledger.get("starting_balance_usd") is None:
        return init_if_empty(new_starting_balance)

    ts = _now_iso()
    ledger["events"].append({
        "type": "reset",
        "amount": float(new_starting_balance),
        "balance_after": float(new_starting_balance),
        "ts": ts,
        "note": note or "user-triggered reset",
    })
    ledger["starting_balance_usd"] = float(new_starting_balance)
    ledger["starting_at"] = ts
    ledger["current_balance_usd"] = float(new_starting_balance)
    ledger["current_balance_at"] = ts
    # Peak se actualiza si el reset SUBE el balance (ej. recarga demo);
    # si BAJA (withdrawal previo no registrado), conservamos peak histórico.
    if (ledger.get("peak_equity_usd") or 0) < new_starting_balance:
        ledger["peak_equity_usd"] = float(new_starting_balance)
        ledger["peak_equity_at"] = ts
    save(ledger)
    return ledger


def record_deposit(amount: float, balance_after: float, note: str = "") -> dict:
    """Registrar un depósito explícito. ``amount`` debe ser POSITIVO."""
    if amount <= 0:
        raise ValueError("deposit amount must be positive")
    ledger = load()
    ts = _now_iso()
    ledger["events"].append({
        "type": "deposit",
        "amount": float(amount),
        "balance_after": float(balance_after),
        "ts": ts,
        "note": note,
    })
    # Un depósito agranda el "starting" para que el DD% se mida desde el nuevo nivel.
    ledger["starting_balance_usd"] = float(balance_after)
    ledger["starting_at"] = ts
    ledger["current_balance_usd"] = float(balance_after)
    ledger["current_balance_at"] = ts
    if (ledger.get("peak_equity_usd") or 0) < balance_after:
        ledger["peak_equity_usd"] = float(balance_after)
        ledger["peak_equity_at"] = ts
    save(ledger)
    return ledger


def record_withdrawal(amount: float, balance_after: float, note: str = "") -> dict:
    """Registrar un retiro. ``amount`` debe ser POSITIVO (la cantidad retirada)."""
    if amount <= 0:
        raise ValueError("withdrawal amount must be positive")
    ledger = load()
    ts = _now_iso()
    ledger["events"].append({
        "type": "withdrawal",
        "amount": float(amount),
        "balance_after": float(balance_after),
        "ts": ts,
        "note": note,
    })
    # Un retiro NO debe contar como pérdida — bajamos el starting al nivel actual.
    ledger["starting_balance_usd"] = float(balance_after)
    ledger["starting_at"] = ts
    ledger["current_balance_usd"] = float(balance_after)
    ledger["current_balance_at"] = ts
    save(ledger)
    return ledger


def metrics(current_balance: float | None = None,
            current_equity: float | None = None) -> dict:
    """Snapshot de métricas para dashboard / Telegram / logs.

    Si ``current_balance`` se pasa, se usa como override (típicamente del
    live MT5 read). Si no, usa el último valor en el ledger."""
    ledger = load()
    starting = ledger.get("starting_balance_usd")
    if starting is None and current_balance is not None:
        ledger = init_if_empty(current_balance)
        starting = ledger["starting_balance_usd"]

    cur = float(current_balance) if current_balance is not None \
        else (ledger.get("current_balance_usd") or starting or 0.0)
    eq = float(current_equity) if current_equity is not None else cur

    target = ledger.get("target_capital_usd") or _DEFAULT_TARGET
    peak = ledger.get("peak_equity_usd") or starting or cur

    pl_session = (cur - starting) if starting else 0.0
    pl_session_pct = (pl_session / starting * 100) if starting else 0.0
    pl_target_remaining = (target - cur) if target else 0.0
    dd_from_peak = (peak - eq) if peak and eq else 0.0
    dd_from_peak_pct = (dd_from_peak / peak * 100) if peak else 0.0

    return {
        "target_capital_usd":   round(float(target), 2),
        "starting_balance_usd": round(float(starting or 0.0), 2),
        "starting_at":          ledger.get("starting_at"),
        "current_balance_usd":  round(float(cur), 2),
        "current_equity_usd":   round(float(eq), 2),
        "peak_equity_usd":      round(float(peak), 2),
        "peak_equity_at":       ledger.get("peak_equity_at"),
        "pl_session_usd":       round(pl_session, 2),
        "pl_session_pct":       round(pl_session_pct, 3),
        "pl_target_remaining_usd": round(pl_target_remaining, 2),
        "dd_from_peak_usd":     round(dd_from_peak, 2),
        "dd_from_peak_pct":     round(dd_from_peak_pct, 3),
        "events_count":         len(ledger.get("events", [])),
        "last_event":           (ledger.get("events") or [None])[-1],
    }


def is_drift_suspicious(observed_balance: float) -> dict | None:
    """Heurística: si el balance live difiere mucho del último registrado,
    podría ser un deposit/withdrawal sin declarar. Retorna info para alertar
    al usuario via Telegram."""
    ledger = load()
    last = ledger.get("current_balance_usd")
    if last is None or last <= 0:
        return None
    diff = observed_balance - last
    diff_pct = (diff / last) * 100 if last else 0
    if abs(diff_pct) < _TOLERANCE_PCT:
        return None
    # Diferencia > 0.5%: posible evento no registrado. Retorna info.
    return {
        "last_recorded": last,
        "observed": observed_balance,
        "diff_usd": round(diff, 2),
        "diff_pct": round(diff_pct, 2),
        "direction": "deposit" if diff > 0 else "withdrawal",
        "hint": (
            f"El balance subió {diff:+.2f} USD ({diff_pct:+.1f}%) sin que "
            f"el bot abriera/cerrara trades. Si fue un depósito, "
            f"declara `/deposit {abs(diff):.2f}`. Si fue ajuste interno "
            f"del broker, ignora este aviso."
            if diff > 0 else
            f"El balance bajó {diff:+.2f} USD ({diff_pct:+.1f}%) sin "
            f"P&L de trades reciente. Si fue un retiro, declara "
            f"`/withdrawal {abs(diff):.2f}`."
        ),
    }
