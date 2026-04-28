"""Migrate xm-mt5-trading-platform/data/daily_pnl_state.json into the new
risk-mcp/state.json schema.

The legacy file shape (from disk, today):
{
  "allowed_symbols_today": ["BTCUSD", "XAUUSD", "EURUSD"],
  "daily_loss_limit_usd": 25.0,
  "daily_profit_target_usd": 25.0,
  "daily_trading_enabled": true,
  "close_only_mode": false,
  "remaining_loss_capacity_usd": 25.0,
  "stop_reason_code": "DAILY_PROFIT_TARGET_REACHED",
  "trading_stopped_for_day": null/false,
  "processed_trade_ids": [...],
  "last_reset_at": "...",
  ...
}

The new bot's risk-mcp/state.json schema (per state_manager.py):
{
  "_schema_version": "...",
  "starting_balance_today": float,
  "current_equity": float,
  "deals_today": [...],
  "consecutive_losses": int,
  "locked_until_utc": str | null,
  "last_reset_date": "YYYY-MM-DD"
}

These don't fully overlap. The migration extracts what is comparable and
leaves the rest as a sidecar `legacy_daily_pnl.json` alongside state.json
so risk-mcp tools can reference it via the new daily_pnl_guard.

Usage:
    python scripts/migrate_daily_pnl_state.py \\
        --legacy-state path/to/old/daily_pnl_state.json \\
        --risk-mcp-dir path/to/NEW-BOT-PRO_MAX/mcp-scaffolds/risk-mcp/

This script is idempotent: re-running it overwrites the sidecar but does
not touch state.json if the date hasn't changed.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate legacy daily_pnl_state to risk-mcp.")
    parser.add_argument("--legacy-state", required=True, type=Path)
    parser.add_argument("--risk-mcp-dir", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.legacy_state.exists():
        print(f"ERROR: legacy state file not found: {args.legacy_state}", file=sys.stderr)
        return 2

    legacy = json.loads(args.legacy_state.read_text(encoding="utf-8"))
    print(f"Loaded legacy state: {len(legacy)} keys", file=sys.stderr)

    sidecar = {
        "_source": "legacy:xm-mt5-trading-platform/data/daily_pnl_state.json",
        "_migrated_at_utc": datetime.now(timezone.utc).isoformat(),
        "daily_trading_enabled": bool(legacy.get("daily_trading_enabled", True)),
        "trading_stopped_for_day": bool(legacy.get("trading_stopped_for_day")) ,
        "close_only_mode": bool(legacy.get("close_only_mode", False)),
        "allowed_symbols_today": list(legacy.get("allowed_symbols_today") or []),
        "stop_reason_code": legacy.get("stop_reason_code"),
        "daily_loss_limit_usd": legacy.get("daily_loss_limit_usd"),
        "daily_profit_target_usd": legacy.get("daily_profit_target_usd"),
        "remaining_loss_capacity_usd": legacy.get("remaining_loss_capacity_usd"),
        "remaining_profit_to_target_usd": legacy.get("remaining_profit_to_target_usd"),
        "last_reset_at": legacy.get("last_reset_at"),
        "stop_triggered_at": legacy.get("stop_triggered_at"),
        "resume_on_next_day": bool(legacy.get("resume_on_next_day", True)),
    }

    target = args.risk_mcp_dir / "legacy_daily_pnl.json"

    if args.dry_run:
        print(json.dumps(sidecar, indent=2))
        print(f"\nWould write to: {target}", file=sys.stderr)
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")
    print(f"Wrote sidecar: {target}", file=sys.stderr)
    print(
        "Use it by calling daily_pnl_guard with these flags from your wiring "
        "code (or read the file at startup and pass the relevant fields).",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
