# legacy/

Read-only reference material from `xm-mt5-trading-platform` (the discontinued
bot). Nothing here is executed by the bot nuevo — it lives here purely as
historical documentation and as a sanity check during migration follow-up.

## Contents

- `mql5/Experts/`
  - `XMBridgeEA.mq5` — the legacy file-bridge Expert Advisor that exchanged
    state and orders with the Python core via on-disk JSON files.
  - `XMTerminalBridge.mq5` — terminal-side helper for heartbeat/control flags.
  - The bot nuevo speaks to MT5 directly via the `MetaTrader5` Python package,
    so these EAs are NOT loaded. They're kept because the file-bridge protocol
    is documented here and may be useful if someone needs to add a write-only
    audit channel later.

- `mql5/README.md` — original setup notes for the bridge.

- `docs/`
  - `risk_engine.md`, `risk-policy.md`, `strategy-spec.md`,
    `analysis-profiles.md`, `execution-rules.md`, `news-gate.md`,
    `mt5_bridge.md`, `runbook.md`, `quality-assessment.md`
  - These are the conceptual specs the legacy implementation evolved against.
    Many ideas survive in the bot nuevo (e.g., conviction sizing, drawdown
    guard, news gate); the docs here explain the legacy reasoning. When the
    bot nuevo's docs and these disagree, the bot nuevo wins.

- `reports/`
  - `backtests/eurusd_m5/` and `paper/default/` — legacy backtest and paper
    runs. Useful for "did our metrics drift?" after re-running backtests on
    the bot nuevo against equivalent data.

- `audit/audit_events.jsonl` — small audit-event log from the legacy bot. The
  74 MB `codex_enhanced_interactions.jsonl` and the 8 GB
  `logs/{backtest,live,paper,demo}/` were intentionally excluded — they were
  pure operational data with no value for the migration.

## What did NOT come over

- `xm-mt5-trading-platform/src/integrations/` (codex_*, openclaw_*) — 13.4k
  LOC of slot-management / login plumbing for the user's own LLM tooling.
  Zero connection to trading.
- `xm-mt5-trading-platform/src/persistence/` — SQLite store. Replaced by
  Mongo + JSONL.
- `xm-mt5-trading-platform/src/analysis/agent_*` — multi-agent consensus
  scaffolding. The bot nuevo uses Claude as the single orchestrator.
- All Windows `.cmd` shortcuts and PowerShell autostart scripts. Replaced by
  `connect_account.py` and direct `uvicorn` runs.
- The 2.3 GB `data/xm_bot.sqlite3` — operational database, not migrated.

## How to read this folder

If you're trying to understand a behavior in the bot nuevo and want to see
how the legacy bot did the same thing, search for the keyword here. The
bot nuevo's modules contain comments like "Port of
xm-mt5-trading-platform/src/<x>" which point back to the original file —
the original is in the tarball under `_archive/`, not in this folder.

This folder is the user-facing archive; the tarball is the raw source.
