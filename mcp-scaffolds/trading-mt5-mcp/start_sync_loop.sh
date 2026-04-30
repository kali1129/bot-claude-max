#!/bin/bash
export WINEPREFIX=/opt/trading-bot/wine
export WINEARCH=win64
export DISPLAY=:99
export WINEDEBUG=-all
cd /opt/trading-bot/app/mcp-scaffolds/trading-mt5-mcp
exec wine "C:\Program Files\Python311\python.exe" "Z:\opt\trading-bot\app\mcp-scaffolds\trading-mt5-mcp\sync_loop.py" \
    --interval 60 \
    --lookback 7
