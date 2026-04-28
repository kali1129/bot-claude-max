"""Emit a claude_desktop_config.json that points at all 4 MCPs in this repo.

Run:
    python mcp-scaffolds/generate_claude_desktop_config.py

It writes the JSON to stdout and to %APPDATA%\\Claude\\claude_desktop_config.json
(or ~/.config/Claude/ on Linux/Mac) when --install is passed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MCPS = [
    ("trading", "trading-mt5-mcp"),
    ("risk",    "risk-mcp"),
    ("analysis","analysis-mcp"),
    ("news",    "news-mcp"),
]


def _venv_python(mcp_dir: Path) -> str:
    if sys.platform == "win32":
        p = mcp_dir / ".venv" / "Scripts" / "python.exe"
    else:
        p = mcp_dir / ".venv" / "bin" / "python"
    return str(p)


def _server_path(mcp_dir: Path) -> str:
    return str(mcp_dir / "server.py")


def _claude_config_path() -> Path:
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise RuntimeError("APPDATA env var missing on Windows")
        return Path(appdata) / "Claude" / "claude_desktop_config.json"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def build_config() -> dict:
    servers = {}
    for name, folder in MCPS:
        d = ROOT / folder
        if not d.exists():
            continue
        env_file = d / ".env"
        env_block = {}
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k, v = k.strip(), v.strip()
                if v and v not in {"", "<your-key>"}:
                    env_block[k] = v
        servers[name] = {
            "command": _venv_python(d),
            "args": [_server_path(d)],
            "env": env_block,
        }
    return {"mcpServers": servers}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--install", action="store_true",
                    help="Write config to Claude Desktop's app dir (overwrites).")
    ap.add_argument("--out", help="Optional path to write the JSON to.")
    args = ap.parse_args()

    cfg = build_config()
    payload = json.dumps(cfg, indent=2)
    print(payload)

    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
        print(f"\n# wrote to {args.out}", file=sys.stderr)
    if args.install:
        target = _claude_config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            backup = target.with_suffix(".bak.json")
            target.rename(backup)
            print(f"# previous config backed up to {backup}", file=sys.stderr)
        target.write_text(payload, encoding="utf-8")
        print(f"# installed to {target}", file=sys.stderr)
        print("# restart Claude Desktop for it to pick up the changes.", file=sys.stderr)


if __name__ == "__main__":
    main()
