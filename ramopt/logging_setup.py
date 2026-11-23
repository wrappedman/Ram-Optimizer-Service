# -*- coding: utf-8 -*-
"""راه‌اندازی لاگ: فایل چرخشی + رویدادنگار ویندوز + کرش‌لاگ چرخشی.

نکات نسخه‌ی ۲:

* سطح لاگ از پیکربندی خوانده می‌شود (قبلاً همیشه INFO بود و همه‌ی
  ``logger.debug`` عملاً مرده بودند).
* ``crash.log`` هم چرخشی است (قبلاً بی‌نهایت رشد می‌کرد).
* خطاهای داخل تردها هم گرفته می‌شوند (``threading.excepthook``).
* نوشتن روی ``stderr`` نامعتبر (سرویس فریزشده) کل برنامه را نمی‌شکند.
"""

from __future__ import annotations

import datetime
import io
import logging
import logging.handlers
import os
import sys
import threading
import traceback
from typing import TYPE_CHECKING, Any

from ramopt import paths
from ramopt.version import EVENT_SOURCE_NAME

if TYPE_CHECKING:  # pragma: no cover
    from ramopt.config import Config

logger = logging.getLogger("RamOptimizer")

LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_BACKUP_COUNT = 3
CRASH_LOG_MAX_BYTES = 512 * 1024
CRASH_LOG_BACKUP_COUNT = 2

_configured = False
_event_log_failed = False


class _SafeStreamHandler(logging.StreamHandler):
    """StreamHandler‌ای که اگر stderr نامعتبر باشد (سرویس فریزشده) نمی‌شکند."""

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - محیط سرویس
        try:
            if self.stream is None:
                return
            super().emit(record)
        except (OSError, ValueError, AttributeError, UnicodeEncodeError):
            # در exe با کنسول نامعتبر یا کنسول با code page قدیمی
            self.stream = None


def _level_from_name(name: str) -> int:
    return {
        "debug": logging.DEBUG,
        "info": logging.INFO,
        "warning": logging.WARNING,
        "error": logging.ERROR,
        "critical": logging.CRITICAL,
    }.get((name or "info").lower(), logging.INFO)


def setup_logging(config: "Config | None" = None, console: bool | None = None) -> bool:
    """پیکربندی لاگ. خروجی: آیا فایل لاگ با موفقیت باز شد؟

    این تابع idempotent است: فراخوانی دوباره هندلرهای تکراری نمی‌سازد.
    """
    global _configured
    if _configured:
        return True

    level = _level_from_name(config.log_level if config else "info")
    logger.setLevel(level)
    logger.propagate = False

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(threadName)-12s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_ok = False
    try:
        log_path = paths.log_file()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        file_ok = True
    except OSError:
        pass

    # لاگ رویداد ویندوز (فقط اگر pywin32 موجود باشد). در Event Viewer زیر
    # Windows Logs → Application با Source = RamOptimizerService قابل فیلتر است.
    event_handler = _make_event_log_handler(level)
    if event_handler is not None:
        event_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(event_handler)

    # کنسول: در حالت سرویس stderr معمولاً نامعتبر است، پس فقط وقتی
    # واقعاً کنسول داریم آن را می‌سازیم.
    if console is None:
        try:
            console = bool(sys.stderr) and sys.stderr.isatty()
        except (ValueError, AttributeError, OSError):
            console = False
    if console:
        stream = _SafeStreamHandler()
        stream.setFormatter(formatter)
        logger.addHandler(stream)

    _configured = True
    return file_ok


def _make_event_log_handler(level: int) -> logging.Handler | None:
    """ساخت هندلر Event Log ویندوز؛ روی خطا فقط یک‌بار هشدار می‌دهد."""
    global _event_log_failed
    if _event_log_failed or sys.platform != "win32":
        return None
    try:
        import win32evtlogutil

        # اگر منبع رویداد در رجیستری ثبت نشده باشد، ثبت خودکار می‌کنیم
        # (نصب‌کننده هم با --register-event-source این کار را می‌کند).
        win32evtlogutil.AddSourceToRegistry(EVENT_SOURCE_NAME, "", "Application")
    except Exception:  # pragma: no cover - بسته به دسترسی/ویندوز
        _event_log_failed = True
        return None

    BaseHandler: Any = logging.Handler

    class _EventLogHandler(BaseHandler):
        def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover
            global _event_log_failed
            if _event_log_failed:
                return
            try:
                import win32evtlogutil

                type_map = {
                    logging.DEBUG: 1,  # EVENTLOG_INFORMATION_TYPE-ish
                    logging.INFO: 4,  # EVENTLOG_INFORMATION_TYPE
                    logging.WARNING: 2,  # EVENTLOG_WARNING_TYPE
                    logging.ERROR: 1,  # EVENTLOG_ERROR_TYPE
                    logging.CRITICAL: 1,
                }
                if record.levelno < logging.INFO:
                    return  # Event Log را با debug پر نمی‌کنیم
                win32evtlogutil.ReportEvent(
                    EVENT_SOURCE_NAME,
                    1000 + min(record.levelno, 50),
                    eventType=type_map.get(record.levelno, 4),
                    strings=[self.format(record)],
                )
            except Exception:
                # نباید لاگ کردن باعث خرابی شود؛ یک‌بار غیرفعال می‌شود.
                _event_log_failed = True

    handler = _EventLogHandler()
    handler.setLevel(logging.INFO)
    return handler


def _rotate_file(path: str, max_bytes: int, backups: int) -> None:
    """چرخش دستی یک فایل متنی (RotatingFileHandler فقط در ``emit`` می‌چرخد و
    این‌جا ما متن خام می‌نویسیم، پس چرخش را خودمان انجام می‌دهیم)."""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) < max_bytes:
            return
        for index in range(backups - 1, 0, -1):
            source = f"{path}.{index}"
            target = f"{path}.{index + 1}"
            if os.path.isfile(source):
                os.replace(source, target)
        os.replace(path, f"{path}.1")
    except OSError:
        pass


def write_crash(exc_type, exc, tb, note: str = "") -> str | None:
    """نوشتن یک استثنا در crash.log چرخشی. مسیر فایل را برمی‌گرداند."""
    try:
        crash_path = paths.crash_log_file()
        os.makedirs(os.path.dirname(crash_path), exist_ok=True)
        _rotate_file(crash_path, CRASH_LOG_MAX_BYTES, CRASH_LOG_BACKUP_COUNT)

        buffer = io.StringIO()
        buffer.write(f"\n{'=' * 70}\n{datetime.datetime.now().isoformat(timespec='seconds')}")
        if note:
            buffer.write(f" | {note}")
        buffer.write("\n")
        traceback.print_exception(exc_type, exc, tb, file=buffer)
        text = buffer.getvalue()

        with open(crash_path, "a", encoding="utf-8") as handle:
            handle.write(text)
        # اگر یک استثنای غول‌آسا خودش از سقف بزرگ‌تر بود، همان لحظه بچرخان
        _rotate_file(crash_path, CRASH_LOG_MAX_BYTES, CRASH_LOG_BACKUP_COUNT)
        return crash_path
    except Exception:
        return None


def install_crash_handlers() -> None:
    """گرفتن استثناهای کشنده‌ی اصلی و داخل تردها + ثبت اطلاعات بیلد."""

    def _hook(exc_type, exc, tb):
        write_crash(
            exc_type,
            exc,
            tb,
            note=f"thread={threading.current_thread().name}",
        )
        try:
            sys.__excepthook__(exc_type, exc, tb)
        except Exception:
            pass

    sys.excepthook = _hook

    if hasattr(threading, "excepthook"):
        # threading.__excepthook__ فقط از Python 3.10 وجود دارد؛ روی 3.9
        # getattr نمی‌گیریم وگرنه AttributeError خودش باعث کرش می‌شود.
        default_hook = getattr(threading, "__excepthook__", None)

        def _thread_hook(args):  # pragma: no cover - فقط خطای ترد
            write_crash(
                args.exc_type,
                args.exc_value,
                args.exc_traceback,
                note=f"thread={getattr(args.thread, 'name', '?')}",
            )
            if default_hook is not None:
                try:
                    default_hook(args)
                except Exception:
                    pass

        threading.excepthook = _thread_hook


def log_startup_banner(config: "Config", extra: dict[str, object] | None = None) -> None:
    """ثبت خلاصه‌ی پیکربندی هنگام استارت (برای عیب‌یابی از راه دور)."""
    from ramopt.version import build_info

    info = build_info()
    logger.info("=" * 70)
    logger.info("RAM Optimizer Service version %s", info["version"])
    logger.info(
        "configuration: trigger %d%% (reset %d%%) | interval %d s | cooldown %d s | "
        "hourly cap %d | standby purge=%s | min_free_after_trim=%d MB",
        config.trigger_percent,
        config.reset_percent,
        config.check_interval_seconds,
        config.cooldown_seconds,
        config.max_purges_per_hour,
        config.purge_standby_list,
        config.min_free_mb_after_trim,
    )
    logger.info(
        "guards: fullscreen=%s | battery=%s | quiet hours=%s | startup delay=%d s",
        config.skip_when_fullscreen,
        config.skip_on_battery,
        config.quiet_hours or "off",
        config.startup_delay_seconds,
    )
    logger.info(
        "environment: Python %s | frozen=%s | %s", info["python"], info["frozen"], info["platform"]
    )
    logger.info("data folder: %s", paths.data_dir())
    if extra:
        logger.info("extra status: %s", extra)


__all__ = [
    "install_crash_handlers",
    "log_startup_banner",
    "setup_logging",
    "write_crash",
]
