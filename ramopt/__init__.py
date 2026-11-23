# -*- coding: utf-8 -*-
"""Ram Optimizer Service — سرویس ویندوز آزادسازی حافظه.

پکیج اصلی برنامه. ماژول‌ها:

``version``     نسخه‌ی برنامه و اطلاعات بیلد.
``paths``       مسیرهای ProgramData (لاگ، پیکربندی، وضعیت) با fallback امن.
``config``      مدل پیکربندی + خواندن/نوشتن ``config.ini``.
``logging_setup`` لاگ چرخشی فایل + رویدادنگار ویندوز.
``win32``       لایه‌ی نازک روی Win32 (ctypes) — قابل mock کردن در تست‌ها.
``memory``      اندازه‌گیری واقعی حافظه و دستورهای Memory List.
``engine``      سیاست تصمیم‌گیری و اجرای پاک‌سازی (بدون وابستگی به ویندوز).
``status``      نوشتن ``status.json`` برای پایش بیرونی.
``service``     کلاس سرویس ویندوز (pywin32).
``cli``         خط فرمان + دستورهای مدیریت سرویس.
"""

from ramopt.version import __version__, build_info

__all__ = ["__version__", "build_info"]
