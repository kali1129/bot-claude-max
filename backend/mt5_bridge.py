"""Read-only bridge to MetaTrader5 for the dashboard control panel.

The trading-mt5-mcp owns ``place_order`` and the kill-switch logic; this
module only surfaces account / positions / recent deals so the UI can show
a live snapshot without going through the MCP stdio protocol. Writes
remain in the MCP.

Credentials come from the MCP's ``.env`` (single source of truth) so the
backend, the MCP, and the sync loop all log in to the same account.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import dotenv_values

log = logging.getLogger("mt5-bridge")

_HERE = Path(__file__).resolve().parent
_MCP_ROOT = _HERE.parent / "mcp-scaffolds" / "trading-mt5-mcp"
_MCP_PYTHON = _MCP_ROOT / ".venv" / "Scripts" / "python.exe"
_MCP_ENV    = _MCP_ROOT / ".env"
_HALT_FILE = Path(os.path.expanduser(os.environ.get("HALT_FILE", "~/mcp/.HALT")))


def _mcp_env() -> dict:
    """Read the MCP's .env (without polluting os.environ)."""
    if _MCP_ENV.exists():
        return {k: v for k, v in dotenv_values(_MCP_ENV).items() if v is not None}
    return {}


# --------------------------- MetaTrader5 (lazy import) ---------------------------

_mt5 = None
_init_ok = False
_init_login = None  # which login the current session is authenticated as


def _mt5_import():
    global _mt5
    if _mt5 is None:
        try:
            import MetaTrader5 as mt5  # type: ignore
            _mt5 = mt5
        except ImportError:
            _mt5 = False
    return _mt5 if _mt5 else None


def _opt_int(val):
    if val is None or val == "":
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _ensure() -> bool:
    """Initialise the MT5 connection.

    Strategy (in order):
      1. Attach passively to whatever terminal the operator already has open.
         This is the most robust path — it never cares about server name
         spelling or password format.
      2. If no terminal is open, fall back to launching one with the
         credentials in the MCP's .env (login/password/server).

    The dashboard reflects whatever account the active terminal is logged
    into, so the user can switch accounts in MT5 without restarting anything.
    """
    global _init_ok, _init_login
    mt5 = _mt5_import()
    if mt5 is None:
        return False

    cfg = _mcp_env()
    target_login    = _opt_int(cfg.get("MT5_LOGIN") or os.environ.get("MT5_LOGIN"))
    target_password = cfg.get("MT5_PASSWORD") or os.environ.get("MT5_PASSWORD") or None
    target_server   = cfg.get("MT5_SERVER")   or os.environ.get("MT5_SERVER")   or None
    target_path     = cfg.get("MT5_PATH")     or os.environ.get("MT5_PATH")     or None

    if _init_ok:
        # Already connected; if the operator switched accounts in the MT5
        # GUI we'll see it via account_info() without re-init.
        info = mt5.account_info()
        if info is not None:
            _init_login = info.login
            return True
        # Stale handle, drop it and re-init.
        try:
            mt5.shutdown()
        except Exception:  # noqa: BLE001
            pass
        _init_ok = False

    # Attempt 1: passive attach (no credentials).
    passive_kwargs = {"path": target_path} if target_path else {}
    if mt5.initialize(**passive_kwargs):
        info = mt5.account_info()
        if info is not None:
            _init_ok = True
            _init_login = info.login
            return True
        try:
            mt5.shutdown()
        except Exception:  # noqa: BLE001
            pass

    # Attempt 2: login explicitly with .env credentials.
    if target_login is not None and target_password and target_server:
        creds_kwargs = dict(passive_kwargs)
        creds_kwargs.update({"login": target_login,
                             "password": target_password,
                             "server": target_server})
        if mt5.initialize(**creds_kwargs):
            info = mt5.account_info()
            _init_ok = True
            _init_login = info.login if info else target_login
            return True
        log.warning("mt5.initialize with creds failed: %s", mt5.last_error())

    log.info("mt5 not reachable — dashboard will show fallback values")
    return False


# --------------------------- public API ---------------------------

def status() -> dict:
    """Snapshot of the connected MT5 account + open positions."""
    mt5 = _mt5_import()
    if mt5 is None:
        return {"connected": False, "reason": "MetaTrader5 lib not installed in backend venv"}
    if not _ensure():
        err = mt5.last_error() if mt5 else "unknown"
        return {"connected": False, "reason": f"MT5 init failed: {err}"}

    info = mt5.account_info()
    term = mt5.terminal_info()
    if info is None:
        return {"connected": False, "reason": "account_info returned None — terminal logged out?"}

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    deals = mt5.history_deals_get(today_start, datetime.now(timezone.utc)) or []
    realised_today = sum(
        float(d.profit or 0.0)
        for d in deals
        if d.entry == mt5.DEAL_ENTRY_OUT
    )
    unrealised = float(info.profit or 0.0)
    daily_pl = realised_today + unrealised
    daily_pl_pct = (daily_pl / info.balance * 100.0) if info.balance else 0.0

    positions = mt5.positions_get() or []
    pos_list = []
    for p in positions:
        pos_list.append({
            "ticket": int(p.ticket),
            "symbol": p.symbol,
            "side": "buy" if p.type == 0 else "sell",
            "lots": float(p.volume),
            "entry": float(p.price_open),
            "current": float(p.price_current),
            "sl": float(p.sl),
            "tp": float(p.tp),
            "profit_usd": float(p.profit),
            "open_time_utc": datetime.fromtimestamp(p.time, tz=timezone.utc).isoformat(),
        })

    return {
        "connected": True,
        "account": {
            "login": info.login,
            "name": info.name,
            "server": info.server,
            "currency": info.currency,
            "balance": float(info.balance),
            "equity": float(info.equity),
            "margin": float(info.margin),
            "margin_free": float(info.margin_free),
            "margin_level": float(info.margin_level) if info.margin else None,
            "leverage": info.leverage,
            "trade_allowed": bool(info.trade_allowed),
        },
        "today": {
            "realised_pl_usd": round(realised_today, 2),
            "unrealised_pl_usd": round(unrealised, 2),
            "total_pl_usd": round(daily_pl, 2),
            "total_pl_pct": round(daily_pl_pct, 3),
        },
        "open_positions": pos_list,
        "terminal": {
            "company": term.company if term else None,
            "build": term.build if term else None,
            "path": term.path if term else None,
        },
    }


def trigger_sync(lookback_days: int = 7) -> dict:
    """Call the MCP's sync_to_dashboard from a one-shot subprocess.

    Keeps the MCP venv (which has its own MetaTrader5 + requests pin)
    isolated from the backend venv. Returns the JSON the MCP printed.
    """
    if not _MCP_PYTHON.exists():
        return {"ok": False, "reason": "MCP venv not found",
                "detail": f"expected at {_MCP_PYTHON}"}

    snippet = (
        "import sys; from pathlib import Path; "
        f"ROOT = Path(r'{_MCP_ROOT}'); "
        "sys.path.insert(0, str(ROOT)); "
        "sys.path.insert(0, str(ROOT.parent / '_shared')); "
        "from dotenv import load_dotenv; load_dotenv(ROOT / '.env'); "
        "import server, json; "
        f"print(json.dumps(server.sync_to_dashboard({int(lookback_days)})))"
    )
    try:
        proc = subprocess.run(
            [str(_MCP_PYTHON), "-c", snippet],
            capture_output=True, text=True, timeout=180,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "TIMEOUT", "detail": "sync took >180s"}

    if proc.returncode != 0:
        return {"ok": False, "reason": "MCP_ERROR",
                "detail": (proc.stderr or proc.stdout)[-600:]}
    try:
        result = json.loads(proc.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return {"ok": False, "reason": "BAD_OUTPUT", "detail": proc.stdout[-300:]}

    return {
        "ok": True,
        "pushed": result.get("pushed", []),
        "failed": result.get("failed", []),
        "skipped": result.get("skipped", 0),
        "dedupe_window_days": result.get("dedupe_window_days"),
        # Legacy field kept for older dashboard frontends. The new sync.py
        # uses pushed_tickets[] dedupe instead of a watermark.
        "last_seen_ticket": None,
    }


def halt_status() -> dict:
    if not _HALT_FILE.exists():
        return {"halted": False}
    try:
        body = _HALT_FILE.read_text(encoding="utf-8").strip()
    except OSError as e:
        return {"halted": True, "reason": f"halt file unreadable: {e}"}
    # File may be JSON ({halted_at, reason}) or plain text — surface only the reason.
    parsed_reason = body or "no reason recorded"
    halted_at = None
    try:
        parsed = json.loads(body) if body else {}
        if isinstance(parsed, dict):
            parsed_reason = parsed.get("reason") or parsed_reason
            halted_at = parsed.get("halted_at")
    except json.JSONDecodeError:
        pass
    out = {"halted": True, "reason": parsed_reason, "path": str(_HALT_FILE)}
    if halted_at:
        out["halted_at"] = halted_at
    return out


def halt_set(reason: str) -> dict:
    _HALT_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    payload = {"halted_at": timestamp, "reason": reason or "no reason"}
    _HALT_FILE.write_text(json.dumps(payload), encoding="utf-8")
    log.warning("kill-switch armed reason=%r path=%s", reason, _HALT_FILE)
    return {"halted": True, **payload, "path": str(_HALT_FILE)}


def halt_clear() -> dict:
    if _HALT_FILE.exists():
        _HALT_FILE.unlink()
        log.warning("kill-switch released path=%s", _HALT_FILE)
    return {"halted": False}
