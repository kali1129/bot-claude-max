## Strict Risk Engine

The risk layer is deterministic and can only return:

- `ALLOW`
- `BLOCK`
- `REDUCE_RISK`

Hard limits are never relaxed by LLM or orchestration layers. Reduced-risk mode can only shrink exposure.

### Rule order

1. Emergency kill switch
2. External session filter result
3. News/context gate block states
4. Spread, session, open-position, and symbol-exposure checks
5. Daily loss, total drawdown, cooldown, and consecutive-loss guards
6. Stop-loss / take-profit validation or deterministic derivation
7. Reduced-risk overrides
8. Fixed-risk position sizing

### EURUSD example

```yaml
risk:
  max_risk_per_trade_pct: 0.005
  max_daily_loss_pct: 0.02
  max_drawdown_pct: 0.08
  max_open_positions: 1
  cooldown_after_loss_minutes: 30
  max_consecutive_losses: 3
  max_symbol_exposure_units:
    EURUSD: 100000
  max_spread_points_by_symbol:
    EURUSD: 25
  allowed_sessions_by_symbol:
    EURUSD: [LONDON, NEW_YORK]
  contract_size_by_symbol:
    EURUSD: 100000
  min_lot_by_symbol:
    EURUSD: 0.01
  max_lot_by_symbol:
    EURUSD: 1.00
  lot_step_by_symbol:
    EURUSD: 0.01
```

### XAUUSD example

```yaml
risk:
  max_risk_per_trade_pct: 0.003
  max_daily_loss_pct: 0.015
  max_drawdown_pct: 0.06
  max_open_positions: 1
  cooldown_after_loss_minutes: 45
  max_consecutive_losses: 2
  max_symbol_exposure_units:
    XAUUSD: 500
  max_spread_points_by_symbol:
    XAUUSD: 80
  allowed_sessions_by_symbol:
    XAUUSD: [LONDON, NEW_YORK, US_CLOSE]
  contract_size_by_symbol:
    XAUUSD: 100
  min_lot_by_symbol:
    XAUUSD: 0.01
  max_lot_by_symbol:
    XAUUSD: 2.00
  lot_step_by_symbol:
    XAUUSD: 0.01
  min_stop_distance_price_by_symbol:
    XAUUSD: 2.0
  max_stop_distance_price_by_symbol:
    XAUUSD: 30.0
```
