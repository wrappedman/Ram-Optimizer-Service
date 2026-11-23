@echo off
setlocal EnableExtensions
title RamOptimizer Service - Install
cd /d "%~dp0"

:: --- Self-elevate to Administrator ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
)

set "EXE=%~dp0RamOptimizerService\RamOptimizerService.exe"
if not exist "%EXE%" set "EXE=%~dp0RamOptimizerService.exe"

if not exist "%EXE%" (
    echo [ERROR] EXE not found next to this file:
    echo         %~dp0RamOptimizerService\RamOptimizerService.exe
    echo Build it first with build_exe.bat.
    pause
    exit /b 1
)

echo ============================================================
echo   Installing "RAM Optimizer Service"
echo   - starts automatically with Windows (delayed start)
echo   - restarts itself automatically if it crashes
echo ============================================================
echo.

echo [1/3] Stopping an older instance (if any)...
"%EXE%" service stop >nul 2>&1

echo [2/3] Registering the service...
"%EXE%" service install --wait 25
if errorlevel 1 (
    echo.
    echo [ERROR] Installation failed.
    echo   If the service is already installed, run uninstall_service.bat first,
    echo   or use "repair" to update the paths:
    echo     "%EXE%" service repair
    echo.
    echo   Diagnostic files:
    echo     %ProgramData%\RamOptimizer\crash.log
    echo     %ProgramData%\RamOptimizer\ram_optimizer.log
    pause
    exit /b 1
)

echo.
echo [3/3] Writing the default configuration (only if missing)...
"%EXE%" config --init >nul 2>&1

echo.
echo ============================================================
echo   Done. Useful commands:
echo     "%EXE%" status                 show current state
echo     "%EXE%" test --dry-run         check what it would do

echo     "%EXE%" test --force           optimize now (ignore threshold)
echo     "%EXE%" service query          service state
echo     notepad %ProgramData%\RamOptimizer\config.ini
echo ============================================================
pause
exit /b 0
