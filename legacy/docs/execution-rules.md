# Execution Rules

## Purpose

The execution layer accepts approved risk decisions only. It validates the execution contract, verifies live state freshness, maps intent to broker-compatible requests, and records every attempt.

## Boundaries

- no execution without a valid approved risk decision
- no execution without timestamps
- no execution on stale quotes or stale state
- no execution when terminal or account health is bad
- no execution when a duplicate `decision_id` is detected
- no bypass of the MT5 EA in the preferred live bridge flow

## Execution Flow

```mermaid
flowchart LR
    A["Approved RiskDecision"] --> B["ApprovedExecutionDecision"]
    B --> C["Duplicate Check"]
    C --> D["Latest State Read"]
    D --> E["State + Quote Freshness Checks"]
    E --> F["SL/TP Validation"]
    F --> G["TradeIntent / DecisionMessage"]
    G --> H["Broker Adapter or MT5 EA"]
    H --> I["Execution Outcome"]
    I --> J["Reconciliation"]
    J --> K["Audit + Alerts"]
```

## Accepted Inputs

The execution router requires:

- `approved=True`
- `decision_id`
- `trace_id`
- `symbol`
- `timeframe`
- action of `BUY` or `SELL`
- entry price
- stop loss
- take profit
- positive size or lot value
- creation timestamp

Invalid decisions are rejected before any broker call.

The same `decision_id` is expected to remain intact across the approved risk decision, execution intent, bridge decision file, EA-side processing, and execution result logging.

## Preflight Checks

The execution layer performs these checks before submission:

1. decision contract validation
2. duplicate `decision_id` detection
3. latest state retrieval
4. symbol match between decision and state
5. state staleness check
6. quote age check
7. terminal connectivity check
8. trading enabled and expert enabled checks
9. trade-context-busy check
10. account health check
11. SL/TP geometry validation using the latest quote

## Action Mapping

Internal approved decisions are mapped conservatively:

- `BUY` -> market buy intent or `OPEN_LONG` bridge action
- `SELL` -> market sell intent or `OPEN_SHORT` bridge action
- `HOLD` or other non-entry states -> rejected before submission

In live bridge mode:

- Python writes a bounded `DecisionMessage`
- the EA performs final MT5-side validation
- the EA writes an `ExecutionResultMessage`

## SL/TP Rules

Before submission, the router checks:

- buy orders require `stop_loss < entry < take_profit`
- sell orders require `take_profit < entry < stop_loss`
- live quotes may adjust the routed entry reference
- invalid protective levels cause rejection

## Retry Policy

Retries are allowed only where safe:

- latest state reads may retry according to a bounded policy
- broker order submission is not blindly retried
- duplicate protection prevents accidental re-execution after partial failures

## Partial Failure Handling

| Failure Point | Behavior |
| --- | --- |
| contract invalid | reject and audit |
| duplicate decision | reject and audit |
| no fresh state | return error outcome and alert |
| stale quote | reject and audit |
| terminal disconnected | reject and alert |
| SL/TP invalid | reject and audit |
| broker rejects order | record rejected outcome |
| result missing after submission | timeout error and reconcile later |
| reconciliation mismatch | record mismatch, alert, and require review |

## Reconciliation

The reconciliation store persists:

- bridge state messages
- published decisions
- execution results
- execution attempts
- final execution outcomes
- reconciliation status records

This supports:

- idempotency
- duplicate prevention
- deferred incident review
- broker-vs-internal state checks using pre-submit and post-submit state message IDs
- ticket and broker-order correlation where available
- symbol-volume delta checks so a pre-existing same-symbol position does not count as a successful reconciliation by itself

## Audit Requirements

Every attempt and outcome should be observable through:

- SQLite reconciliation tables
- `logs/<mode>/audit_events.jsonl`
- `logs/<mode>/alerts.jsonl`

Important reason-code families:

- `STATE_STALE`
- `QUOTE_STALE`
- `TERMINAL_DISCONNECTED`
- `TERMINAL_TRADE_DISABLED`
- `TRADE_CONTEXT_BUSY`
- `ACCOUNT_HEALTH_BAD`
- `SLTP_INVALID`
- `DUPLICATE_DECISION_ID`
- `ORDER_REJECTED`
- `RECONCILIATION_MISMATCH`

## Mode-Specific Behavior

| Mode | Execution Behavior |
| --- | --- |
| `demo` | Simulated execution through paper-compatible components |
| `paper` | Full execution routing without broker submission |
| `backtest` | Historical execution simulation inside the backtest engine |
| `live` | MT5 bridge decision publication and EA-side execution |

## Operational Expectations

- treat repeated rejections as an incident
- treat reconciliation mismatch as a higher-severity operational issue
- do not reuse `decision_id` values
- prefer blocking over retrying when state freshness is uncertain
