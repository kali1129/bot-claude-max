@echo off
schtasks /Create /TN "Bot24hAutoStop" /TR "\"C:\Users\Anderson Lora\bugbounty\NEW-BOT-PRO_MAX\scripts\auto_stop_24h.cmd\"" /SC ONCE /SD 04/29/2026 /ST 07:37 /F
echo ---
schtasks /Query /TN "Bot24hAutoStop" /V /FO LIST
