@echo off
REM ===========================================================================
REM  Build RamOptimizerService.exe  (thin launcher)
REM
REM  All logic lives in tools\build_exe.ps1. This file stays pure ASCII on
REM  purpose: batch is read in the console code page, and mixing UTF-8
REM  comments with protected blocks made cmd.exe take the wrong branch.
REM
REM  Usage:
REM     build_exe.bat
REM     build_exe.bat -Python "py -3.11"
REM     build_exe.bat -SkipTests
REM ===========================================================================
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\build_exe.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo [i] Exit code: %RC%   ^(2 = no supported Python 3.9-3.13 found^)
    pause
)
endlocal & exit /b %RC%
