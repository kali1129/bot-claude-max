@echo off
REM Discontinue xm-mt5-trading-platform — Windows side
REM
REM This script (a) lists scheduled tasks and shortcuts that point to the
REM legacy bot, (b) attempts to delete them, and (c) prints the final
REM rmdir command for the user to run after the user confirms backups exist.
REM
REM SAFETY: this does NOT auto-delete xm-mt5-trading-platform/. The user
REM must run the printed `rmdir /S /Q` command manually after verifying:
REM   - C:\Users\Anderson Lora\bugbounty\_archive\xm-mt5-trading-platform-*.tar.gz exists
REM   - The bot nuevo is fully functional
REM   - Capa 6 seed_legacy_journal has been run if the trade history is wanted
REM
REM Run from an elevated (Administrator) cmd.exe.

echo === Discontinue legacy bot xm-mt5-trading-platform ===
echo.

set LEGACY_PATH=C:\Users\Anderson Lora\bugbounty\xm-mt5-trading-platform
set ARCHIVE_DIR=C:\Users\Anderson Lora\bugbounty\_archive

echo [1/4] Verifying archive exists...
dir "%ARCHIVE_DIR%\xm-mt5-trading-platform-*.tar.gz" 2>nul
if errorlevel 1 (
    echo ERROR: no archive found in %ARCHIVE_DIR%. ABORTING.
    echo Re-run capa 0 of the migration first.
    exit /b 1
)
echo OK
echo.

echo [2/4] Listing scheduled tasks that mention xm-mt5-trading-platform...
schtasks /Query /FO LIST /V | findstr /I "xm-mt5-trading-platform" >nul
if not errorlevel 1 (
    echo Found scheduled tasks. Disabling them:
    REM Iterate over candidate task names. Add others here as discovered.
    for %%T in (
        "Daurel Nightly Research"
        "XM Bot Demo Autostart"
        "XM Bot Live Autostart"
        "XM Bot Paper Autostart"
        "XM Bot Telegram Autostart"
    ) do (
        schtasks /Change /TN %%T /DISABLE 2>nul && echo   disabled %%T
    )
) else (
    echo No matching scheduled tasks found.
)
echo.

echo [3/4] Listing legacy .cmd shortcuts in C:\Users\Anderson Lora\bugbounty\...
dir /B "C:\Users\Anderson Lora\bugbounty\*.cmd" 2>nul | findstr /I "XM Bot OpenClaw Codex Daurel"
echo.
echo (Manual step) The following shortcuts point to the legacy bot. Move them
echo to %ARCHIVE_DIR%\windows-shortcuts\ or delete them by hand:
echo   - "C:\Users\Anderson Lora\bugbounty\🚀 Iniciar Bot XM.cmd"
echo   - "C:\Users\Anderson Lora\bugbounty\🛑 Detener Bot XM.cmd"
echo   - Any "Codex *Slot*.cmd" or "OpenClaw *.cmd" in that folder
echo.

echo [4/4] Final step — review then run:
echo   rmdir /S /Q "%LEGACY_PATH%"
echo.
echo This step is NOT executed automatically. After confirming the bot nuevo
echo (NEW-BOT-PRO_MAX) works end-to-end, run the rmdir command above.
echo.
echo === Done ===
