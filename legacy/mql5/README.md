# MQL5 Bridge

This folder contains MetaTrader 5 Expert Advisors and include files for the local Python bridge.

`XMBridgeEA.mq5` is the preferred live bridge. It publishes state snapshots, consumes bounded decision JSON, validates contract and risk-related execution constraints, and then submits orders through the terminal.

## Files

- `Experts/XMBridgeEA.mq5`: JSON state and decision bridge EA
- `Experts/XMTerminalBridge.mq5`: legacy watchdog EA from the initial starter scaffold
- `Include/bridge_common.mqh`: bridge contract helpers, JSON helpers, and execution validation helpers
- `Include/BridgeTypes.mqh`: legacy helper file used by the watchdog scaffold
- `Files/inbound/control_flags.txt`: written by Python
- `Files/outbound/terminal_status.txt`: written by MT5
