# Analysis Profiles

## Purpose

Local analysis profiles provide bounded pre-trade context without creating any new execution authority.

They are designed to:

- run inside the existing Python runtime
- produce structured outputs only
- support one bounded integration path
- remain deterministic and auditable
- never place trades directly
- never override hard risk controls

Allowed outputs for every profile and chain:

- `ALLOW`
- `BLOCK`
- `REDUCE_RISK`
- `REVIEW`

## Runtime Position

The active runtime path is:

1. market data and news collection
2. bounded pre-trade gate
3. local analysis profile chain
4. optional bounded Codex context review
5. hard risk engine
6. execution service

Profiles only affect step 3. They can make the gate stricter, but they cannot relax a stricter upstream decision.

## Local Profiles

Configured in [analysis-profiles.yaml](C:/Users/Anderson%20Lora/bugbounty/xm-mt5-trading-platform/config/analysis-profiles.yaml):

- `market_watch`
- `news_scan`
- `macro_window`
- `anomaly_check`
- `log_review`
- `pretrade_context`
- `spread_watch`
- `reconcile_watch`
- `risk_review`
- `session_watch`

## Execution Model

Each profile has:

- `required_inputs`
- `timeout_seconds`
- `missing_input_gate`
- `timeout_gate`
- `error_gate`
- deterministic rule parameters

Profiles can run:

- independently via `ProfileRunner.run_profile(...)`
- as a chain via `ProfileRunner.run_chain(...)`
- in the default pre-trade chain via `ProfileRunner.run_default_chain(...)`

## Fallback Behavior

If a profile cannot run normally, it does not fail open silently.

Supported degraded paths:

- missing inputs -> configured `missing_input_gate`
- timeout -> configured `timeout_gate`
- internal error -> configured `error_gate`
- disabled profile -> configured `skip_gate`

Each degraded result is emitted as a structured profile result with:

- `execution_status`
- `used_fallback`
- `missing_inputs`
- `summary`
- `reasons`

## Integration With Pre-Trade Gate

The pre-trade gate now loads [analysis-profiles.yaml](C:/Users/Anderson%20Lora/bugbounty/xm-mt5-trading-platform/config/analysis-profiles.yaml) automatically when [news.yaml](C:/Users/Anderson%20Lora/bugbounty/xm-mt5-trading-platform/config/news.yaml) is used through the normal runtime path.

The coordinator passes bounded local context into the gate, including:

- market spread and quote age
- session pass/fail state
- reconciliation backlog counts
- reduced-risk mode context
- terminal connectivity hints

The resulting chain summary is attached to the bounded gate decision and written into the news audit payload.

## Example Structured Result

```json
{
  "chain_name": "default",
  "decision_gate": "REDUCE_RISK",
  "impact_level": "medium",
  "reason_codes": [
    "MARKET_SPREAD_ELEVATED",
    "RISK_CONTEXT_REDUCED_MODE"
  ],
  "profile_results": [
    {
      "profile_name": "market_watch",
      "decision_gate": "REDUCE_RISK",
      "execution_status": "COMPLETED"
    },
    {
      "profile_name": "risk_review",
      "decision_gate": "REDUCE_RISK",
      "execution_status": "COMPLETED"
    }
  ]
}
```

## Example Direct Use

```python
from datetime import datetime, UTC

from analysis import AnalysisProfileContext, ProfileRunner

runner = ProfileRunner.from_yaml("config/analysis-profiles.yaml")
context = AnalysisProfileContext(
    symbol="EURUSD",
    timestamp=datetime.now(UTC),
    timeframe="M5",
    context_age_seconds=12.0,
    market_data={"spread_points": 18, "quote_age_seconds": 1, "terminal_connected": True},
    operational_state={"session_allowed": True, "open_positions": 0, "max_open_positions": 1},
    collected_headlines=(),
    relevant_headlines=(),
    stale_headlines=(),
    active_events=(),
    anomaly_signals=(),
    log_lines=(),
)
result = runner.run_default_chain(context=context)
print(result.to_dict())
```

## Operator Notes

- Profiles are local and deterministic; they do not require multiple Codex sessions.
- Profiles are safe to keep enabled in demo mode because degraded execution is explicit.
- If `analysis-profiles.yaml` is missing, the chain is disabled safely and the pre-trade gate still runs.
- Hard risk controls remain authoritative even when a profile returns `ALLOW`.
