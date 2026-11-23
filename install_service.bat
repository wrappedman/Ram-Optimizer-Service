@echo off
setlocal
title RamOptimizer Service - Install and Start

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
    echo Build it first with build_exe.bat and keep the whole
    echo "RamOptimizerService" folder next to this .bat file.
    pause
    exit /b 1
)

echo Installing service (startup: automatic)...
"%EXE%" --startup auto install
if errorlevel 1 goto :fail

echo Starting service...
"%EXE%" start
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo  RamOptimizerService is installed and running.
echo  It starts automatically with Windows.
echo  Log file: %ProgramData%\RamOptimizer\ram_optimizer.log
echo ============================================================
pause
exit /b 0

:fail
echo.
echo [ERROR] Installation failed.
echo If the service fails to START, check these files and share them:
echo   %ProgramData%\RamOptimizer\crash.log
echo   %ProgramData%\RamOptimizer\ram_optimizer.log
echo Also try:  "%EXE%" debug   (in an admin command prompt)
pause
exit /b 1
