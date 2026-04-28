"""MT5 connection manager.

Single point of (re)connect. ``ensure()`` is idempotent — safe to call from
every tool. If ``MT5_LOGIN`` / ``MT5_PASSWORD`` / ``MT5_SERVER`` are set we
authenticate explicitly; otherwise we attach to whatever terminal is already
running (handy for local dev with the user's terminal already logged in).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import MetaTrader5 as mt5

log = logging.getLogger(__name__)

_initialised = False


def _opt_int(val: Optional[str]):
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        return None


def ensure() -> dict:
    """Initialise the MT5 connection (idempotent)."""
    global _initialised
    if _initialised:
        return {"connected": True, "cached": True}

    login = _opt_int(os.environ.get("MT5_LOGIN"))
    password = os.environ.get("MT5_PASSWORD") or None
    server = os.environ.get("MT5_SERVER") or None
    path = os.environ.get("MT5_PATH") or None

    kwargs = {}
    if path:
        kwargs["path"] = path
    if login is not None and password and server:
        kwargs.update({"login": login, "password": password, "server": server})

    ok = mt5.initialize(**kwargs)
    if not ok:
        err = mt5.last_error()
        log.error("mt5.initialize failed: %s", err)
        return {"connected": False, "error": str(err)}

    info = mt5.account_info()
    term = mt5.terminal_info()
    _initialised = True
    return {
        "connected": True,
        "account": {
            "login": info.login if info else None,
            "server": info.server if info else None,
            "name": info.name if info else None,
            "currency": info.currency if info else None,
            "leverage": info.leverage if info else None,
            "balance": info.balance if info else None,
            "trade_allowed": info.trade_allowed if info else None,
        },
        "terminal": {
            "path": term.path if term else None,
            "build": term.build if term else None,
            "company": term.company if term else None,
        },
    }


def shutdown() -> None:
    global _initialised
    if _initialised:
        mt5.shutdown()
        _initialised = False
