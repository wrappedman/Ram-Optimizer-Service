# -*- coding: utf-8 -*-
"""حلقه‌ی اجرای مشترک بین سرویس ویندوز، تسک زمان‌بندی و حالت کنسول.

قبلاً حلقه در دو جا (کنسول و سرویس) تکرار شده بود و رفتارشان کمی متفاوت؛
این‌جا یک‌بار نوشته شده و هر دو از آن استفاده می‌کنند.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading

from ramopt import memory as memory_mod
from ramopt import win32
from ramopt.config import Config
from ramopt.engine import Action, OptimizerEngine
from ramopt.logging_setup import log_startup_banner
from ramopt.status import StatusWriter

logger = logging.getLogger("RamOptimizer")

#: هر چند چرخه یک‌بار شمارنده‌ی «زنده‌ام» را در لاگ بنویسیم.
HEARTBEAT_EVERY_N_CYCLES = 60


class OptimizerRunner:
    """چرخه‌ی اندازه‌گیری → تصمیم → اجرا را با قابلیت توقف فوری اجرا می‌کند."""

    def __init__(
        self,
        config: Config,
        api: "win32.Win32Api | None" = None,
        provider: memory_mod.ProcessProvider | None = None,
        status: StatusWriter | None = None,
        engine: OptimizerEngine | None = None,
    ) -> None:
        self.config = config
        self.api = api or win32.Win32Api()
        self.status = status or StatusWriter()
        self.engine = engine or OptimizerEngine(config, self.api, provider)
        self._stop_event = threading.Event()
        self._cycles = 0

    # -- کنترل -------------------------------------------------------------
    def stop(self) -> None:
        self._stop_event.set()

    def pause(self, reason: str = "درخواست مدیر سرویس") -> None:
        self.engine.pause(reason)
        self.status.state = "paused"
        self.status.extra["pause_reason"] = self.engine.pause_reason
        self.status.write()

    def resume(self) -> None:
        self.engine.resume()
        self.status.state = "running"
        self.status.extra.pop("pause_reason", None)
        self.status.write()

    @property
    def stopped(self) -> bool:
        return self._stop_event.is_set()

    # -- آماده‌سازی ---------------------------------------------------------
    def prepare(self) -> None:
        """فعال‌سازی اختیارها + گزارش شروع. یک‌بار در ابتدای اجرا صدا زده می‌شود."""
        log_startup_banner(self.config)

        if not self.api.available:
            logger.error("Win32 در دسترس نیست: %s", self.api.load_error)
        else:
            # فقط اختیارهایی که واقعاً لازم‌اند. SeDebugPrivilege لازم نیست و
            # فعال کردنش هشدار آنتی‌ویروس را بیشتر می‌کند.
            required = ("SeProfileSingleProcessPrivilege", "SeIncreaseQuotaPrivilege")
            missing = [name for name in required if not self.api.enable_privilege(name)]
            if missing:
                logger.warning(
                    "این اختیارها فعال نشدند: %s — برنامه احتمالاً با دسترسی "
                    "Administrator/SYSTEM اجرا نشده؛ بخشی از حافظه پاک نخواهد شد.",
                    ", ".join(missing),
                )

        self.status.started_at = dt.datetime.now().isoformat(timespec="seconds")
        self.status.state = "running"
        self.status.extra["privileges_ok"] = bool(self.api.available)
        self.status.write()

    # -- حلقه --------------------------------------------------------------
    def run_once(self) -> None:
        """یک چرخه (بدون خوابیدن). استثناها این‌جا گرفته می‌شوند."""
        timestamp = dt.datetime.now().isoformat(timespec="seconds")
        try:
            result = self.engine.run_cycle()
        except Exception as exc:  # pragma: no cover - دفاعی
            logger.exception("خطای غیرمنتظره در چرخه‌ی بهینه‌سازی (ادامه می‌دهیم).")
            self.status.record_error(f"{type(exc).__name__}: {exc}", timestamp)
            self.status.last_cycle_at = timestamp
            self.status.last_action = "error"
            self.status.write()
            return

        self._cycles += 1
        self.status.last_cycle_at = result.timestamp
        self.status.first_cycle_at = self.status.first_cycle_at or result.timestamp
        self.status.last_action = result.action.value
        self.status.last_reason = result.reason
        self.status.counters["cycles"] = self._cycles
        self.status.memory = {
            "used_percent": round(result.used_percent_before or 0.0, 1),
            "available_mb": round(result.available_mb_before or 0.0, 0),
            "commit_percent": round(result.commit_percent or 0.0, 1),
            "standby_mb": None
            if result.standby_mb_before is None
            else round(result.standby_mb_before, 0),
            "total_mb": None,
        }
        if result.action is Action.OPTIMIZED:
            self.status.counters["purges"] = int(self.status.counters.get("purges", 0)) + 1
            self.status.counters["freed_mb"] = round(
                float(self.status.counters.get("freed_mb", 0.0)) + result.freed_mb, 1
            )
        next_allowed = None
        if self.engine.last_purge_at is not None:
            next_allowed = (
                self.engine.last_purge_at + dt.timedelta(seconds=self.config.cooldown_seconds)
            ).isoformat(timespec="seconds")
        self.status.next_allowed_at = next_allowed
        self.status.write()

        if self._cycles % HEARTBEAT_EVERY_N_CYCLES == 0:
            logger.info(
                "Heartbeat | چرخه %d | حالت %s | آپ‌تایم %s | مجموع پاک‌سازی %d (%.0fMB)",
                self._cycles,
                self.engine.mode.value,
                _uptime_text(self.status.started_at),
                self.status.counters.get("purges", 0),
                float(self.status.counters.get("freed_mb", 0.0)),
            )

    def run_forever(self) -> None:
        """حلقه‌ی اصلی. با ``stop()`` بلافاصله خارج می‌شود (نه با خواب طولانی)."""
        self.prepare()
        logger.info(
            "حلقه‌ی بهینه‌سازی شروع شد (فاصله: %d ثانیه).", self.config.check_interval_seconds
        )

        while not self._stop_event.is_set():
            self.run_once()
            # wait روی Event: توقف سرویس بلافاصله جواب می‌دهد و لازم نیست
            # تا پایان sleep صبر کنیم.
            if self._stop_event.wait(self.config.check_interval_seconds):
                break

        self.status.state = "stopped"
        self.status.write()
        logger.info("حلقه‌ی بهینه‌سازی متوقف شد.")


def _uptime_text(started_at: str | None) -> str:
    if not started_at:
        return "?"
    try:
        started = dt.datetime.fromisoformat(started_at)
    except ValueError:
        return "?"
    delta = dt.datetime.now() - started
    hours, remainder = divmod(int(delta.total_seconds()), 3600)
    minutes, _ = divmod(remainder, 60)
    return f"{hours}h{minutes:02d}m"


__all__ = ["HEARTBEAT_EVERY_N_CYCLES", "OptimizerRunner"]
