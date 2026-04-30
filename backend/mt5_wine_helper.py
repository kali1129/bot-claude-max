"""Helper script that runs under Wine Python to query MT5 and return JSON.

Called by mt5_bridge.py via subprocess. Accepts a single argument:
  status   - account info, positions, daily P&L
  sync N   - sync closed deals from last N days to dashboard

Outputs a single JSON line to stdout (last line). All Wine noise goes to stderr.
"""
import sys
import os
import json
from datetime import datetime, timezone

# Setup paths for Wine environment
mcp_dir = r"Z:\opt\trading-bot\app\mcp-scaffolds\trading-mt5-mcp"
shared_dir = r"Z:\opt\trading-bot\app\mcp-scaffolds\_shared"
sys.path.insert(0, mcp_dir)
sys.path.insert(0, shared_dir)
os.chdir(mcp_dir)

from dotenv import load_dotenv
load_dotenv(os.path.join(mcp_dir, ".env"))

import MetaTrader5 as mt5


def _init_mt5():
    path = os.environ.get("MT5_PATH")
    login_str = os.environ.get("MT5_LOGIN", "")
    password = os.environ.get("MT5_PASSWORD", "")
    server = os.environ.get("MT5_SERVER", "")

    kwargs = {}
    if path:
        kwargs["path"] = path
    if login_str and password and server:
        kwargs["login"] = int(login_str)
        kwargs["password"] = password
        kwargs["server"] = server

    ok = mt5.initialize(**kwargs)
    if not ok:
        return False, str(mt5.last_error())
    return True, None


def cmd_status():
    ok, err = _init_mt5()
    if not ok:
        return {"connected": False, "reason": f"MT5 init failed: {err}"}

    info = mt5.account_info()
    term = mt5.terminal_info()

    if info is None:
        mt5.shutdown()
        return {"connected": False, "reason": "account_info returned None"}

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

    result = {
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
    mt5.shutdown()
    return result


def cmd_sync(lookback_days=7):
    """Sync closed deals to dashboard backend via HTTP POST."""
    import requests

    ok, err = _init_mt5()
    if not ok:
        return {"ok": False, "reason": f"MT5 init failed: {err}"}

    dashboard_url = os.environ.get("DASHBOARD_URL", "http://127.0.0.1:8000")
    dashboard_token = os.environ.get("DASHBOARD_TOKEN", "")

    from_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    # Go back lookback_days
    from datetime import timedelta
    from_date = from_date - timedelta(days=lookback_days)
    to_date = datetime.now(timezone.utc)

    deals = mt5.history_deals_get(from_date, to_date) or []
    closed = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT and d.profit != 0]

    pushed = []
    failed = []
    skipped = 0

    headers = {}
    if dashboard_token:
        headers["Authorization"] = f"Bearer {dashboard_token}"
    headers["Content-Type"] = "application/json"

    for d in closed:
        client_id = f"mt5-deal-{d.ticket}"
        payload = {
            "client_id": client_id,
            "symbol": d.symbol,
            "direction": "long" if d.type == 0 else "short",
            "entry_price": float(d.price),
            "exit_price": float(d.price),
            "sl": 0.0,
            "tp": 0.0,
            "lots": float(d.volume),
            "pnl_usd": float(d.profit),
            "opened_at": datetime.fromtimestamp(d.time, tz=timezone.utc).isoformat(),
            "closed_at": datetime.fromtimestamp(d.time, tz=timezone.utc).isoformat(),
            "source": "mt5-sync",
        }
        try:
            resp = requests.post(
                f"{dashboard_url}/api/journal",
                json=payload,
                headers=headers,
                timeout=10,
            )
            if resp.status_code in (200, 201):
                pushed.append(client_id)
            elif resp.status_code == 409:
                skipped += 1
            else:
                failed.append({"ticket": d.ticket, "status": resp.status_code})
        except Exception as e:
            failed.append({"ticket": d.ticket, "error": str(e)})

    mt5.shutdown()
    return {
        "ok": True,
        "pushed": pushed,
        "failed": failed,
        "skipped": skipped,
        "dedupe_window_days": lookback_days,
    }


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "status"

    if command == "status":
        result = cmd_status()
    elif command == "sync":
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
        result = cmd_sync(days)
    else:
        result = {"error": f"Unknown command: {command}"}

    # Output JSON on the last line (Wine noise goes to stderr)
    print(json.dumps(result))
