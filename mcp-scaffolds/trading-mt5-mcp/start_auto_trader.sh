#!/bin/bash
export WINEPREFIX=/opt/trading-bot/wine
export WINEARCH=win64
export DISPLAY=:99
export WINEDEBUG=-all
cd /opt/trading-bot/app/mcp-scaffolds/trading-mt5-mcp
exec wine "C:\Program Files\Python311\python.exe" "Z:\opt\trading-bot\app\mcp-scaffolds\trading-mt5-mcp\auto_trader.py" \
    --interval 120 \
    --risk-pct 2.0 \
    --min-score 40
