@echo off
setlocal EnableExtensions
title RamOptimizer Service - Remove
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

if exist "%EXE%" (
    echo Stopping and removing the service...
    "%EXE%" service remove --wait 20
) else (
    echo EXE not found - falling back to sc.exe ...
    sc stop RamOptimizerService >nul 2>&1
    sc delete RamOptimizerService >nul 2>&1
)

echo.
set /p PURGE=Also delete logs, config and status in "%ProgramData%\RamOptimizer"? [y/N] 
if /i "%PURGE%"=="y" (
    if exist "%ProgramData%\RamOptimizer" (
        echo Deleting %ProgramData%\RamOptimizer ...
        rmdir /s /q "%ProgramData%\RamOptimizer"
    )
)

echo.
echo ============================================================
echo   Service removed. You can delete this folder now.
echo ============================================================
pause
exit /b 0
