# -*- coding: utf-8 -*-
"""نقطه‌ی ورود exe سرویس (RamOptimizerService.exe).

نصب و اجرای سرویس دیگر از ``win32serviceutil.HandleCommandLine`` استفاده
نمی‌کند (دلیل در :mod:`ramopt.service_admin` توضیح داده شده). این فایل فقط
سه کار دارد:

1. سرویس استارت‌شده توسط SCM را میزبانی کند (``servicemanager``)؛
2. اگر از کنسول اجرا شد، پیام قابل‌فهم نشان دهد و دستور مدیریتی را اجرا کند؛
3. کرش‌های زودهنگام (قبل از راه‌اندازی لاگ) را در ``crash.log`` ثبت کند.

دستورهای مدیریتی::

    RamOptimizerService.exe install|remove|start|stop|restart|pause|continue|query|repair
    RamOptimizerService.exe console        اجرای دائمی در پیش‌زمینه
    RamOptimizerService.exe test --dry-run  آزمون بدون تغییر سیستم
    RamOptimizerService.exe install --startup auto   (سازگار با نسخه‌ی قدیمی)
"""

from __future__ import annotations

import sys


# ---------------------------------------------------------------------------
# ثبت کرش‌های زودهنگام: قبل از هر import دیگری (وقتی SCM استارت می‌کند
# کنسولی وجود ندارد و بدون این کار هیچ اثری از خطا نمی‌ماند).
# ---------------------------------------------------------------------------
def _install_early_crash_logger() -> None:
    try:
        sys.path.insert(0, _base_dir())
        from ramopt.logging_setup import install_crash_handlers

        install_crash_handlers()
    except Exception:  # pragma: no cover - اگر خود ramopt بارگذاری نشد
        pass


def _base_dir() -> str:
    import os

    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


_install_early_crash_logger()

# ---------------------------------------------------------------------------


def _is_service_start(argv: list[str]) -> bool:
    """SCM برنامه را بدون آرگومان اجرا می‌کند."""
    return len(argv) == 1


def _dispatch_service() -> int:
    """اتصال به SCM و میزبانی کلاس سرویس."""
    import servicemanager

    from ramopt.service import RamOptimizerService
    from ramopt.version import SERVICE_NAME

    servicemanager.Initialize(SERVICE_NAME, sys.executable)
    servicemanager.PrepareToHostSingle(RamOptimizerService)
    servicemanager.StartServiceCtrlDispatcher()
    return 0


def _print_usage() -> None:
    print("RAM Optimizer Service — اجرای مستقیم این فایل سرویس را نصب نمی‌کند.")
    print("دستورها:")
    print("  RamOptimizerService.exe install     نصب سرویس (شروع خودکار با تأخیر)")
    print("  RamOptimizerService.exe remove      حذف سرویس")
    print("  RamOptimizerService.exe start|stop|restart|pause|continue|query")
    print("  RamOptimizerService.exe repair      اصلاح مسیر/تنظیمات نصب فعلی")
    print("  RamOptimizerService.exe console     اجرای دائمی در پیش‌زمینه (بدون نصب)")
    print("  RamOptimizerService.exe test        یک چرخه‌ی آزمایشی (--dry-run = بدون تغییر)")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)

    if _is_service_start(args):
        try:
            return _dispatch_service()
        except Exception as exc:  # pragma: no cover - فقط ویندوز/SCM
            winerror = getattr(exc, "winerror", None)
            if winerror == 1063:  # ERROR_FAILED_SERVICE_CONTROLLER_CONNECT
                _print_usage()
                return 0
            from ramopt.logging_setup import write_crash

            write_crash(type(exc), exc, exc.__traceback__, note="service dispatch failed")
            print(f"[خطا] استارت سرویس ناموفق بود: {exc}")
            return 1

    from ramopt.cli import main as cli_main

    # دستورهای قدیمی (install/start/remove/…) در ramopt.cli.normalize_argv
    # به «service <action>» تبدیل می‌شوند.
    return cli_main(args[1:])


if __name__ == "__main__":
    sys.exit(main())
