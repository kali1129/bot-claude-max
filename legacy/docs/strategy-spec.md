# Strategy Specification

## Purpose

The strategy layer converts feature snapshots into deterministic directional signals. It does not size positions, set portfolio limits, or place trades.

## Strategy Contract

Each strategy returns:

- `LONG`
- `SHORT`
- `FLAT`

Each decision also includes:

- rationale codes
- `confidence_info` for logging only

The strategy output is converted into the existing signal contract before it reaches the risk engine.

## Shared Design Rules

- no look-ahead bias
- same core logic in live, paper, and backtest modes
- explicit feature requirements
- deterministic output from the same input snapshot
- return `FLAT` when required features are missing or invalid

## Feature Inputs

The baseline strategies use the shared feature pipeline. Common inputs include:

- `fast_ema`
- `slow_ema`
- `rsi`
- `atr`
- `atr_pct`
- `rolling_volatility`
- `breakout_range`
- `breakout_position`
- `spread_points`
- `spread_zscore`
- session labels
- candle structure features
- short-horizon momentum features

## Strategy Flow

1. Build a `FeatureSnapshot` from normalized bars.
2. Validate snapshot freshness and required features.
3. Apply strategy-local gating such as session or spread rules.
4. Evaluate deterministic directional logic.
5. Emit a bounded strategy decision.
6. Convert the decision to the shared signal contract for the risk engine.

## Implemented Strategies

### `deterministic_momentum`

This is the repository's current default starter strategy. It is intentionally simple and is primarily useful for smoke tests, demo mode, and integration wiring.

Responsibilities:

- provide a stable baseline signal path
- keep integration behavior predictable
- avoid reliance on external context or complex pattern logic

### `ema_rsi_trend`

Source:

- `src/strategies/ema_rsi_trend.py`

Rules:

- long bias when fast EMA is above slow EMA
- short bias when fast EMA is below slow EMA
- RSI must confirm direction
- ATR filter avoids dead markets
- spread must remain below a configured maximum
- session label must be in the allowed set

Typical rationale codes:

- `EMA_BULLISH`
- `EMA_BEARISH`
- `RSI_LONG_CONFIRMED`
- `RSI_SHORT_CONFIRMED`
- `ATR_OK`
- `SPREAD_OK`
- `SESSION_BLOCKED`

Tradeoffs:

- simple and interpretable
- less adaptive than regime-specific logic
- intentionally returns `FLAT` in ambiguous conditions

### `breakout_volatility`

Source:

- `src/strategies/breakout_volatility.py`

Rules:

- detect recent consolidation using breakout range relative to ATR
- require breakout location near the range edge
- require rolling volatility confirmation
- reject abnormal spread conditions
- require allowed session conditions
- require supporting candle-body structure and short-horizon momentum

Typical rationale codes:

- `CONSOLIDATION_READY`
- `BREAKOUT_LONG_CONFIRMED`
- `BREAKOUT_SHORT_CONFIRMED`
- `VOLATILITY_CONFIRMED`
- `SPREAD_ABNORMAL`
- `NO_CONSOLIDATION`

Tradeoffs:

- useful for regime change detection
- more sensitive to bar quality and spread anomalies
- intentionally blocks already-expanded or noisy conditions

### `ensemble`

Source:

- `src/strategies/ensemble.py`

Behavior:

- combines child strategies deterministically
- supports consensus mode and weighted voting
- returns `FLAT` on conflict
- preserves child rationale codes with strategy prefixes

Typical rationale codes:

- `ALL_STRATEGIES_FLAT`
- `ENSEMBLE_CONFLICT`
- `CONSENSUS_NOT_REACHED`
- `ENSEMBLE_LONG`
- `ENSEMBLE_SHORT`

Tradeoffs:

- useful for reducing false positives when children disagree
- more conservative than any single child strategy

## Configuration Overview

Strategy selection is configured in `config/base.yaml`:

```yaml
strategy:
  name: ema_rsi_trend
  fast_period: 8
  slow_period: 21
  min_signal_strength: 0.0
  allow_short: true
  params:
    rsi_long_min: 55
    rsi_short_max: 45
    min_atr_pct: 0.00015
    max_spread_points: 22
    allowed_sessions: [LONDON, NEW_YORK]
```

For the ensemble:

```yaml
strategy:
  name: ensemble
  fast_period: 8
  slow_period: 21
  params:
    mode: consensus
    ema_rsi_trend:
      rsi_long_min: 55
    breakout_volatility:
      max_consolidation_atr_ratio: 3.0
```

## Operational Modes

| Mode | Strategy Behavior |
| --- | --- |
| `demo` | Deterministic smoke validation using synthetic data |
| `paper` | Same strategy logic as live without broker execution |
| `backtest` | Same strategy logic on historical replay |
| `live` | Same strategy logic on MT5 state-derived features |

## Testing Expectations

Strategy tests should confirm:

- deterministic output for identical snapshots
- correct handling of missing features
- no future data dependency
- correct spread and session blocking
- expected rationale code emission

See:

- `tests/test_strategy.py`
- `tests/test_strategies_baselines.py`
- `tests/test_features.py`

## Non-Goals

- no machine learning in the baseline path
- no direct risk control in strategies
- no profit optimization claims
- no parameter brute-force search inside live logic
