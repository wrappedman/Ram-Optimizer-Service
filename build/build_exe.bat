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

:: --- 0) Find a supported Python -------------------------------------------
:: PyInstaller and this project support 3.9 - 3.13. If PATH only exposes a
:: newer Python (3.14+), the build fails with confusing errors deep inside
:: PyInstaller, so we look for a supported one first and say so clearly.
set "PYEXE="
for %%V in (3.13 3.12 3.11 3.10 3.9) do (
    if not defined PYEXE (
        py -%%V -c "import sys" >nul 2>&1
        if not errorlevel 1 set "PYEXE=py -%%V"
    )
)
if not defined PYEXE (
    where python >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%O in ('python -c "import sys;print(sys.version_info[0]*100+sys.version_info[1])"') do set "PYVER=%%O"
        if defined PYVER if !PYVER! LSS 314 set "PYEXE=python"
    )
)
if not defined PYEXE (
    echo [ERROR] No supported Python found ^(3.9 - 3.13^).
    echo         PyInstaller does not support 3.14+ yet, and this project targets 3.9+.
    echo         Install Python 3.11 from https://www.python.org/downloads/
    echo         ^(tick "Add python.exe to PATH"^), or run:  py -3.11 build_exe.bat
    echo.
    echo         Detected "python": 
    python -c "import sys;print('  ', sys.version)" 2>nul
    pause
    exit /b 1
)
echo [0/6] Using %PYEXE%

if not exist ".venv\Scripts\python.exe" (
    echo [1/6] Creating virtual environment...
    %PYEXE% -m venv .venv
    if errorlevel 1 goto :fail
) else (
    echo [1/6] Using existing virtual environment.
)
set "PY=.venv\Scripts\python.exe"
"%PY%" -c "import sys; assert sys.version_info[:2] <= (3, 13), 'venv has an unsupported Python: ' + sys.version" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] .venv was created with Python 3.14+ ^(unsupported by PyInstaller^).
    echo         Delete the .venv folder and run this script again.
    pause
    exit /b 1
)

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
