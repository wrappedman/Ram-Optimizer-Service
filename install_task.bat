@echo off
setlocal EnableExtensions
title RamOptimizer - Run as a SYSTEM scheduled task (no service)
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
    echo [ERROR] EXE not found: %EXE%
    pause
    exit /b 1
)

echo ============================================================
echo   Creating scheduled task "RamOptimizer"
echo   Runs as SYSTEM at startup, hidden, forever.
echo ============================================================
echo.

:: Task Scheduler's own defaults are wrong for a permanent daemon:
::   DisallowStartIfOnBatteries = True   -> never starts on a laptop on battery
::   ExecutionTimeLimit         = PT72H  -> Windows kills it after 3 days
:: schtasks.exe cannot clear those, so we build the task with PowerShell.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$exe = '%EXE%';" ^
  "$action = New-ScheduledTaskAction -Execute $exe -Argument 'once' -WorkingDirectory (Split-Path $exe);" ^
  "$trigger = New-ScheduledTaskTrigger -AtStartup;" ^
  "$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew;" ^
  "$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest;" ^
  "Register-ScheduledTask -TaskName 'RamOptimizer' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null;"
if errorlevel 1 (
    echo.
    echo [ERROR] Task creation failed.
    echo   Try running this .bat again from an Administrator prompt.
    pause
    exit /b 1
)

echo Starting the task now...
schtasks /Run /TN "RamOptimizer" >nul 2>&1

echo.
echo ============================================================
echo   Done. RamOptimizer runs as a SYSTEM task and starts with Windows.
echo   Note: a task starts the whole process over at every boot; the
echo   Windows service option is still the recommended way.
echo   Log: %ProgramData%\RamOptimizer\ram_optimizer.log
echo ============================================================
pause
exit /b 0
