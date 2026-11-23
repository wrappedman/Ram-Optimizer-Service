@echo off
setlocal
title RamOptimizer Service - Stop and Remove

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
    echo Falling back to sc.exe ...
    sc stop RamOptimizerService
    sc delete RamOptimizerService
    pause
    exit /b 0
)

echo Stopping service...
"%EXE%" stop

echo Removing service...
"%EXE%" remove

echo.
echo ============================================================
echo  RamOptimizerService was stopped and removed.
echo ============================================================
pause
