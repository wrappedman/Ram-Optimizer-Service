@echo off
setlocal
title RamOptimizer - Schedule as SYSTEM Task (alternative to Windows Service)

:: --- Self-elevate to Administrator ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
)

cd /d "%~dp0"
set "EXE=%~dp0RamOptimizerService\RamOptimizerService.exe"

if not exist "%EXE%" (
    echo [ERROR] EXE not found:
    echo         %EXE%
    pause
    exit /b 1
)

echo Creating scheduled task "RamOptimizer" (runs as SYSTEM at startup, hidden)...
schtasks /Create /TN "RamOptimizer" /TR "\"%EXE%\" console" /SC ONSTART /RU SYSTEM /RL HIGHEST /F
if errorlevel 1 goto :fail

echo Starting the task now...
schtasks /Run /TN "RamOptimizer"

echo.
echo ============================================================
echo  Done. RamOptimizer is now running as a scheduled SYSTEM task
echo  and will start automatically with Windows.
echo  Log file: %ProgramData%\RamOptimizer\ram_optimizer.log
echo ============================================================
pause
exit /b 0

:fail
echo.
echo [ERROR] Failed to create the scheduled task.
pause
exit /b 1
