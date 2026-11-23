# -*- coding: utf-8 -*-
"""ابزارهای مشترک اسکریپت‌های ``tools/``.

مشکل واقعی (CI ویندوز): چاپ متن فارسی روی کنسول cp1252 کنسول ویندوز با
``UnicodeEncodeError`` می‌میرد و کل بیلد را می‌خواباند. اینجا خروجی را یک بار
برای همیشه امن می‌کنیم.
"""

from __future__ import annotations

import sys


def force_utf8_console() -> None:
    """خروجی استاندارد را UTF-8 با خطای ``replace`` می‌کند (idempotent)."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def say(message: str = "") -> None:
    """چاپ امن: اگر کنسول UTF-8 نپذیرفت، به ASCII برمی‌گردیم."""
    force_utf8_console()
    try:
        print(message)
    except UnicodeEncodeError:  # pragma: no cover - کنسول عجیب
        encoding = getattr(sys.stdout, "encoding", None) or "ascii"
        print(message.encode(encoding, "replace").decode(encoding, "replace"))
