@echo off
setlocal
set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..

echo [MedPaperFlow] Register daily dual-domain task at 05:30...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%register_daily_dual_domains_task.ps1" -TaskName "MedPaperFlow-DualDaily" -StartTime "05:30" -ProjectRoot "%PROJECT_ROOT%" -Force

echo.
echo Done. Press any key to exit.
pause >nul
