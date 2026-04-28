# Operations Runbook

## Purpose

This runbook describes how to start, observe, and troubleshoot the MT5/XM trading bot safely.

## Daily Operator Sequence

1. confirm the intended runtime mode
2. verify `.env` and YAML changes were reviewed
3. run startup self-check
4. review prior daily summaries and alerts
5. start the selected runtime
6. monitor health, alerts, and audit outputs
7. confirm today's daily PnL target and loss limit before leaving the session supervised
8. confirm `current_mode`, `requested_mode`, and `real_mode_locked` before any supervised start

## Pre-Start Checks

Run:

```powershell
.\scripts\run_self_check.ps1 --mode demo
.\scripts\run_self_check.ps1 --mode paper
.\scripts\run_self_check.ps1 --mode live
```

Expected checks:

- configuration validation
- runtime directories
- SQLite writability
- MT5 connectivity
- Telegram notification status
- Telegram control status
- Codex availability
- Codex auth status / auth mode / limit status
- news collector status
- failover mode
- reconciliation health
- local control health
- duplicate runtime process detection

Telegram operator notes:

- runtime notifications are governed and throttled
- `NORMAL` is the default operator mode
- only one runtime/coordinator publishes Telegram notifications at a time by default
- repeated identical failover and blocked-trade alerts are suppressed into counters
- `live` gets periodic digests in `NORMAL`; `demo` and `paper` summaries stay suppressed unless `VERBOSE` is enabled
- digest summaries replace per-cycle status spam
- Telegram command control now uses a persistent bottom keyboard
- `/start`, `/menu`, `/help`, `Menu principal`, and common greetings restore the keyboard
- the main keyboard only shows top-level sections; each section opens its own submenu
- `Back` safely exits an input flow and returns to the previous safe submenu
- main-menu buttons interrupt pending text-entry flows safely, so `Estado`, `Cuenta`, or `Symbols hoy` always win over an unfinished `Set symbols` / `Set meta USD` / `Set loss USD` prompt
- normal command replies restore the menu without posting a second fragile panel message
- the default operator view is now `SIMPLE`, with short emoji-based cards and notifications
- use `Ver detalle tecnico`, `/detalle`, or `/debug` for the full technical drill-down
- `Modo simple`, `Modo normal`, and `Modo verbose` change only the presentation layer; they do not change risk controls or notification throttling
- Telegram command suggestions use `/estado`, `/cuenta`, `/riesgo`, `/activos`, `/ultimas_operaciones`, `/codex`, plus underscore forms such as `/show_current_mode`; the runtime still accepts the older hyphen aliases manually
- Codex auth alerts are state-change only
- Telegram exposes `Show Codex status` and `Show Codex login help`
- the operator can set today's daily profit target and daily loss limit in USD from Telegram or local control
- hitting either daily threshold stops new entries automatically for the rest of the trading day
- if `daily_stop_close_only_mode=true`, the runtime may continue bounded management of already-open positions
- the stop resets automatically on the next trading day
- the bounded opportunity layer now scans a configurable market universe and picks one `primary_focus_symbol` plus a small secondary watchlist
- the bot can rotate focus when another allowed symbol becomes materially better, but only after hysteresis and cooldown checks
- the AI decision layer may recommend `ALLOW`, `BLOCK`, `REDUCE_RISK`, `REVIEW`, `SELECT_SYMBOL`, `ROTATE_SYMBOL`, `CANCEL_ENTRY`, or `HOLD_OFF`, but execution still depends on pretrade/news, risk, execution, and reconciliation authority
- the operator can switch `PAPER` and `DEMO` directly from Telegram with confirmation
- `REAL` remains visible but locked unless the configured local unlock file or env gate is present
- mode changes are auditable and persisted in the local control state directory

Codex login helpers on this workstation:

- `C:\Users\Anderson Lora\bugbounty\Codex Manual Login.cmd`
- `C:\Users\Anderson Lora\bugbounty\Codex Switch Account.cmd`
- `C:\Users\Anderson Lora\bugbounty\Codex Login Status.cmd`

They target the single global Codex home at `C:\Users\Anderson Lora\.codex` and do not create extra slots.

Codex recovery flow from Telegram:

1. Use `Codex status` to view `codex_auth_status`, `codex_limit_status`, and the latest error.
2. Use `Codex ayuda` to see the exact launcher names and absolute paths.
3. Follow the recommended launcher:
   - `Codex Manual Login.cmd` for `LOGGED_OUT`
   - `Codex Switch Account.cmd` for `AUTH_INVALID`
   - `Codex Login Status.cmd` for `RATE_LIMITED`
   - `Codex Switch Account.cmd` for `USAGE_EXHAUSTED` only if another authorized account is available
4. Wait for the next state-change alert or refresh `Codex status`.

Persistent Telegram main menu:

- `Operacion`
- `Estado y cuenta`
- `Riesgo y objetivos`
- `Mercado y activos`
- `Codex y sistema`
- `Menu principal`
- `Back`

Submenus:

- `Operacion`
  - `Iniciar bot`
  - `Pausar`
  - `Reanudar`
  - `Detener`
  - `Modo actual`
  - `Modo PAPER`
  - `Modo DEMO`
  - `REAL`
  - `Habilitar hoy`
  - `Deshabilitar hoy`
- `Estado y cuenta`
  - `Estado`
  - `Cuenta`
  - `Rendimiento`
  - `Ultimas operaciones`
- `Riesgo y objetivos`
  - `Riesgo hoy`
  - `PnL hoy`
  - `Meta actual`
  - `Loss actual`
  - `Set meta USD`
  - `Set loss USD`
  - `Stop diario`
- `Mercado y activos`
  - `Activos`
  - `Universo de mercados`
  - `Mercado elegido ahora`
  - `Ranking actual`
  - `Por que cambio`
  - `Estado contexto`
  - `Symbols hoy`
  - `Set symbols`
  - `Ventana recomendada`
- `Codex y sistema`
  - `Codex status`
  - `Tokens Codex`
  - `Codex ayuda`
  - `Estado autostart`
  - `Estado tareas`
  - `Ver detalle tecnico`
  - `Modo simple`
  - `Modo normal`
  - `Modo verbose`

State wording used across `Estado`, `Cuenta`, `Riesgo hoy`, `Stop diario`, and `Modo actual`:

- `Politica stop diaria`: whether the daily stop rules are armed for the day
- `Estado stop diario`: `DISABLED`, `ARMED`, or `TRIGGERED`
- `Stop diario disparado`: whether a target or loss stop already fired today
- `Trading habilitado hoy`: operator policy toggle for the day
- `Nuevas entradas`: whether the runtime may open new positions right now
- `Close-only tras stop`: whether the runtime is configured to manage open positions after a daily stop
- `Close-only activo`: whether the runtime is currently restricted to bounded open-position management
- `Monitoreo seguro`: whether the runtime is observation-only because active blockers still prevent new entries

Operator dashboard cards now available from Telegram and local control:

- `Cuenta`
  - broker balance
  - broker equity
  - broker free margin
  - optional strategy capital
  - current mode
  - active symbols
  - open positions count
  - trading enabled today
  - whether new entries are allowed now
  - whether close-only is active now
  - monitoring-only state
  - operational blocker
  - contextual blocker
- `Rendimiento`
  - trades closed today
  - wins
  - losses
  - win rate
  - realized PnL today
  - floating PnL when available
  - best trade
  - worst trade
  - last closed trade
- `Riesgo hoy`
  - daily target
  - daily loss limit
  - realized PnL
  - daily stop policy enabled
  - daily stop state
  - daily stop triggered
  - target reached
  - loss limit reached
  - remaining distance to target and loss limit
  - whether new entries are allowed now
  - whether close-only is active now
- `Activos`
  - allowed symbols today
  - currently monitored symbols
  - current chart symbol and timeframe
  - open-position symbols
  - current symbol eligibility
- `Universo de mercados`
  - configured market universe
  - symbols enabled today
  - active watchlist
- `Mercado elegido ahora`
  - current primary focus symbol
  - alternatives
  - why it was chosen
  - what currently limits entry
- `Ranking actual`
  - ranked symbols
  - opportunity score
  - confidence band
  - selection action
- `Por que cambio`
  - latest focus rotation reason
  - previous focus
  - current focus
- `Estado contexto`
  - news/context quality
  - execution health
  - reconciliation health
  - current bounded recommendation
- `Ultimas operaciones`
  - latest 5 closed trades where available
- `Codex status` and `Tokens Codex`
  - auth
  - limit
  - model
  - budget state
  - last error
  - launcher names and Windows paths

Operator-facing Telegram wording is now intentionally split:

- default simple view
  - short
  - visual
  - operator-first
- technical detail view
  - full codes
  - blockers
  - trace ids
  - failover detail
  - reconciliation detail

The simple default should answer quickly:

- did it trade or not
- did it win or lose
- is it blocked or allowed
- what should I do now

Codex budget visibility rules:

- exact numeric value if the local `codex login status` output exposes it reliably
- best-effort estimate if it exposes a reliable usage ratio
- otherwise explicit `UNKNOWN`

Windows autostart support is also available for supervised reboot recovery:

- Task Scheduler task `XM MT5 Bot - Telegram Control`
- Task Scheduler task `XM MT5 Bot - Runtime Autostart`
- install with `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_autostart_tasks.ps1 -Recreate`
- remove with `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\remove_autostart_tasks.ps1`
- test without reboot using `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\test_autostart.ps1`
- inspect status using `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\show_autostart_task_status.ps1`
- autostart status file: `data/control_center/autostart_status.json`
- autostart event log: `logs/control_center/autostart/autostart_events.jsonl`
- `DEMO` and `PAPER` may auto-start; `REAL` stays blocked for trading autostart and only restores the control path

Repeatable supervised-DEMO quality assessment:

- `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_quality_assessment.ps1 -Mode live`
- `.\.venv\Scripts\python.exe .\scripts\run_quality_assessment.py --mode live`
- artifacts are written under `logs\live\quality_assessments\`

Multi-market opportunity controls:

- configured universe comes from `risk.allowed_symbols`
- today's eligible symbols still come from the operator day-allowlist
- opportunity settings live under the new `opportunity` config section
- the runtime scans the allowed universe, ranks symbols, selects one focus symbol, and keeps the rest as watchlist only
- rotation requires a meaningful score advantage and cooldown, so the bot does not thrash between markets
- if no symbol clears the bounded threshold, the runtime explicitly stays in `NO_TRADE`

## Start Commands

Demo:

```powershell
.\scripts\run_demo.ps1
```

Paper:

```powershell
.\scripts\run_paper.ps1
```

Backtest:

```powershell
.\scripts\run_backtest.ps1
```

Live:

```powershell
.\scripts\run_live.ps1
```

## Files To Watch

- `logs/<mode>/audit_events.jsonl`
- `logs/<mode>/alerts.jsonl`
- `logs/<mode>/news_gate_audit.jsonl`
- `logs/<mode>/daily_summaries/`
- `logs/<mode>/dashboards/`
- `data/xm_bot.sqlite3`
- `mql5/Files/inbound/`
- `mql5/Files/outbound/`

## Supervised Demo Checklist

For the first XM demo-account session in `live` mode:

1. Run `.\scripts\run_live_validation.ps1 -OperatorSummary`.
3. Start `.\scripts\run_live.ps1`.
4. After the first processed live bar, capture a baseline:

```powershell
.\scripts\validate_restart_dedupe.ps1 -Action capture -OperatorSummary
```

5. Restart the coordinator before the next bar closes.
6. Compare the baseline:

```powershell
.\scripts\validate_restart_dedupe.ps1 -Action compare -OperatorSummary
```

7. Continue only if `restart_dedupe_check` passes.

## Log Verification

### Decision ID Continuity

Verify that the latest persisted watermark metadata, bridge decision, execution outcome, and reconciliation row all carry the same `decision_id` when an entry was actually routed.

### Duplicate Suppression

After a controlled restart on the same bar, confirm:

- `restart_dedupe_check` passes
- the watermark timestamp does not advance
- no second `execution_attempt` is recorded for the same `decision_id`

### News Blocking And Reduced Risk

Inspect:

- `logs/live/news_gate_audit.jsonl`
- `logs/live/audit_events.jsonl`

Confirm that `news_gate`, `risk_decision`, and `blocked_trade` entries show explicit reasons such as event-window blocks, reduced-risk context, or review-required behavior.

### Failover Behavior

Inspect:

- `logs/live/audit_events.jsonl`
- `logs/live/alerts.jsonl`

Confirm that a Codex or context-provider outage produces a `failover_event` and that the runtime behavior matches the active fallback mode.
Also confirm the latest bounded analysis chain is visible in local status or Telegram `/status`.

### Daily PnL Stop State

Inspect:

- Telegram buttons `PnL hoy`, `Meta actual`, `Loss actual`, `Stop diario`, `Symbols hoy`
- `logs/live/audit_events.jsonl`
- the file configured at `risk.daily_pnl_state_file`

Confirm:

- the active USD target and loss limit are the intended values for today
- `today_pnl_realized_usd` tracks realized closed-trade PnL
- `daily_trading_enabled=true` when the bot is intended to take new entries today
- `allowed_symbols_today` only contains configured bounded symbols
- `trading_stopped_for_day=true` only after the target or loss limit is reached
- the next trading day clears the stop automatically before new entries resume
- the next trading day also restores the default symbol allowlist and re-enables daily trading unless a new manual action changes it again

### Runtime Mode Control

Inspect:

- Telegram buttons `Modo actual`, `Modo PAPER`, `Modo DEMO`, `REAL`, `Activar REAL`
- local control status field `runtime_mode_control`
- `data/control_center/runtime_mode_state.json`

Confirm:

- `current_mode` matches the intended start mode
- `requested_mode` reflects the last operator request
- `REAL` shows `real_mode_locked=true` unless the local unlock condition is present
- `Activar REAL` is rejected clearly when the unlock gate is absent
- the currently running mode is stopped before switching to a different mode

### Telegram Noise Or Missing Alerts

Inspect:

- `logs/telegram_notification_state.json`
- `data/telegram_notification_publisher.json`
- `logs/live/audit_events.jsonl`

Confirm:

- `notification_mode` is the intended one
- `suppressed_notifications_count` is increasing only during repeated identical conditions
- `last_notification_reason` matches either cooldown, message-cap, or mode-based suppression
- `messages_last_hour` stays below the configured cap
- the shared publisher lease points to the intended runtime mode and PID

If the operator wants more output for a supervised session, prefer `VERBOSE` mode over shortening risk or failover controls.

### Telegram Menu Missing

Action:

1. send `/menu`
2. if needed, send `/help`
3. if the keyboard is visible but you are inside an input flow, use `Back`
4. if the keyboard is hidden manually, use `Menu principal` after restoring it with `/menu`
5. confirm you are in the private chat with the bot
6. if the runtime itself is not responding, run `powershell -ExecutionPolicy Bypass -File .\scripts\run_telegram_control_bot.ps1 -Mode live -ForceMainMenu`

Confirm:

- the next bot reply includes the persistent bottom keyboard
- sensitive actions still show inline confirm/cancel buttons
- `logs/control_center/telegram_control_bot.stderr.log` shows `telegram recognized menu restore command` and `telegram sendMessage success`

### Windows Autostart After Reboot

Action:

1. confirm the selected mode in `Modo actual`
2. keep `REAL` locked unless you intend manual supervised activation later
3. install the scheduled tasks with `.\scripts\install_autostart_tasks.ps1 -Recreate`
4. run `.\scripts\test_autostart.ps1` once before relying on reboot recovery
5. inspect `data/control_center/autostart_status.json`
6. inspect `logs/control_center/autostart/autostart_events.jsonl`

Confirm:

- Telegram control starts once
- the selected `DEMO` or `PAPER` runtime starts once
- no duplicate coordinators are created
- `REAL` produces `BLOCKED_REAL_LOCKED` instead of auto-starting trading
- `Estado` or `Modo actual` shows the latest autostart summary when available

### Reconciliation Outcomes

Inspect the reconciliation records in `data/xm_bot.sqlite3` and confirm the latest routed decision lands in an explicit state such as `confirmed`, `mismatch`, or `deferred`. Do not treat repeated deferred results as acceptable steady-state behavior.

## Incident Response

### Startup Self-Check Fails

Action:

1. read the reported error or warning
2. correct config, path, or permissions issues
3. rerun self-check before starting the loop

Interpret the local-control items like this:

1. `local_control_health` should be `PASS` for normal standalone local operation.
2. `telegram_control` only needs to be `PASS` if you actually want Telegram command control enabled.
3. `LOCAL_CONTROL_TOKEN` is only required when `config/control-center.yaml` explicitly enables `auth.required: true`.
4. A missing gateway heartbeat is only relevant when `config/control-center.yaml` explicitly enables a gateway.

### MT5 Terminal Disconnected

Action:

1. confirm MT5 is open and logged into the correct XM account
2. confirm algorithmic trading is enabled
3. confirm the EA is attached and active
4. inspect bridge output for fresh state files
5. do not restart live execution until the self-check passes

### Stale Market State Or Quotes

Action:

1. inspect `state_*.json` timestamps in `mql5/Files/outbound`
2. confirm MT5 chart symbol and timeframe match configuration
3. confirm no filesystem permission issue is blocking bridge writes
4. keep new entries blocked until freshness recovers

### Rejected Orders

Action:

1. inspect `alerts.jsonl` and `audit_events.jsonl`
2. identify the execution reason code
3. confirm terminal trade status, spread, and SL/TP geometry
4. treat repeated rejections as an incident

### News Gate Blocking

Action:

1. inspect `news_gate_audit.jsonl`
2. confirm whether an event window or conflict triggered the block
3. do not bypass the gate by editing live rules ad hoc
4. wait for the validity window to expire or review the approved source set

News source health is now classified explicitly during startup:

- no sources configured
- source file not populated yet
- healthy but empty source
- stale source
- populated healthy source

### Failover Mode Active

Action:

1. inspect `logs/llm_failover_audit.jsonl`
2. identify the failover reason code and active fallback mode
3. verify whether new entries are still permitted under policy
4. restore provider health before returning to normal operation

### Reconciliation Drift

Action:

1. inspect reconciliation records in SQLite
2. compare broker-visible positions with internal state
3. pause or block new entries if drift persists
4. preserve artifacts for incident review

### Reconciliation Stays Pending Or Deferred

Action:

1. confirm fresh `state_*.json` files continue to arrive after the decision was routed
2. inspect the latest execution result and reconciliation payload for the affected `decision_id`
3. compare broker-visible tickets and symbol volume with the pre-submit snapshot
4. if the state feed is not advancing, stop assuming fills and keep the run supervised
5. escalate if the same decision remains unresolved across multiple fresh state updates

### Codex Or News Transport Unavailable

Action:

1. inspect `failover_event` and alert entries
2. confirm whether the runtime moved into `REVIEW_REQUIRED`, `NO_NEW_TRADES`, or another configured fallback mode
3. continue only if the operator accepts the degraded mode and understands the new-entry restrictions
4. restore the unavailable transport before removing supervision

### Codex Logged Out Or Rate Limited

Action:

1. run `C:\Users\Anderson Lora\bugbounty\Codex Login Status.cmd`
2. if logged out or invalid, run `C:\Users\Anderson Lora\bugbounty\Codex Manual Login.cmd`
3. if you intentionally need to change the single global account, run `C:\Users\Anderson Lora\bugbounty\Codex Switch Account.cmd`
4. confirm `/status` shows `codex_auth_status=LOGGED_IN`
5. if Telegram reports `RATE_LIMITED` or `USAGE_EXHAUSTED`, wait for recovery or reduce reliance on Codex-backed advisory paths before removing supervision

### EA Compiles But Does Not Emit State

Action:

1. confirm the EA is attached to the intended chart and the smiley/active indicator is visible
2. confirm algorithmic trading is enabled globally and for the chart
3. inspect `mql5/Files/outbound` for fresh `state_*.json`
4. inspect `terminal_status.txt` if present
5. verify the repository bridge paths and the terminal `MQL5\Files` paths still align
6. restart MT5 after recompilation or path changes before continuing

### Kill Switch Engaged

Action:

1. confirm whether engagement was intentional
2. keep new entries blocked until the operator clears the flag
3. document the reason in the audit trail if this was a manual action

### Daily Profit Target Or Loss Limit Reached

Action:

1. verify `PnL hoy`, `Meta actual`, `Loss actual`, and `Stop diario`
2. confirm the stop reason is `DAILY_PROFIT_TARGET_REACHED` or `DAILY_LOSS_LIMIT_REACHED`
3. do not expect new entries to resume on the same trading day
4. let the next trading day reset clear the stop automatically
5. if the stop fired unexpectedly, review closed-trade audit records before changing the limits

### Trading Disabled Or Symbols Restricted For Today

Action:

1. verify `Stop diario`, `Symbols hoy`, and `/status`
2. confirm whether `daily_trading_enabled=false` or `allowed_symbols_today` excludes the runtime symbol
3. use `Habilitar hoy` only if supervised trading should resume today
4. use `Set symbols` only with configured bounded symbols
5. if the runtime should remain observation-only, leave trading disabled and keep monitoring logs running

## Shutdown Procedure

For a normal shutdown:

1. stop the Python process
2. confirm no partial bridge files remain in progress
3. preserve current logs and daily summaries

For an emergency stop:

1. engage the kill switch
2. disable the EA or MT5 algorithmic trading if needed
3. stop the Python process
4. capture logs and queue artifacts

## Change Management

Before changing live configuration:

1. make the change in YAML or `.env`
2. run self-check
3. run at least demo or paper validation if the change affects strategy, risk, news, or execution
4. record the change window and operator identity outside the runtime where required

## Escalation Triggers

Escalate for review when any of the following persist:

- repeated stale state
- repeated order rejection
- reconciliation mismatch
- failover mode remains active
- daily loss or drawdown guard trips
- audit or SQLite writes fail

## Reference Documents

- `docs/architecture.md`
- `docs/risk-policy.md`
- `docs/execution-rules.md`
- `docs/news-gate.md`
- `docs/failover-policy.md`
- `docs/deployment.md`
