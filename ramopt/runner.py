# -*- coding: utf-8 -*-
"""حلقه‌ی اجرای مشترک بین سرویس ویندوز، تسک زمان‌بندی و حالت کنسول.

قبلاً حلقه در دو جا (کنسول و سرویس) تکرار شده بود و رفتارشان کمی متفاوت؛
این‌جا یک‌بار نوشته شده و هر دو از آن استفاده می‌کنند.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import threading

from ramopt import memory as memory_mod
from ramopt import paths, win32
from ramopt.config import Config, load_config
from ramopt.engine import Action, CycleResult, OptimizerEngine
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

    def apply_config(self, config: Config) -> None:
        """اعمال پیکربندی جدید بدون ری‌استارت (از طریق پوشه‌ی command)."""
        old = self.config
        self.config = config
        self.engine.config = config
        if config.trigger_percent != old.trigger_percent or (
            config.reset_percent != old.reset_percent
        ):
            # آستانه‌ها عوض شده‌اند → حالت قبلی معنی ندارد
            self.engine._reset_state()
        logger.info(
            "پیکربندی جدید اعمال شد | آستانه %d%% (ریست %d%%) | فاصله %d ثانیه | بحرانی %d%%",
            config.trigger_percent,
            config.reset_percent,
            config.check_interval_seconds,
            config.sustained_trigger_percent,
        )
        self.status.extra["config_revision"] = self.status.extra.get("config_revision", 0) + 1
        self.status.write()

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
    def run_once(self) -> CycleResult | None:
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
            return None

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
        self.status.extra["critical"] = result.critical
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
        return result

    # -- پوشه‌ی command: pause / resume / reload از بیرون -----------------
    def _command_path(self) -> str:
        return os.path.join(paths.data_dir(), "command.json")

    def _poll_command(self) -> None:
        """اجرای دستورهای بیرونی (``ramopt pause`` / ``resume`` / ``reload``).

        چرا فایل و نه IPC؟ هر روش IPC یک پنجره‌ی امنیتی روی یک سرویس SYSTEM
        باز می‌کند (named pipe یا TCP). یک فایل در ProgramData که فقط
        Administrators می‌توانند بنویسند، ساده‌تر و امن‌تر است و پس از اجرا
        حذف می‌شود.
        """
        path = self._command_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, encoding="utf-8") as handle:
                payload = json.load(handle)
            command = str(payload.get("command", "")).strip().lower()
        except (OSError, ValueError):
            command = ""
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

        if command == "pause":
            self.pause("درخواست از خط فرمان")
        elif command == "resume":
            self.resume()
        elif command in ("reload", "config"):
            config, issues = load_config()
            for issue in issues:
                logger.warning("پیکربندی: [%s] %s → %s", issue.key, issue.value, issue.message)
            self.apply_config(config)
        elif command:
            logger.warning("دستور ناشناخته در command.json: %r", command)
        else:
            logger.warning("command.json بدون کلید command — نادیده گرفته شد.")

    def next_interval(self) -> int:
        """فاصله تا بررسی بعدی (ثانیه).

        عادی: ``check_interval_seconds`` (پیش‌فرض ۶۰ = هر یک دقیقه).
        بحرانی: ``critical_poll_seconds`` (پیش‌فرض ۵) تا اگر وضعیت بدتر شد
        منتظر یک دقیقه‌ی بعد نمانیم.
        """
        if self.engine.critical and self.config.critical_poll_seconds > 0:
            return min(self.config.critical_poll_seconds, self.config.check_interval_seconds)
        return self.config.check_interval_seconds

    def _memory_is_critical(self) -> bool:
        """آیا همین حالا مصرف از آستانه‌ی بحرانی گذشته است؟

        فقط یک خواندن سبک GlobalMemoryStatusEx — بدون تصمیم، بدون پاک‌سازی.
        """
        try:
            snapshot = self.api.memory_snapshot()
        except Exception:  # pragma: no cover - دفاعی
            return False
        if snapshot is None:
            return False
        return snapshot.used_percent >= self.config.sustained_trigger_percent

    def wait_next(self, seconds: int) -> bool:
        """خواب بین دو چرخه، ولی با بیدار شدن زودهنگام اگر رم بحرانی شد.

        چرا؟ «فوراً» باید واقعاً فوری باشد: اگر در ثانیه‌ی ۳ یک برنامه ۳ گیگ
        بگیرد، نباید تا ثانیه‌ی ۶۰ صبر کنیم. حداکثر هر
        ``critical_probe_seconds`` (پیش‌فرض ۲) ثانیه یک خواندن بسیار ارزان
        انجام می‌شود؛ به‌محض عبور از آستانه‌ی بحرانی بیدار می‌شویم.

        خروجی ``True`` یعنی باید حلقه خارج شود (توقف درخواست شده).
        """
        if self._stop_event.is_set():
            return True
        probe = self.config.critical_probe_seconds
        if probe <= 0:
            return self._stop_event.wait(seconds)

        import time

        deadline = time.monotonic() + seconds
        while not self._stop_event.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            # بیشتر از یک probe صبر نکن، و هرگز از باقی‌مانده بیشتر
            if self._stop_event.wait(min(probe, remaining)):
                return True
            if self._memory_is_critical():
                logger.warning(
                    "حافظه در فاصله‌ی بین دو چرخه بحرانی شد (≥%d%%) — "
                    "چرخه‌ی بعدی همین حالا اجرا می‌شود (بدون انتظار برای %d ثانیه).",
                    self.config.sustained_trigger_percent,
                    seconds,
                )
                return False
        return True

    def run_forever(self) -> None:
        """حلقه‌ی اصلی. با ``stop()`` بلافاصله خارج می‌شود (نه با خواب طولانی)."""
        self.prepare()
        logger.info(
            "حلقه‌ی بهینه‌سازی شروع شد | بررسی عادی هر %d ثانیه | "
            "در وضعیت بحرانی (≥%d%%) هر %d ثانیه (پایش هر %d ثانیه)",
            self.config.check_interval_seconds,
            self.config.sustained_trigger_percent,
            self.config.critical_poll_seconds,
            self.config.critical_probe_seconds,
        )

        while not self._stop_event.is_set():
            self._poll_command()
            self.run_once()
            # wait روی Event: توقف سرویس بلافاصله جواب می‌دهد؛ و در وضعیت
            # بحرانی/نزدیک بحرانی، بیدار شدن زودهنگام.
            if self.wait_next(self.next_interval()):
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
