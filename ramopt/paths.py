# -*- coding: utf-8 -*-
"""مسیرهای فایل‌های برنامه (ProgramData با fallback امن).

همه‌ی مسیرها از یک‌جا می‌آیند تا تست‌ها بتوانند با یک متغیر محیطی
(``RAMOPT_DATA_DIR``) کل داده‌ها را به پوشه‌ی موقت منتقل کنند.
"""

from __future__ import annotations

import os
import sys

from ramopt.version import APP_NAME

ENV_DATA_DIR = "RAMOPT_DATA_DIR"


def data_dir() -> str:
    """پوشه‌ی داده‌ها: ``%ProgramData%\\RamOptimizer``.

    ترتیب اولویت:
      1) متغیر محیطی ``RAMOPT_DATA_DIR`` (برای تست و اجرای portable)
      2) ``%ProgramData%\\RamOptimizer``
      3) کنار فایل اجرایی (اگر ProgramData قابل نوشتن نبود)
    """
    override = os.environ.get(ENV_DATA_DIR)
    if override:
        return override

    candidates: list[str] = []
    program_data = os.environ.get("ProgramData")
    if program_data:
        candidates.append(os.path.join(program_data, APP_NAME))

    if getattr(sys, "frozen", False):
        candidates.append(os.path.dirname(sys.executable))
    else:
        candidates.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    for directory in candidates:
        try:
            os.makedirs(directory, exist_ok=True)
            probe = os.path.join(directory, ".write-test")
            with open(probe, "w", encoding="utf-8"):
                pass
            os.remove(probe)
            return directory
        except OSError:
            continue

    # آخرین راه: پوشه‌ی موقت کاربر
    import tempfile

    fallback = os.path.join(tempfile.gettempdir(), APP_NAME)
    os.makedirs(fallback, exist_ok=True)
    return fallback


def log_file() -> str:
    return os.path.join(data_dir(), "ram_optimizer.log")


def crash_log_file() -> str:
    return os.path.join(data_dir(), "crash.log")


def config_file() -> str:
    return os.path.join(data_dir(), "config.ini")


def status_file() -> str:
    return os.path.join(data_dir(), "status.json")


def lock_file() -> str:
    return os.path.join(data_dir(), "instance.lock")


def ensure_data_dir() -> str:
    directory = data_dir()
    os.makedirs(directory, exist_ok=True)
    return directory
