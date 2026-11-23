# -*- coding: utf-8 -*-
"""کلاس سرویس ویندوز (pywin32).

نکات نسخه‌ی ۲ نسبت به نسخه‌ی قبلی:

* آماده‌سازی (لاگ، پیکربندی، کرش‌لاگ) **قبل** از اعلام ``SERVICE_RUNNING``
  انجام می‌شود؛ اگر پیکربندی یا لاگ خراب باشد، SCM به‌جای یک سرویس «در حال
  اجرا ولی مرده»، خطای واقعی را ثبت می‌کند.
* Pause/Continue پشتیبانی می‌شود (``sc pause`` / ``sc continue``).
* ``SERVICE_ACCEPT_PRESHUTDOWN`` پذیرفته می‌شود؛ در خاموشی سریع ویندوز سرویس
  فرصت می‌کند درست بسته شود (قبلاً بدون گزارش کشته می‌شد).
* فعال‌سازی اختیارها، حلقه و وضعیت همه در :mod:`ramopt.runner` هستند تا کد
  کنسول و سرویس یکی باشد.
"""

from __future__ import annotations

import logging

from ramopt import win32
from ramopt.config import load_config
from ramopt.logging_setup import install_crash_handlers, setup_logging
from ramopt.status import StatusWriter
from ramopt.version import (
    EVENT_SOURCE_NAME,
    SERVICE_DESCRIPTION,
    SERVICE_DISPLAY_NAME,
    SERVICE_NAME,
    __version__,
)

logger = logging.getLogger("RamOptimizer")

try:  # pragma: no cover - فقط ویندوز
    import servicemanager
    import win32event
    import win32service
    import win32serviceutil

    PYWIN32_AVAILABLE = True
except ImportError:  # pragma: no cover - لینوکس/مک برای تست
    PYWIN32_AVAILABLE = False
    servicemanager = None
    win32event = None
    win32service = None
    win32serviceutil = None


if PYWIN32_AVAILABLE:  # pragma: no cover - فقط ویندوز

    class RamOptimizerService(win32serviceutil.ServiceFramework):
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = SERVICE_DISPLAY_NAME
        _svc_description_ = SERVICE_DESCRIPTION

        def __init__(self, args):
            super().__init__(args)
            self._runner = None
            self._config = None
            self._issues = []

        # -- کنترل‌های SCM ---------------------------------------------
        def GetAcceptedControls(self):
            accepted = super().GetAcceptedControls()
            # SERVICE_ACCEPT_PRESHUTDOWN در pywin32 جدید موجود است؛ در نسخه‌های
            # قدیمی مقدار عددی 0x0400 استفاده می‌شود تا import نشکند.
            accepted |= getattr(win32service, "SERVICE_ACCEPT_PRESHUTDOWN", 0x0400)
            return accepted

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING, waitHint=10000)
            logger.info("درخواست توقف سرویس دریافت شد.")
            if self._runner is not None:
                self._runner.stop()

        def SvcShutdown(self):
            logger.info("درخواست خاموشی سیستم — توقف سرویس.")
            self.SvcStop()

        def SvcPause(self):
            self.ReportServiceStatus(win32service.SERVICE_PAUSED)
            logger.info("سرویس موقتاً متوقف شد (Pause).")
            if self._runner is not None:
                self._runner.pause("سرویس توسط مدیر متوقف شد")

        def SvcContinue(self):
            self.ReportServiceStatus(win32service.SERVICE_RUNNING)
            logger.info("سرویس از حالت توقف خارج شد (Continue).")
            if self._runner is not None:
                self._runner.resume()

        # -- اجرا -------------------------------------------------------
        def SvcRun(self):
            """آماده‌سازی را قبل از گزارش RUNNING انجام می‌دهد."""
            self._prepare()
            return super().SvcRun()

        def _prepare(self) -> None:
            install_crash_handlers()
            self._config, self._issues = load_config()
            setup_logging(self._config)
            for issue in self._issues:
                logger.warning(
                    "پیکربندی: [%s] %s = %r → %s",
                    issue.section,
                    issue.key,
                    issue.value,
                    issue.message,
                )
            try:
                servicemanager.SetEventSourceName(EVENT_SOURCE_NAME, True)
            except Exception:  # pragma: no cover - بستگی به دسترسی دارد
                logger.debug("ثبت Event Source ممکن نشد.")

        def SvcDoRun(self):
            servicemanager.LogMsg(
                servicemanager.EVENTLOG_INFORMATION_TYPE,
                servicemanager.PYS_SERVICE_STARTED,
                (self._svc_name_, f"v{__version__}"),
            )
            try:
                from ramopt.runner import OptimizerRunner

                self._runner = OptimizerRunner(
                    config=self._config,
                    api=win32.Win32Api(),
                    status=StatusWriter(),
                )
                self._runner.run_forever()
            except Exception:
                logger.exception("سرویس به‌دلیل خطای کشنده متوقف می‌شود.")
                raise
            finally:
                servicemanager.LogMsg(
                    servicemanager.EVENTLOG_INFORMATION_TYPE,
                    servicemanager.PYS_SERVICE_STOPPED,
                    (self._svc_name_, ""),
                )


else:  # pragma: no cover - لینوکس/مک

    class RamOptimizerService:  # type: ignore[no-redef]
        """جانشین فقط برای این‌که import در تست‌ها نشکند."""

        def __init__(self, *args, **kwargs):
            raise RuntimeError("سرویس ویندوز فقط روی ویندوز قابل استفاده است")


__all__ = ["PYWIN32_AVAILABLE", "RamOptimizerService"]
