@echo off
REM ===========================================================================
REM  RAM Optimizer Service - Control Panel
REM
REM  One file for everything: install, remove, status, logs and more.
REM  Double-click it. Administrator rights are requested only when the chosen
REM  action needs them. Nothing runs in the background.
REM
REM  This file is pure ASCII with CRLF line endings on purpose: cmd.exe reads
REM  batch files in the console code page, so UTF-8 comments can break the
REM  block parser. All the logic (and all Persian text) is in
REM  RamOptimizerControl.ps1, which PowerShell decodes as UTF-8.
REM ===========================================================================
setlocal
title RAM Optimizer Service - Control Panel
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0RamOptimizerControl.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo [i] Exit code: %RC%
    pause
)
endlocal & exit /b %RC%
