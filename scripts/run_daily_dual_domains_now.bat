@echo off
setlocal
set SCRIPT_DIR=%~dp0

echo [MedPaperFlow] Run medical + cqed_plasmonics now...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run_daily_dual_domains.ps1"

echo.
echo Done. Press any key to exit.
pause >nul
