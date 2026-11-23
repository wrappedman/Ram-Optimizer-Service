@echo off
setlocal EnableExtensions
title Build RamOptimizerService.exe
cd /d "%~dp0"

echo ============================================================
echo   RamOptimizer - Build EXE (onedir mode - service friendly)
echo   Needs: Windows 10/11 x64 + Python 3.8+ added to PATH
echo ============================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python was not found in PATH.
    echo         Install Python 3.8+ from https://www.python.org/downloads/
    echo         and CHECK the "Add python.exe to PATH" option during setup.
    pause
    exit /b 1
)

echo [1/4] Upgrading pip...
python -m pip install --upgrade pip >nul

echo [2/4] Installing requirements (psutil, pywin32, pyinstaller)...
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail

:: A third-party PyPI package literally named "servicemanager", if present,
:: SHADOWS pywin32's own servicemanager module inside the frozen exe and
:: causes exactly the "service did not respond in a timely fashion" error.
:: Make sure it is not installed.
python -m pip show servicemanager >nul 2>&1
if not errorlevel 1 (
    echo Removing conflicting PyPI package "servicemanager"...
    python -m pip uninstall -y servicemanager
)

echo [3/4] Building with PyInstaller...
:: NOTE: We intentionally do NOT use --onefile. A single-file exe unpacks
:: itself to TEMP on every start and Windows' Service Control Manager often
:: fails to connect to it in time ("service did not respond..."). A onedir
:: build starts instantly and directly as the service process.
python -m PyInstaller --clean --noconfirm ^
    --name RamOptimizerService ^
    --noupx ^
    --hidden-import win32timezone ^
    ram_optimizer_service.py
if errorlevel 1 goto :fail

echo [4/4] Preparing the "release" folder...
if not exist release mkdir release
if exist "release\RamOptimizerService" rmdir /s /q "release\RamOptimizerService"
xcopy "dist\RamOptimizerService" "release\RamOptimizerService\" /E /I /Y /Q >nul
if errorlevel 1 goto :fail
copy /y "install_service.bat"          "release\" >nul
copy /y "uninstall_service.bat"        "release\" >nul
copy /y "install_task.bat"             "release\" >nul
copy /y "uninstall_task.bat"           "release\" >nul
copy /y "README.md"                    "release\" >nul

echo.
echo ============================================================
echo   BUILD OK. Everything you need is in the "release" folder:
echo     release\RamOptimizerService\RamOptimizerService.exe
echo     release\install_service.bat   (just double-click it)
echo     release\uninstall_service.bat
echo ============================================================
pause
exit /b 0

:fail
echo.
echo [ERROR] Build failed. Read the messages above.
pause
exit /b 1
