@echo off
REM Re-anchors the Bot24hAutoStop scheduled task to fire 24h from the
REM moment of regenerating it (computed by the caller and passed via env).
schtasks /Delete /TN "Bot24hAutoStop" /F 2>nul
schtasks /Create /TN "Bot24hAutoStop" /TR "\"C:\Users\Anderson Lora\bugbounty\NEW-BOT-PRO_MAX\scripts\auto_stop_24h.cmd\"" /SC ONCE /SD 04/29/2026 /ST 14:03 /F
echo ---
schtasks /Query /TN "Bot24hAutoStop" /V /FO LIST
