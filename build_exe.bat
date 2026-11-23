@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Build RamOptimizerService
cd /d "%~dp0"

echo ============================================================
echo   RAM Optimizer Service - Build
echo   Requirements: Windows 10/11 x64, Python 3.9 - 3.13
echo ============================================================
echo.

:: ---------------------------------------------------------------
:: 0) Find a supported Python
::    PyInstaller does not support 3.14+ yet. If PATH only has a newer
::    Python, the build fails deep inside PyInstaller with confusing
::    errors, so pick a supported interpreter up front and say so.
:: ---------------------------------------------------------------
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
    echo         PyInstaller does not support 3.14+ yet.
    echo         Install Python 3.11 from https://www.python.org/downloads/
    echo         ^(tick "Add python.exe to PATH"^), or run:  py -3.11 build_exe.bat
    echo.
    echo         Detected "python":
    python -c "import sys;print('  ', sys.version)" 2>nul
    pause
    exit /b 1
)
echo [0/6] Using %PYEXE%

:: ---------------------------------------------------------------
:: 1) Virtual environment (بدون آلوده کردن پایتون سیستم)
:: ---------------------------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [1/6] Creating virtual environment...
    %PYEXE% -m venv .venv
    if errorlevel 1 goto :fail
) else (
    echo [1/6] Using existing virtual environment.
)
set "PY=.venv\Scripts\python.exe"

echo [2/6] Installing build requirements...
"%PY%" -m pip install --upgrade pip >nul 2>&1
"%PY%" -m pip install -r requirements-dev.txt
if errorlevel 1 goto :fail

"%PY%" -c "import sys; raise SystemExit(0 if sys.version_info[:2] <= (3, 13) else 1)" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] .venv was created with Python 3.14+ ^(unsupported by PyInstaller^).
    echo         Delete the .venv folder and run this script again.
    pause
    exit /b 1
)

:: A third-party PyPI package literally named "servicemanager" SHADOWS
:: pywin32's own servicemanager inside the frozen exe and causes exactly the
:: "service did not respond in a timely fashion" error. Make sure it is gone.
"%PY%" -m pip show servicemanager >nul 2>&1
if not errorlevel 1 (
    echo Removing conflicting PyPI package "servicemanager"...
    "%PY%" -m pip uninstall -y servicemanager
)

:: ---------------------------------------------------------------
:: 2) Tests - if the suite fails, do not ship a broken build
:: ---------------------------------------------------------------
echo [3/6] Running the test suite...
"%PY%" -m pytest -q
if errorlevel 1 (
    echo [ERROR] Tests failed - fix them before building.
    goto :fail
)

:: ---------------------------------------------------------------
:: 3) Version info (so the exe has a real version in Explorer)
:: ---------------------------------------------------------------
echo [4/6] Generating version_info.txt...
"%PY%" tools\make_version_info.py
if errorlevel 1 goto :fail

:: ---------------------------------------------------------------
:: 4) Build (onedir - see RamOptimizerService.spec for why)
:: ---------------------------------------------------------------
echo [5/6] Building with PyInstaller...
"%PY%" -m PyInstaller --clean --noconfirm RamOptimizerService.spec
if errorlevel 1 goto :fail

:: ---------------------------------------------------------------
:: 5) Release folder
:: ---------------------------------------------------------------
echo [6/6] Preparing the "release" folder...
if not exist release mkdir release
if exist "release\RamOptimizerService" rmdir /s /q "release\RamOptimizerService"
xcopy "dist\RamOptimizerService" "release\RamOptimizerService\" /E /I /Y /Q >nul
if errorlevel 1 goto :fail

copy /y "install_service.bat"   "release\" >nul
copy /y "uninstall_service.bat" "release\" >nul
copy /y "install_task.bat"      "release\" >nul
copy /y "uninstall_task.bat"    "release\" >nul
copy /y "README.md"             "release\" >nul
copy /y "README.en.md"          "release\" >nul
"%PY%" -c "from ramopt.config import default_config_text; open(r'release\config.ini.example','w',encoding='utf-8').write(default_config_text())"
copy /y "LICENSE"               "release\" >nul
if exist "CHANGELOG.md" copy /y "CHANGELOG.md" "release\" >nul

:: Checksums so users can verify what they got
if exist "release\SHA256SUMS.txt" del "release\SHA256SUMS.txt"
for %%F in ("release\RamOptimizerService\RamOptimizerService.exe") do (
    certutil -hashfile "%%~fF" SHA256 | findstr /v /c:"hash" /c:"CertUtil" >> "release\SHA256SUMS.txt"
)

echo.
echo ============================================================
echo   BUILD OK. Everything you need is in the "release" folder:
echo     release\RamOptimizerService\RamOptimizerService.exe
echo     release\install_service.bat   (double-click, then Yes on UAC)
echo ============================================================
echo.
pause
exit /b 0

:fail
echo.
echo [ERROR] Build failed. Read the messages above.
pause
exit /b 1
