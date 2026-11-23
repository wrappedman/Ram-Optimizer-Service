# -*- coding: utf-8 -*-
"""``status.json`` — پل ارتباطی با ابزارهای پایش بیرونی.

هر چرخه (حتی وقتی کاری انجام نمی‌شود) یک فایل کوچک نوشته می‌شود. با این
فایل می‌توان بدون خواندن لاگ فهمید سرویس زنده است یا نه::

    {
      "version": "2.0.0",
      "state": "running",
      "pid": 1234,
      "started_at": "...",
      "last_cycle_at": "...",
      "first_cycle_at": "...",
      "last_action": "optimized",
      "last_reason": "...",
      "memory": {"used_percent": 81.2, "available_mb": 2450.0, ...},
      "counters": {"purges": 3, "freed_mb": 812.5, "errors": 0},
      "next_allowed_at": "..."
    }

نوشتن اتمیک است (فایل موقت + ``os.replace``) تا خواننده هرگز فایل نیمه‌نوشته
نبیند.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from typing import Any

from ramopt import paths
from ramopt.version import __version__

logger = logging.getLogger("RamOptimizer")

MAX_ERRORS_KEPT = 5


class StatusWriter:
    """نگه‌دارنده‌ی وضعیت و نوشتن آن در ``status.json``."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or paths.status_file()
        self.state = "starting"
        self.started_at: str | None = None
        self.first_cycle_at: str | None = None
        self.last_cycle_at: str | None = None
        self.last_action: str | None = None
        self.last_reason: str | None = None
        self.memory: dict[str, Any] = {}
        self.counters: dict[str, Any] = {"purges": 0, "freed_mb": 0.0, "errors": 0, "cycles": 0}
        self.recent_errors: list[dict[str, str]] = []
        self.next_allowed_at: str | None = None
        self.extra: dict[str, Any] = {}

    def record_error(self, message: str, timestamp: str) -> None:
        self.counters["errors"] = int(self.counters.get("errors", 0)) + 1
        self.recent_errors.append({"at": timestamp, "message": message[:500]})
        del self.recent_errors[:-MAX_ERRORS_KEPT]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": __version__,
            "state": self.state,
            "pid": os.getpid(),
            "started_at": self.started_at,
            "first_cycle_at": self.first_cycle_at,
            "last_cycle_at": self.last_cycle_at,
            "last_action": self.last_action,
            "last_reason": self.last_reason,
            "memory": self.memory,
            "counters": self.counters,
            "recent_errors": self.recent_errors,
            "next_allowed_at": self.next_allowed_at,
            **self.extra,
        }

    def write(self) -> bool:
        """نوشتن اتمیک فایل وضعیت. خطا فقط لاگ می‌شود (هرگز استثنا نمی‌دهد)."""
        try:
            directory = os.path.dirname(self.path) or "."
            os.makedirs(directory, exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(prefix=".status-", suffix=".json", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)
                    handle.write("\n")
                os.replace(tmp_path, self.path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
            return True
        except Exception as exc:  # pragma: no cover - خطای دیسک
            logger.debug("could not write status.json: %s", exc)
            return False


def read_status(path: str | None = None) -> dict[str, Any] | None:
    """خواندن status.json برای ابزارهای بیرونی/CLI."""
    status_path = path or paths.status_file()
    try:
        with open(status_path, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


__all__ = ["StatusWriter", "read_status"]
