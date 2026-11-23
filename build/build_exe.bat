@echo off
rem ===========================================================================
rem  Build build\RamOptimizerService\RamOptimizerService.exe
rem
rem  One-click build from the source tree: creates/updates .venv, runs the
rem  tests, builds the onedir exe with PyInstaller and copies it to build\.
rem  Then run Manage-RamOptimizer.bat to install/remove/check it.
rem
rem  This is the Windows equivalent of what the CI "windows" job does.
rem ===========================================================================
setlocal EnableExtensions EnableDelayedExpansion
title Build RamOptimizerService
cd /d "%~dp0.."

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found in PATH.
    echo         Install Python 3.9+ from https://www.python.org/downloads/
    echo         and tick "Add python.exe to PATH" during setup.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/6] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 goto :fail
) else (
    echo [1/6] Using existing virtual environment.
)
set "PY=.venv\Scripts\python.exe"

echo [2/6] Installing build requirements...
"%PY%" -m pip install --upgrade pip >nul 2>&1
"%PY%" -m pip install -r requirements-dev.txt
if errorlevel 1 goto :fail

:: A third-party PyPI package named "servicemanager" SHADOWS pywin32's own
:: servicemanager inside the frozen exe ("service did not respond in a
:: timely fashion"). Make sure it is gone.
"%PY%" -m pip show servicemanager >nul 2>&1
if not errorlevel 1 (
    echo Removing the conflicting PyPI package "servicemanager"...
    "%PY%" -m pip uninstall -y servicemanager
)

echo [3/6] Running the test suite...
"%PY%" -m pytest -q
if errorlevel 1 (
    echo [ERROR] Tests failed - not shipping a broken build.
    goto :fail
)

echo [4/6] Generating version_info.txt...
"%PY%" tools\make_version_info.py
if errorlevel 1 goto :fail

echo [5/6] Building with PyInstaller (onedir)...
"%PY%" -m PyInstaller --clean --noconfirm RamOptimizerService.spec
if errorlevel 1 goto :fail

echo [6/6] Copying the result to build\...
if not exist "build" mkdir build
if exist "build\RamOptimizerService" rmdir /s /q "build\RamOptimizerService"
xcopy "dist\RamOptimizerService" "build\RamOptimizerService\" /E /I /Y /Q >nul
if errorlevel 1 goto :fail
"%PY%" tools\make_build_info.py
if errorlevel 1 goto :fail

echo.
echo ============================================================
echo   BUILD OK
echo     build\RamOptimizerService\RamOptimizerService.exe
echo     build\Manage-RamOptimizer.bat   (install / remove / status / logs)
echo ============================================================
echo.
pause
exit /b 0

:fail
echo.
echo [ERROR] Build failed - read the messages above.
pause
exit /b 1
