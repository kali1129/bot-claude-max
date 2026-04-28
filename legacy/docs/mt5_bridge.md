# MT5 Execution Bridge

This document describes the JSON bridge between the Python decision engine and the MetaTrader 5 Expert Advisor for XM.

## Design assumptions

1. The EA is attached to one chart for the active execution symbol.
2. The EA is the only component allowed to submit live trade requests.
3. Python writes bounded decision files and never calls `order_send` directly in the preferred bridge flow.
4. The bridge uses local filesystem directories under `MQL5\Files\inbound` and `MQL5\Files\outbound`.
5. The Python connector treats `.json` files as immutable audit artifacts and uses SQLite to track which message IDs have already been processed.
6. The EA rejects stale decisions using `created_at_epoch + valid_for_seconds`.
7. The EA computes lot size from `risk_pct`, current equity, and stop distance for `OPEN_LONG` and `OPEN_SHORT`.
8. For `REDUCE`, the EA interprets `risk_pct` as the fraction of current symbol exposure to close.
9. For `CLOSE`, the EA closes the full open symbol exposure.
10. `HOLD` and `BLOCK` never place orders. They still produce execution result payloads for auditability.
11. State payloads may be produced even when the terminal is disconnected or quotes are stale. Python should inspect `terminal_status` and freshness before producing decisions.
12. The current starter coordinator still contains legacy live-mode components. The bridge contract and connector introduced here are the preferred live execution boundary.

## Files

- `mql5/Experts/XMBridgeEA.mq5`
- `mql5/Include/bridge_common.mqh`
- `src/brokers/mt5_connector.py`
- `src/decision/decision_contract.py`
- `src/execution/reconciliation.py`

## Message flow

1. EA writes `outbound/state_<message_id>.json`
2. Python connector reads and validates the state payload
3. Python writes `inbound/decision_<message_id>.json`
4. EA validates the decision, checks terminal health, checks quote freshness, checks stops and contract rules, and executes if permitted
5. EA writes `outbound/execution_<message_id>.json`
6. Python reconciliation ingests the execution result and matches it to `decision_id`

## Inbound state payload example

```json
{
  "schema_version": "1.0",
  "message_type": "state",
  "message_id": "state-20260403T071210Z-0001abcd",
  "created_at": "2026-04-03T07:12:10Z",
  "created_at_epoch": 1775200330,
  "symbol": "EURUSD",
  "timeframe": "M5",
  "timestamp": "2026-04-03T07:12:10Z",
  "timestamp_epoch": 1775200330,
  "bid": 1.08231,
  "ask": 1.08244,
  "spread": 13.0,
  "recent_bars": [
    {
      "timestamp": "2026-04-03T07:10:00Z",
      "timestamp_epoch": 1775200200,
      "open": 1.08212,
      "high": 1.08248,
      "low": 1.08202,
      "close": 1.08231,
      "volume": 1243.0
    }
  ],
  "open_positions": [
    {
      "ticket": 123456789,
      "symbol": "EURUSD",
      "direction": "BUY",
      "volume": 0.1,
      "open_price": 1.08195,
      "stop_loss": 1.08075,
      "take_profit": 1.08435,
      "profit": 12.7
    }
  ],
  "balance": 10000.0,
  "equity": 10012.7,
  "free_margin": 9760.4,
  "terminal_status": {
    "connected": true,
    "trade_allowed": true,
    "expert_enabled": true,
    "dlls_allowed": false,
    "trade_context_busy": false,
    "quote_age_seconds": 0,
    "session_status": "CONNECTED",
    "server": "XMGlobal-MT5 7",
    "company": "MetaQuotes Ltd.",
    "ping_ms": 42
  }
}
```

## Outbound decision payload example

```json
{
  "schema_version": "1.0",
  "message_type": "decision",
  "message_id": "decision-20260403T071211Z-1e2a3b4c",
  "decision_id": "decision-20260403T071211Z-9f8e7d6c",
  "state_message_id": "state-20260403T071210Z-0001abcd",
  "created_at": "2026-04-03T07:12:11Z",
  "created_at_epoch": 1775200331,
  "symbol": "EURUSD",
  "timeframe": "M5",
  "action": "OPEN_LONG",
  "stop_loss": 1.0811,
  "take_profit": 1.0845,
  "risk_pct": 0.005,
  "reason_codes": ["STRATEGY_OK", "NEWS_CLEAR", "RISK_OK"],
  "confidence_info": {
    "score": 0.78,
    "source": "deterministic_python_engine",
    "notes": ["bounded", "no llm override"]
  },
  "valid_for_seconds": 15
}
```

## Execution result payload example

```json
{
  "schema_version": "1.0",
  "message_type": "execution_result",
  "message_id": "execution-20260403T071212Z-0a1b2c3d",
  "decision_id": "decision-20260403T071211Z-9f8e7d6c",
  "state_message_id": "state-20260403T071210Z-0001abcd",
  "created_at": "2026-04-03T07:12:12Z",
  "created_at_epoch": 1775200332,
  "symbol": "EURUSD",
  "status": "FILLED",
  "reason": "Request executed",
  "broker_order_id": "983726451",
  "fill_price": 1.08244,
  "filled_volume": 0.1,
  "retcode": 10009,
  "error_code": 0,
  "confidence_info": {}
}
```

## Failure behaviors

- Disconnected terminal: `TERMINAL_DISCONNECTED`
- Stale decision: `STALE_REJECTED`
- Stale quote: `REJECTED` with reason indicating stale quote
- Invalid stops or contract violation: `REJECTED`
- Invalid fill metadata after broker acceptance: `INVALID_FILL`
- Duplicate decision ID: `DUPLICATE_IGNORED`
- Passive actions: `RECEIVED` for `HOLD`, `BLOCKED` for `BLOCK`

## Operational notes

- Keep the inbound and outbound directories on the same local disk as the MT5 terminal.
- Do not edit bridge JSON files in place.
- Use the reconciliation store to resolve retries instead of reusing decision IDs.
- Review `processed_decisions.log` and `bridge_audit.log` for EA-side audit context.
