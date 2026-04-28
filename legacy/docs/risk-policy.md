# Risk Policy

## Purpose

The risk layer is the final authority for approving new entries before execution. It translates a strategy signal into an explicit bounded decision or a block.

## Scope

Inputs:

- strategy signal
- normalized market bar
- account snapshot
- news gate result
- session status
- feature snapshot for stop logic where needed

Outputs:

- `ALLOW`
- `BLOCK`
- `REDUCE_RISK`

Output fields include:

- action
- symbol
- timeframe
- units
- lots
- entry price
- stop loss
- take profit
- applied risk percent
- reason codes
- audit payload

## Hard Rules

The engine enforces:

- fixed maximum risk per trade
- maximum daily loss
- maximum drawdown
- maximum open positions
- maximum symbol exposure
- per-symbol spread limits
- cooldown after losses
- maximum consecutive losses
- session restrictions
- optional reduced-risk mode
- emergency kill switch

## Evaluation Order

The current implementation evaluates rules in this order:

1. reject `HOLD` as a non-entry signal
2. check kill switch state
3. check session eligibility
4. apply news gate restrictions
5. evaluate exposure limits
6. evaluate daily loss and drawdown guard
7. resolve and validate stop-loss and take-profit levels
8. apply risk overrides such as reduced-risk mode
9. calculate position size and lots

Any failed rule returns a blocked decision immediately.

## Position Sizing

Sizing is deterministic and symbol-aware.

Inputs:

- equity
- maximum risk per trade
- entry price
- stop distance
- symbol profile
- existing symbol exposure

Symbol profile values include:

- contract size
- min lot
- max lot
- lot step
- min stop distance
- max stop distance

The engine calculates units first, then derives lots where applicable.

## Stop Policy

Protective levels are required for open actions.

Behavior:

- derive stops from configured ATR multiple when needed
- enforce minimum and maximum stop distance by symbol
- derive take-profit from configured reward-to-risk
- reject trades with invalid or non-sensical stop geometry

The risk layer defines or validates the stop plan before execution starts.

## Reduced-Risk Mode

Reduced-risk mode is optional and configuration-driven.

When active:

- risk percent is multiplied by `reduced_risk_factor`
- the disposition becomes `REDUCE_RISK`
- hard blocks still remain blocks

Reduced-risk mode does not permit trades that would otherwise violate hard limits.

## Kill Switch

The kill switch is file-backed and deterministic.

Configured by:

- `risk.kill_switch_enabled`
- `risk.kill_switch_file`

When the flag file is present and kill switch enforcement is enabled, the engine blocks fresh entries.

## Configuration Overview

Risk settings are defined in `config/base.yaml` and may be overridden per mode.

Key settings:

- `max_risk_per_trade_pct`
- `max_daily_loss_pct`
- `max_drawdown_pct`
- `max_open_positions`
- `stop_loss_pct`
- `default_stop_loss_atr_multiple`
- `reward_to_risk`
- `cooldown_after_loss_minutes`
- `max_consecutive_losses`
- `reduced_risk_mode`
- `reduced_risk_factor`
- `kill_switch_enabled`
- `kill_switch_file`
- `max_symbol_exposure_units`
- `max_spread_points_by_symbol`
- `allowed_sessions_by_symbol`
- `contract_size_by_symbol`
- `min_lot_by_symbol`
- `max_lot_by_symbol`
- `lot_step_by_symbol`
- `min_stop_distance_price_by_symbol`
- `max_stop_distance_price_by_symbol`

## Example Symbol Policy

```yaml
risk:
  max_symbol_exposure_units:
    default: 100000
    EURUSD: 100000
    XAUUSD: 500
  max_spread_points_by_symbol:
    default: 35
    EURUSD: 25
    XAUUSD: 80
  allowed_sessions_by_symbol:
    default: [LONDON, NEW_YORK]
    XAUUSD: [LONDON, NEW_YORK, US_CLOSE]
```

## Reason Code Categories

Common categories include:

- signal state: `NO_ENTRY_SIGNAL`
- session and gate: `FILTER_SESSION_BLOCKED`, `NEWS_GATE_BLOCKED`, `MANUAL_REVIEW_REQUIRED`
- kill switch: kill-switch reason codes from `kill_switch.py`
- exposure and limits: max open position or symbol exposure blocks
- drawdown and loss controls: daily loss, drawdown, cooldown, consecutive loss blocks
- stop validation: invalid stop geometry or missing stop plan
- reduced-risk annotations: non-blocking reason codes describing applied reduction
- sizing errors: invalid size, lot, or exposure fit

## Audit Trail

Every evaluation emits an auditable rule trace through the configured audit hook. Runtime outputs are also written to:

- SQLite audit storage
- `logs/<mode>/audit_events.jsonl`
- monitoring summaries and anomaly counters

## Invariants

The risk layer is designed to preserve these invariants:

- no entry without a non-flat signal
- no entry when kill switch is engaged
- no entry when daily loss or drawdown thresholds are breached
- no entry without valid protective levels
- no entry when configured spread or exposure caps are violated
- no LLM or orchestration component can override hard limits
