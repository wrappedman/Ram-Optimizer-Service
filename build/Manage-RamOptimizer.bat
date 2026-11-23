@echo off
rem ===========================================================================
rem  RAM Optimizer Service - Control Panel   /   پنل مدیریت سرویس
rem
rem  یک فایل برای همه‌ی کارها: نصب، حذف، وضعیت، لاگ و کارهای عیب‌یابی.
rem  Double-click it. It asks for Administrator rights only when the chosen
rem  action needs them. Nothing runs in the background.
rem
rem  طراحی: منطق در PowerShell نوشته شده چون گرفتن خروجی exe، تشخیص UTF-8 و
rem  منوی تعاملی در batch خالص شکننده است؛ batch فقط پوسته است.
rem ===========================================================================
setlocal EnableExtensions
title RAM Optimizer Service - Control Panel
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0RamOptimizerControl.ps1" %*
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
    echo.
    echo [i] Exit code: %RC%
    pause
)
endlocal & exit /b %RC%
