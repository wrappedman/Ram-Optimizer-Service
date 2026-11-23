@echo off
REM ===========================================================================
REM  Build build\RamOptimizerService\RamOptimizerService.exe
REM
REM  Same build as build_exe.bat in the repository root; this copy exists so
REM  the build/ folder is self-contained. Logic: tools\build_exe.ps1.
REM ===========================================================================
setlocal
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\tools\build_exe.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo [i] Exit code: %RC%
    pause
)
endlocal & exit /b %RC%
