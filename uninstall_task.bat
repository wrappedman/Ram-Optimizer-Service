@echo off
setlocal
title RamOptimizer - Remove Scheduled Task

:: --- Self-elevate to Administrator ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator privileges...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b 0
)

echo Stopping task...
schtasks /End /TN "RamOptimizer" >nul 2>&1

echo Removing task...
schtasks /Delete /TN "RamOptimizer" /F

echo.
echo Done.
pause
