#!/bin/bash
# Watchdog: if /opt/trading-bot/state/auto_trader.heartbeat is stale > 5 min,
# the auto-trader is hung -> kill -9 so systemd restarts it.
# Installed at: /usr/local/bin/auto-trader-watchdog.sh
# Cron: */2 * * * * root /usr/local/bin/auto-trader-watchdog.sh >> /var/log/auto-trader-watchdog.log 2>&1
HB=/opt/trading-bot/state/auto_trader.heartbeat
MAX_AGE_SEC=300
if [ ! -f $HB ]; then
  echo "$(date -u +%FT%TZ) heartbeat missing -- first run? skipping."
  exit 0
fi
AGE=$(( $(date +%s) - $(stat -c%Y $HB) ))
if [ $AGE -gt $MAX_AGE_SEC ]; then
  PID=$(pgrep -f "auto_trader.py --interval" | head -1)
  echo "$(date -u +%FT%TZ) WATCHDOG: heartbeat ${AGE}s stale (max ${MAX_AGE_SEC}s) -- killing PID=$PID"
  if [ -n "$PID" ]; then
    kill -KILL $PID
    pkill -KILL -f "start.exe.*auto_trader" 2>/dev/null
  fi
else
  echo "$(date -u +%FT%TZ) OK (heartbeat ${AGE}s old)"
fi
