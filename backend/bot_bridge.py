"""bot_bridge — backend ↔ auto_trader bridge.

Exposes everything the bot sees so the dashboard (and any HTTP client,
including Claude) can:
  - read the bot's live status, open paper trades, last scan
  - tail the audit log
  - trigger a fresh scan on demand
  - execute a manual order via the trading-mt5-mcp
  - update a few bot config values

The auto_trader writes ``last_scan.json`` after every iteration; we just
read it. For ``scan_now`` and ``execute_trade`` we shell out to a small
one-shot script in the MCP venv so the backend's venv stays slim.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("bot-bridge")

_HERE = Path(__file__).resolve().parent
_MCP_ROOT = _HERE.parent / "mcp-scaffolds" / "trading-mt5-mcp"
_MCP_PYTHON = _MCP_ROOT / ".venv" / "Scripts" / "python.exe"
_MCP_ENV    = _MCP_ROOT / ".env"

_PAPER_OPEN_FILE   = _MCP_ROOT / "paper_open.json"
_PAPER_TRADES_FILE = _MCP_ROOT / "paper_trades.jsonl"
_LAST_SCAN_FILE    = _MCP_ROOT / "last_scan.json"
_AUDIT_LOG         = Path(os.path.expanduser(
    os.environ.get("LOG_DIR", "~/mcp/logs"))) / "auto_trader.jsonl"


# --------------------------- helpers ---------------------------

def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _read_jsonl_tail(path: Path, n: int) -> list:
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    out = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _run_mcp(snippet: str, timeout: int = 30) -> dict:
    """Run a python snippet inside the trading-mt5-mcp venv. Returns the
    last printed JSON object, or ``{ok:false}`` on failure."""
    if not _MCP_PYTHON.exists():
        return {"ok": False, "reason": "MCP venv not found",
                "detail": str(_MCP_PYTHON)}
    try:
        proc = subprocess.run(
            [str(_MCP_PYTHON), "-c", snippet],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "TIMEOUT", "timeout_s": timeout}
    if proc.returncode != 0:
        return {"ok": False, "reason": "MCP_ERROR",
                "detail": (proc.stderr or proc.stdout)[-1000:]}
    output = proc.stdout.strip().splitlines()
    if not output:
        return {"ok": False, "reason": "EMPTY_OUTPUT"}
    try:
        return json.loads(output[-1])
    except json.JSONDecodeError:
        return {"ok": False, "reason": "BAD_OUTPUT", "detail": output[-1][:500]}


# --------------------------- public ---------------------------

def status() -> dict:
    """Bot health: process up?, open trades, recent activity."""
    open_trades = _read_json(_PAPER_OPEN_FILE, [])
    last_scan = _read_json(_LAST_SCAN_FILE, None)
    closed = _read_jsonl_tail(_PAPER_TRADES_FILE, 50)
    audit = _read_jsonl_tail(_AUDIT_LOG, 1)
    last_iter = audit[0] if audit else None

    # Probe: when was the most recent audit line?
    alive = False
    last_iter_ts = None
    if last_iter and "ts" in last_iter:
        try:
            last_iter_ts = last_iter["ts"]
            ts = datetime.fromisoformat(last_iter["ts"].replace("Z", "+00:00"))
            alive = (datetime.now(timezone.utc) - ts).total_seconds() < 300
        except (ValueError, TypeError):
            pass

    wins = [t for t in closed if t.get("status") == "closed-win"]
    losses = [t for t in closed if t.get("status") == "closed-loss"]
    pnl = sum(t.get("pnl_usd", 0) for t in closed)

    return {
        "alive": alive,
        "last_iter_ts": last_iter_ts,
        "open_trades": open_trades,
        "open_count": len(open_trades),
        "closed_count": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / max(len(closed), 1) * 100, 1),
        "total_pnl_usd": round(pnl, 2),
        "last_scan": last_scan,
    }


def log_tail(n: int = 50) -> dict:
    return {"events": _read_jsonl_tail(_AUDIT_LOG, n)}


def scan_now(symbols: list | None = None) -> dict:
    """Run a one-shot scan inside the MCP venv. Returns the candidate list."""
    syms = symbols or ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD", "BTCUSD"]
    syms_repr = json.dumps(syms)
    snippet = f"""
import sys, json
from pathlib import Path
ROOT = Path(r'{_MCP_ROOT}')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / '_shared'))
from dotenv import load_dotenv; load_dotenv(ROOT / '.env')
import auto_trader
best, scan = auto_trader._scan({syms_repr})
print(json.dumps({{'ok': True, 'best': best, 'candidates': scan}}, default=str))
"""
    return _run_mcp(snippet, timeout=45)


def execute_trade(symbol: str, side: str, sl: float, tp: float,
                   risk_pct: float = 1.0, lots: float | None = None,
                   client_order_id: str | None = None) -> dict:
    """Manually place an order through the MCP. Honours all guards
    (kill-switch, MAX_POSITIONS, MIN_RR, RISK_EXCEEDED…). In paper mode
    the result is logged + tracked the same as auto-trader trades."""
    payload = {
        "symbol": symbol, "side": side, "sl": float(sl), "tp": float(tp),
        "risk_pct": float(risk_pct),
        "lots": float(lots) if lots is not None else None,
        "client_order_id": client_order_id,
    }
    snippet = rf"""
import sys, json, uuid
from pathlib import Path
ROOT = Path(r'{_MCP_ROOT}')
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / '_shared'))
from dotenv import load_dotenv; load_dotenv(ROOT / '.env')
import server, auto_trader
from lib import connection
import MetaTrader5 as mt5
# Make sure MT5 is initialised before any symbol_info call. Without this,
# mt5.symbol_info() returns None for every symbol (manifests as NO_SYMBOL).
conn = connection.ensure()
if not conn.get('connected'):
    print(json.dumps({{'ok': False, 'reason': 'MT5_DISCONNECTED', 'detail': str(conn.get('error'))}})); sys.exit(0)

p = json.loads({json.dumps(json.dumps(payload))})
sym = p['symbol']; side = p['side'].lower()
sl = p['sl']; tp = p['tp']
coid = p.get('client_order_id') or f"manual-{{uuid.uuid4().hex[:10]}}"

# Compute lots if not given.
if p.get('lots'):
    lots = p['lots']
else:
    info = mt5.symbol_info(sym)
    if info is None:
        # Symbol not in Market Watch — try to add it.
        if mt5.symbol_select(sym, True):
            info = mt5.symbol_info(sym)
    if info is None:
        print(json.dumps({{'ok': False, 'reason': 'NO_SYMBOL', 'detail': f'symbol_info({{sym}}) returned None even after symbol_select'}})); sys.exit(0)
    acc = mt5.account_info()
    bal = acc.balance if acc else 0
    tick = mt5.symbol_info_tick(sym)
    entry = tick.ask if side == 'buy' else tick.bid
    sl_dist = abs(entry - sl)
    sl_ticks = sl_dist / (info.trade_tick_size or info.point or 1e-5)
    dollars_per_lot = sl_ticks * (info.trade_tick_value or 1)
    if dollars_per_lot <= 0:
        print(json.dumps({{'ok': False, 'reason': 'BAD_TICK_VALUE'}})); sys.exit(0)
    raw = bal * (p['risk_pct'] / 100.0) / dollars_per_lot
    step = info.volume_step or 0.01
    lots = round(round(raw / step) * step, 4)
    lots = max(lots, info.volume_min or 0.01)
    lots = min(lots, info.volume_max or 100, 0.5)

result = server.place_order(symbol=sym, side=side, lots=lots,
                            sl=sl, tp=tp, comment='manual', client_order_id=coid)

# If paper-mode and ok, register in paper_open.json so the auto_trader monitor
# closes it on SL/TP just like its own trades.
if result.get('ok') and result.get('mode') == 'paper':
    bal = mt5.account_info().balance if mt5.account_info() else 0
    tick = mt5.symbol_info_tick(sym)
    entry = tick.ask if side == 'buy' else tick.bid
    auto_trader._open_paper_trade(
        {{'symbol': sym, 'side': side, 'entry': entry, 'sl': sl, 'tp': tp, 'score': 'manual'}},
        lots, int(result['ticket']), bal,
    )

print(json.dumps({{'ok': True, 'lots_used': lots, 'result': result, 'coid': coid}}, default=str))
"""
    return _run_mcp(snippet, timeout=60)


def get_config() -> dict:
    """Return the bot config currently in the .env."""
    cfg = {}
    if _MCP_ENV.exists():
        for line in _MCP_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    safe = {k: v for k, v in cfg.items() if "PASSWORD" not in k.upper()}
    safe["__paths"] = {
        "mcp_root": str(_MCP_ROOT),
        "audit_log": str(_AUDIT_LOG),
        "paper_open": str(_PAPER_OPEN_FILE),
    }
    return safe


def set_config(updates: dict[str, Any]) -> dict:
    """Update specific keys in the MCP .env. Refuses to touch passwords."""
    if not _MCP_ENV.exists():
        return {"ok": False, "reason": "no .env file"}
    blocked = {k for k in updates if "PASSWORD" in k.upper()}
    if blocked:
        return {"ok": False, "reason": "PASSWORD_BLOCKED",
                "detail": f"keys forbidden: {sorted(blocked)}"}
    text = _MCP_ENV.read_text(encoding="utf-8")
    import re
    for k, v in updates.items():
        line = f"{k}={v}"
        if re.search(rf"^{re.escape(k)}=", text, re.MULTILINE):
            text = re.sub(rf"^{re.escape(k)}=.*$", line, text, flags=re.MULTILINE)
        else:
            text += f"\n{line}\n"
    _MCP_ENV.write_text(text, encoding="utf-8")
    return {"ok": True, "updated": list(updates.keys()),
            "note": "Restart auto_trader / sync_loop for changes to apply"}


# --------------------------- MT5 credentials ---------------------------

def set_mt5_credentials(login: str, password: str, server: str,
                         path: str | None = None) -> dict:
    """Update MT5_LOGIN / MT5_PASSWORD / MT5_SERVER (and optional MT5_PATH)
    in the MCP .env. The .env is gitignored — passwords never leave disk."""
    if not _MCP_ENV.exists():
        return {"ok": False, "reason": "NO_ENV_FILE"}
    if not login or not login.isdigit():
        return {"ok": False, "reason": "INVALID_LOGIN",
                "detail": "login must be numeric"}
    if not password:
        return {"ok": False, "reason": "EMPTY_PASSWORD"}
    if not server:
        return {"ok": False, "reason": "EMPTY_SERVER"}

    text = _MCP_ENV.read_text(encoding="utf-8")
    import re
    for k, v in {"MT5_LOGIN": login,
                  "MT5_PASSWORD": password,
                  "MT5_SERVER": server,
                  **({"MT5_PATH": path} if path else {})}.items():
        line = f"{k}={v}"
        if re.search(rf"^{re.escape(k)}=", text, re.MULTILINE):
            text = re.sub(rf"^{re.escape(k)}=.*$", line, text, flags=re.MULTILINE)
        else:
            text += f"\n{line}\n"
    _MCP_ENV.write_text(text, encoding="utf-8")
    return {"ok": True, "login": login, "server": server,
            "note": "Reinicia el backend y/o el bot para que la nueva cuenta tome efecto."}


def test_mt5_credentials(login: str, password: str, server: str,
                          path: str | None = None) -> dict:
    """Try to authenticate without persisting anything. Returns the account
    info on success or the MT5 error code on failure."""
    snippet = f"""
import json, sys
import MetaTrader5 as mt5
kwargs = dict(login={int(login)}, password={json.dumps(password)},
              server={json.dumps(server)})
{'kwargs["path"] = ' + json.dumps(path) if path else ''}
ok = mt5.initialize(**kwargs)
out = {{'ok': ok, 'error': mt5.last_error()}}
if ok:
    info = mt5.account_info()
    if info:
        out['account'] = {{'login': info.login, 'server': info.server,
                            'name': info.name, 'currency': info.currency,
                            'balance': float(info.balance),
                            'trade_mode': info.trade_mode,
                            'trade_allowed': bool(info.trade_allowed)}}
mt5.shutdown()
print(json.dumps(out, default=str))
"""
    return _run_mcp(snippet, timeout=20)


# --------------------------- Supervisor (Claude scheduled task) ---------------------------

def _scheduled_root() -> Path:
    """Both Claude Desktop (CCD) and Claude Code put scheduled tasks under
    %USERPROFILE%/.claude/scheduled-tasks/. We read the SKILL.md for the
    supervisor task to surface its current state."""
    return Path.home() / ".claude" / "scheduled-tasks"


def _supervisor_dir() -> Path:
    return _scheduled_root() / "trading-bot-supervisor"


def supervisor_status() -> dict:
    """Return the supervisor task's current state (frontmatter + recent runs)."""
    d = _supervisor_dir()
    skill = d / "SKILL.md"
    if not skill.exists():
        return {"installed": False,
                "detail": "trading-bot-supervisor task not found",
                "path": str(skill)}
    try:
        text = skill.read_text(encoding="utf-8")
    except OSError as exc:
        return {"installed": True, "ok": False, "detail": str(exc)}

    # Parse YAML-ish frontmatter between --- markers.
    import re
    fm = {}
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.strip().startswith("#"):
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip().strip('"').strip("'")

    # The state.json sibling holds enabled / lastRunAt / nextRunAt.
    state_file = d / "state.json"
    state = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    return {
        "installed": True,
        "task_id": "trading-bot-supervisor",
        "description": fm.get("description"),
        "cron": fm.get("cronExpression") or state.get("cronExpression"),
        "enabled": state.get("enabled", True),
        "last_run_at": state.get("lastRunAt"),
        "next_run_at": state.get("nextRunAt"),
        "path": str(d),
    }

