@echo off
REM Triggered by Windows Task Scheduler 24h after test start.
REM Calls the backend API to stop the bot and notify Telegram.
"C:\Users\Anderson Lora\bugbounty\NEW-BOT-PRO_MAX\backend\.venv\Scripts\python.exe" "C:\Users\Anderson Lora\bugbounty\NEW-BOT-PRO_MAX\scripts\auto_stop_24h.py" >> "%USERPROFILE%\mcp\logs\auto_stop_24h.log" 2>&1
