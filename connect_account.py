"""Connect the dashboard to your real MT5 account in one shot.

Run from the project root:
    py connect_account.py

It asks for your MT5 password (no echo), tries to authenticate, on success
writes it to mcp-scaffolds/trading-mt5-mcp/.env and pings the dashboard so
the new account shows up live. The password file is gitignored.

If the server name in .env is wrong, the script also walks a list of
common XM server names so you don't have to guess.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import sys
import time
from pathlib import Path

import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / "mcp-scaffolds" / "trading-mt5-mcp" / ".env"
DASHBOARD = os.environ.get("DASHBOARD_URL", "http://127.0.0.1:8000")


def _read_env() -> dict:
    out = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


def _write_env(updates: dict) -> None:
    """Update specific keys, preserving comments / order."""
    text = ENV_FILE.read_text(encoding="utf-8")
    for k, v in updates.items():
        if re.search(rf"^{k}=", text, re.MULTILINE):
            text = re.sub(rf"^{k}=.*$", f"{k}={v}", text, flags=re.MULTILINE)
        else:
            text += f"\n{k}={v}\n"
    ENV_FILE.write_text(text, encoding="utf-8")


def _try(login: int, password: str, server: str, path: str) -> tuple[bool, str]:
    """Attempt to authenticate; return (ok, detail)."""
    import MetaTrader5 as mt5  # noqa: WPS433  late import on purpose
    kwargs = {"login": login, "password": password, "server": server}
    if path:
        kwargs["path"] = path
    ok = mt5.initialize(**kwargs)
    if not ok:
        err = mt5.last_error()
        mt5.shutdown()
        return False, f"{err}"
    info = mt5.account_info()
    mt5.shutdown()
    if info is None:
        return False, "no account_info after login"
    return True, f"login={info.login} balance=${info.balance} {info.currency} server={info.server!r}"


def _ping_backend() -> dict:
    try:
        with urllib.request.urlopen(f"{DASHBOARD}/api/system/health", timeout=3) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError):
        return {"backend": False}


SERVER_CANDIDATES = [
    # primary (what the user said)
    "XMGlobal-MT5 11",
    "XMGlobal-MT5_11",
    "XMGlobal-MT511",
    # XMGlobal real / live variants
    "XMGlobal-Real 11", "XMGlobal-Real11",
    "XMGlobal-Live 11", "XMGlobal-Live11",
    # XMTrading variants (japanese branch)
    "XMTrading-MT5 11", "XMTrading-MT511",
    "XMTrading-Real 11",
    # demo (very unlikely if account is real)
    "XMGlobal-Demo 11", "XMGlobal-Demo",
]


def main():
    if not ENV_FILE.exists():
        print(f"ERROR: {ENV_FILE} not found.", file=sys.stderr)
        sys.exit(1)

    env = _read_env()
    login = env.get("MT5_LOGIN", "")
    server = env.get("MT5_SERVER", "")
    path = env.get("MT5_PATH", "")
    if not login.isdigit():
        print(f"ERROR: MT5_LOGIN missing in {ENV_FILE}", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting account {login} on server {server!r}")
    pwd = getpass.getpass("MT5 password (input is hidden): ").strip()
    if not pwd:
        print("aborted: password empty")
        sys.exit(1)

    # Make sure MetaTrader5 is importable from this venv.
    try:
        import MetaTrader5  # noqa: F401
    except ImportError:
        print("ERROR: MetaTrader5 lib not found. Run inside the backend venv:")
        print("  backend/.venv/Scripts/python.exe connect_account.py")
        sys.exit(1)

    print()
    # Try the configured server first, then the known XM variants.
    seen = set()
    candidates = [server, *SERVER_CANDIDATES]
    success = None
    for s in candidates:
        if not s or s in seen:
            continue
        seen.add(s)
        ok, detail = _try(int(login), pwd, s, path)
        marker = "OK " if ok else "no"
        print(f"  [{marker}] {s!r:30s}  {detail}")
        if ok:
            success = (s, detail)
            break

    if not success:
        print()
        print("All variants failed. Most likely:")
        print("  • password still wrong → recover at https://members.xm.com")
        print("  • server name format different → open MT5, log in via GUI,")
        print("    then read the server name from View → Toolbox → Journal tab")
        sys.exit(2)

    server_ok, detail = success
    _write_env({"MT5_PASSWORD": pwd, "MT5_SERVER": server_ok})
    print()
    print(f"Saved to {ENV_FILE}")
    print(f"  MT5_SERVER={server_ok}")
    print(f"  MT5_PASSWORD=*** ({len(pwd)} chars)")

    # Force the dashboard to reread MT5 by hitting /api/mt5/status. The
    # bridge re-inits on every call when previously stale.
    print()
    print("Pinging dashboard…")
    time.sleep(1)
    try:
        with urllib.request.urlopen(f"{DASHBOARD}/api/mt5/status", timeout=5) as r:
            body = json.loads(r.read())
            if body.get("connected"):
                acct = body.get("account", {})
                print(f"  Dashboard sees account {acct.get('login')} "
                      f"balance ${acct.get('balance')} {acct.get('currency')}")
            else:
                print(f"  Dashboard says: {body}")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"  Could not reach {DASHBOARD}: {e}")
        print("  Restart the backend so it picks up the new credentials.")

    print()
    print("Done. Open http://localhost:3000 — your real account is live.")


if __name__ == "__main__":
    main()
