# -*- coding: utf-8 -*-
"""نسخه‌ی برنامه — تنها منبع حقیقت."""

from __future__ import annotations

import os
import sys

__version__ = "2.0.0"

APP_NAME = "RamOptimizer"
SERVICE_NAME = "RamOptimizerService"
SERVICE_DISPLAY_NAME = "RAM Optimizer Service"
EVENT_SOURCE_NAME = "RamOptimizerService"
SERVICE_DESCRIPTION = (
    "Automatically frees RAM that programs have allocated but no longer use "
    "(working-set trimming + standby-list purge) only when memory is under real "
    "pressure. | آزادسازی خودکار حافظه‌ای که برنامه‌ها اشغال کرده‌اند ولی دیگر "
    "استفاده نمی‌کنند."
)


def _platform_name() -> str:
    if sys.platform == "win32" and hasattr(sys, "getwindowsversion"):
        version = sys.getwindowsversion()
        return f"Windows {version.major}.{version.minor} build {version.build}"
    return sys.platform


def build_info() -> dict[str, str]:
    """اطلاعاتی که هنگام گزارش باگ از کاربر می‌خواهیم."""
    frozen = bool(getattr(sys, "frozen", False))
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "frozen": "yes" if frozen else "no",
        "executable": sys.executable or "",
        "platform": _platform_name(),
        "pid": str(os.getpid()),
    }
