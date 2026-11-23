# -*- coding: utf-8 -*-
"""
================================================================================
 RamOptimizer Windows Service — سرویس ویندوز آزادسازی خودکار RAM
================================================================================
 بدون هیچ‌گونه رابط کاربری یا تنظیماتی؛ کافی است یک‌بار نصب شود و برای همیشه
 در پس‌زمینه حواسش به RAM سیستم است.

 دستورها (همه باید با دسترسی Administrator اجرا شوند — فایل‌های bat همراه
 این کار را خودکار انجام می‌دهند):
   نصب (با شروع خودکار ویندوز):      RamOptimizerService.exe --startup auto install
   شروع:                             RamOptimizerService.exe start
   توقف:                             RamOptimizerService.exe stop
   حذف:                              RamOptimizerService.exe remove
   تست بدون نصب (حالت پیش‌زمینه):     RamOptimizerService.exe console [--once]
   عیب‌یابی سرویس در کنسول:           RamOptimizerService.exe debug
================================================================================
"""

# ---------------------------------------------------------------------------
#  قبل از هر import دیگری: اگر exe موقع اجرا کرش کند، خطا را در crash.log
#  می‌نویسیم تا علت دقیق مشخص شود (به‌خصوص موقع استارت توسط SCM که کنسولی
#  برای نمایش خطا وجود ندارد).
# ---------------------------------------------------------------------------
import os
import sys
import traceback
import datetime


def _install_crash_logger():
    def _hook(exc_type, exc, tb):
        try:
            log_dir = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                                   "RamOptimizer")
            os.makedirs(log_dir, exist_ok=True)
            with open(os.path.join(log_dir, "crash.log"), "a", encoding="utf-8") as f:
                f.write("\n" + "=" * 70 + "\n")
                f.write(datetime.datetime.now().isoformat(timespec="seconds") + "\n")
                traceback.print_exception(exc_type, exc, tb, file=f)
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)
    sys.excepthook = _hook


_install_crash_logger()

# ---------------------------------------------------------------------------

import servicemanager
import win32event
import win32service
import win32serviceutil

import ram_optimizer
from ram_optimizer import (
    CHECK_INTERVAL_SECONDS,
    MEMORY_THRESHOLD_PERCENT,
    logger,
    setup_logging,
)


class RamOptimizerService(win32serviceutil.ServiceFramework):
    _svc_name_         = "RamOptimizerService"
    _svc_display_name_ = "RAM Optimizer Service"
    _svc_description_  = (
        "Automatically frees RAM that programs have allocated but no longer use "
        "(working-set trimming + standby-list purge). | "
        "آزادسازی خودکار حافظه‌ای که برنامه‌ها اشغال کرده‌اند ولی دیگر استفاده نمی‌کنند."
    )

    def __init__(self, args):
        super().__init__(args)
        self._stop_event = win32event.CreateEvent(None, 0, 0, None)
        self._alive = True

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self._alive = False
        win32event.SetEvent(self._stop_event)

    def SvcDoRun(self):
        # مهم: بلافاصله به مدیر سرویس ویندوز (SCM) اعلام می‌کنیم که سرویس آماده‌ی
        # کار است؛ وگرنه بعد از ۳۰ ثانیه خطای «did not respond ... in a timely
        # fashion» رخ می‌دهد.
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        try:
            self.main()
        finally:
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STOPPED,
                (self._svc_name_, ""),
            )

    def main(self):
        setup_logging()
        logger.info("=" * 60)
        logger.info("سرویس RAM Optimizer شروع به کار کرد.")
        logger.info("آستانه‌ی مصرف: %d%% | فاصله‌ی بررسی: %d ثانیه",
                    MEMORY_THRESHOLD_PERCENT, CHECK_INTERVAL_SECONDS)
        ram_optimizer.enable_all_privileges()

        while self._alive:
            try:
                ram_optimizer.check_and_optimize()
            except Exception:
                logger.exception("خطای غیرمنتظره در چرخه بهینه‌سازی "
                                 "(سرویس به کارش ادامه می‌دهد).")

            # به‌جای sleep معمولی روی «رویداد توقف» صبر می‌کنیم تا سرویس
            # بلافاصله به دستور Stop ویندوز جواب بدهد.
            result = win32event.WaitForSingleObject(
                self._stop_event, CHECK_INTERVAL_SECONDS * 1000)
            if result == win32event.WAIT_OBJECT_0:
                break

        logger.info("سرویس RAM Optimizer متوقف شد.")


if __name__ == "__main__":
    # اجرای تستی بدون نصب سرویس:  RamOptimizerService.exe console [--once]
    if len(sys.argv) > 1 and sys.argv[1].lower() == "console":
        sys.argv.pop(1)   # تا ماژول اصلی فقط آرگومان‌های خودش را ببیند
        sys.exit(ram_optimizer.run_console())

    elif len(sys.argv) == 1 and getattr(sys, "frozen", False):
        # *** مهم‌ترین بخش برای exe ساخته‌شده با PyInstaller ***
        # وقتی مدیر سرویس ویندوز (SCM) سرویس را استارت می‌کند، exe را بدون
        # هیچ آرگومانی اجرا می‌کند. در exe فریزشده باید خودمان صریحاً به SCM
        # وصل شویم؛ وگرنه ویندوز بعد از ۳۰ ثانیه خطای معروف
        # «The service did not respond to the start or control request
        #  in a timely fashion» می‌دهد.
        try:
            servicemanager.Initialize()
            servicemanager.PrepareToHostSingle(RamOptimizerService)
            servicemanager.StartServiceCtrlDispatcher()
        except win32service.error as details:
            # یعنی کاربر خودش exe را دابل‌کلیک کرده، نه SCM
            if details.winerror != 1063:  # ERROR_FAILED_SERVICE_CONTROLLER_CONNECT
                raise
            print("This is a Windows service executable (do not run it directly).")
            print("Usage:")
            print("  RamOptimizerService.exe install   (install the service)")
            print("  RamOptimizerService.exe start     (start the service)")
            print("  RamOptimizerService.exe stop      (stop the service)")
            print("  RamOptimizerService.exe remove    (uninstall the service)")
            print("  RamOptimizerService.exe console   (test run, no service)")
            print("  RamOptimizerService.exe debug     (debug service in console)")

    else:
        # دستورهای مدیریتی: install / start / stop / remove / debug / ...
        win32serviceutil.HandleCommandLine(RamOptimizerService)
