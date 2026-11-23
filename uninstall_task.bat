@echo off
setlocal EnableExtensions
title RamOptimizer - Remove scheduled task
cd /d "%~dp0"

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
if errorlevel 1 (
    echo Task "RamOptimizer" was not found - nothing to remove.
)

echo.
echo Done.
pause
exit /b 0
