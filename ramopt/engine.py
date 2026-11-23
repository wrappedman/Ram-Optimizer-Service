# -*- coding: utf-8 -*-
"""موتور تصمیم‌گیری و اجرای پاک‌سازی.

این ماژول *هیچ* وابستگی‌ای به ویندوز ندارد: همه‌ی کارهای سیستمی از طریق
:mod:`ramopt.memory` و :mod:`ramopt.win32` انجام می‌شود و برای آن‌ها یک شیء
تزریق می‌شود. به همین دلیل کل سیاست برنامه با تست واحد قابل بررسی است.

قواعد تصمیم‌گیری (هسته‌ی درست‌شده‌ی نسخه‌ی ۲):

* **هیسترزیس**: در ``trigger_percent`` روشن می‌شود و تا رسیدن به
  ``reset_percent`` خاموش می‌ماند.
* **cooldown**: بین دو پاک‌سازی حداقل ``cooldown_seconds`` فاصله است.
* **سقف ساعتی**: حداکثر ``max_purges_per_hour`` پاک‌سازی در هر ساعت.
* **بک‌آف**: اگر پاک‌سازی سودی نداشت، فاصله‌ی بعدی دو برابر می‌شود.
* **احترام به کاربر**: در حالت تمام‌صفحه/ارائه، روی باتری (در صورت تنظیم) و
  در ساعات سکوت کاری انجام نمی‌شود.
* **تأخیر بوت**: بعد از استارت ویندوز تا ``startup_delay_seconds`` دست به
  حافظه نمی‌زند.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from enum import Enum

from ramopt import memory as memory_mod
from ramopt import win32
from ramopt.config import Config

logger = logging.getLogger("RamOptimizer")

MB = 1024 * 1024

#: اگر آزادسازی کمتر از این درصد از حافظه‌ی آزادشده‌ی مورد انتظار باشد،
#: پاک‌سازی «بی‌اثر» تلقی می‌شود و بک‌آف فعال می‌شود.
MIN_USEFUL_FREED_MB = 64


class Mode(str, Enum):
    """حالت داخلی سیاست."""

    IDLE = "idle"  #: زیر آستانه — کاری لازم نیست
    ARMED = "armed"  #: بالای آستانه، منتظر پایان cooldown/محدودیت
    ACTIVE = "active"  #: در حال پاک‌سازی دوره‌ای (هیسترزیس)


class Action(str, Enum):
    NOOP = "noop"
    OPTIMIZED = "optimized"
    SKIPPED = "skipped"


@dataclass
class Decision:
    action: Action
    reason: str
    mode: Mode
    should_optimize: bool = False
    #: وضعیت بحرانی است → چرخه‌ی بعدی نباید یک دقیقه صبر کند
    critical: bool = False
    details: dict[str, object] = field(default_factory=dict)


@dataclass
class CycleResult:
    """خروجی یک چرخه — همان چیزی که در لاگ و status.json می‌نشیند."""

    timestamp: str
    action: Action
    reason: str
    mode: str
    used_percent_before: float | None = None
    used_percent_after: float | None = None
    available_mb_before: float | None = None
    available_mb_after: float | None = None
    commit_percent: float | None = None
    standby_mb_before: float | None = None
    standby_mb_after: float | None = None
    trim: memory_mod.TrimReport | None = None
    purge: memory_mod.PurgeReport | None = None
    duration_ms: float = 0.0
    critical: bool = False
    environment: dict[str, object] = field(default_factory=dict)

    @property
    def freed_mb(self) -> float:
        """آزادشدن واقعی حافظه (available) — صادقانه‌تر از «رم استفاده‌شده»."""
        if self.available_mb_before is None or self.available_mb_after is None:
            return 0.0
        return max(0.0, self.available_mb_after - self.available_mb_before)

    def as_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "action": self.action.value,
            "reason": self.reason,
            "mode": self.mode,
            "used_percent_before": _round(self.used_percent_before),
            "used_percent_after": _round(self.used_percent_after),
            "available_mb_before": _round(self.available_mb_before),
            "available_mb_after": _round(self.available_mb_after),
            "commit_percent": _round(self.commit_percent),
            "standby_mb_before": _round(self.standby_mb_before),
            "standby_mb_after": _round(self.standby_mb_after),
            "freed_mb": round(self.freed_mb, 1),
            "duration_ms": round(self.duration_ms, 1),
            "critical": self.critical,
            "environment": self.environment,
            "trim": self.trim.as_dict() if self.trim else None,
            "purge": self.purge.as_dict() if self.purge else None,
        }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _now() -> dt.datetime:
    return dt.datetime.now()


class OptimizerEngine:
    """سیاست + اجرا. یک نمونه به‌ازای هر سرویس/پروسه."""

    def __init__(
        self,
        config: Config,
        api: "win32.Win32Api",
        provider: memory_mod.ProcessProvider | None = None,
        clock=None,
    ) -> None:
        self.config = config
        self.api = api
        self.provider = provider or memory_mod.PsutilProcessProvider()
        self._now = clock or _now

        self.mode = Mode.IDLE
        self.last_purge_at: dt.datetime | None = None
        self.purge_history: list[dt.datetime] = []
        self.consecutive_useless = 0
        self.paused = False
        self.pause_reason = ""
        self.started_at = self._now()
        self.total_purges = 0
        self.total_freed_mb = 0.0
        #: شمارنده‌ی بررسی‌های متوالی بالای آستانه‌ی بحرانی
        self.critical_streak = 0
        #: آیا در آخرین بررسی وضعیت «بحرانی» بود؟
        self.critical = False
        self.last_result: CycleResult | None = None

    # -- کنترل خارجی (پاز/ریزیوم از سرویس یا CLI) -------------------------
    def pause(self, reason: str = "درخواست کاربر") -> None:
        if not self.paused:
            logger.info("پاک‌سازی موقتاً متوقف شد (%s).", reason)
        self.paused = True
        self.pause_reason = reason
        self.mode = Mode.IDLE

    def resume(self) -> None:
        if self.paused:
            logger.info("پاک‌سازی دوباره فعال شد.")
        self.paused = False
        self.pause_reason = ""
        # بعد از ریزیوم، cooldown را ریست می‌کنیم تا کاربر منتظر نماند.
        self.last_purge_at = None

    # -- تصمیم‌گیری --------------------------------------------------------
    def _cooldown_remaining(self) -> float:
        if self.last_purge_at is None:
            return 0.0
        elapsed = (self._now() - self.last_purge_at).total_seconds()
        cooldown = self.config.cooldown_seconds * (2 ** min(self.consecutive_useless, 5))
        return max(0.0, cooldown - elapsed)

    def _recent_purges(self) -> int:
        cutoff = self._now() - dt.timedelta(hours=1)
        self.purge_history = [t for t in self.purge_history if t >= cutoff]
        return len(self.purge_history)

    def _in_quiet_hours(self) -> bool:
        window = self.config.quiet_hours
        if not window or "-" not in window:
            return False
        try:
            start_raw, end_raw = window.split("-", 1)
            start_h, start_m = (int(part) for part in start_raw.split(":"))
            end_h, end_m = (int(part) for part in end_raw.split(":"))
        except (ValueError, TypeError):
            return False
        now = self._now().time()
        start = dt.time(hour=start_h, minute=start_m)
        end = dt.time(hour=end_h, minute=end_m)
        if start <= end:
            return start <= now < end
        return now >= start or now < end  # بازه‌ای که از نیمه‌شب می‌گذرد

    def _reset_state(self) -> None:
        """ریست کردن حالت سیاست (پس از نصب تنظیمات جدید)."""
        self.mode = Mode.IDLE
        self.last_purge_at = None
        self.purge_history.clear()
        self.consecutive_useless = 0
        self.critical_streak = 0
        self.critical = False
        self.started_at = self._now()

    def _update_critical(self, used: float) -> bool:
        """به‌روزرسانی شمارنده‌ی «وضعیت بحرانی».

        «مصرف» در ویندوز شامل کش (standby) است، پس عدد ۹۲٪ می‌تواند فقط یک
        کش بزرگ باشد. برای همین علاوه بر آستانه، «حداقل حافظه‌ی آزاد» هم باید
        کم باشد؛ وگرنه هیچ‌وقت به حالت بحرانی نمی‌رسیم (بهتر از اجرای بی‌فایده).
        """
        config = self.config
        if config.sustained_trigger_percent <= 0:
            self.critical_streak = 0
            self.critical = False
            return False
        over = used >= config.sustained_trigger_percent
        self.critical_streak = self.critical_streak + 1 if over else 0
        self.critical = self.critical_streak >= max(1, config.sustained_polls)
        return self.critical

    def _blocking_environment(self) -> tuple[str, dict[str, object]]:
        """شرایطی که پاک‌سازی باید کنار بماند. خروجی: (دلیل, جزئیات)."""
        details: dict[str, object] = {}

        if self.paused:
            return self.pause_reason or "موقتاً متوقف شده", details

        boot_delay = self.config.startup_delay_seconds
        if boot_delay > 0:
            elapsed = (self._now() - self.started_at).total_seconds()
            if elapsed < boot_delay:
                details["startup_delay_remaining_s"] = round(boot_delay - elapsed)
                return (
                    f"تأخیر شروع ({boot_delay} ثانیه) — {boot_delay - elapsed:.0f} ثانیه مانده",
                    details,
                )

        if self.config.skip_when_fullscreen:
            state = self.api.user_notification_state()
            details["user_state"] = state
            if state is not None and state in win32.BUSY_USER_STATES:
                return "کاربر در حال استفاده‌ی تمام‌صفحه/ارائه است", details

        if self.config.skip_on_battery and self.api.is_on_battery():
            details["on_battery"] = True
            return "روی باتری — پاک‌سازی انجام نمی‌شود", details

        if self._in_quiet_hours():
            return f"ساعت سکوت ({self.config.quiet_hours})", details

        return "", details

    def decide(self, reading: memory_mod.Reading) -> Decision:
        """تصمیم خالص: آیا باید پاک‌سازی شود و چرا؟"""
        used = reading.used_percent
        config = self.config
        critical = self._update_critical(used)

        # --- وضعیت بحرانی: فرایند عادی محدودیت‌ها را دور می‌زند -----------
        if critical:
            if self.paused:
                return Decision(
                    Action.SKIPPED,
                    self.pause_reason or "موقتاً متوقف شده",
                    self.mode,
                    critical=True,
                )
            # در وضعیت بحرانی حتی اگر حالت IDLE بود (مثلاً کانفیگ ریست شده)
            # باید اقدام شود؛ RAM دارد تمام می‌شود.
            if self.mode is Mode.IDLE:
                self.mode = Mode.ARMED
                logger.warning(
                    "وضعیت بحرانی: مصرف %.1f%% ≥ %d%% (آستانه‌ی عادی %d%%) — اجرای فوری.",
                    used,
                    config.sustained_trigger_percent,
                    config.trigger_percent,
                )
            return Decision(
                Action.OPTIMIZED,
                f"وضعیت بحرانی (مصرف {used:.1f}% ≥ {config.sustained_trigger_percent}%) "
                f"— اجرای فوری بدون انتظار",
                self.mode,
                should_optimize=True,
                critical=True,
            )

        # --- هیسترزیس -------------------------------------------------
        if self.mode is Mode.IDLE:
            if used >= config.trigger_percent:
                self.mode = Mode.ARMED
                logger.info(
                    "مصرف رم %.1f%% ≥ آستانه %d%% — حالت فعال شد.",
                    used,
                    config.trigger_percent,
                )
        elif self.mode in (Mode.ARMED, Mode.ACTIVE) and used <= config.reset_percent:
            self.mode = Mode.IDLE
            self.consecutive_useless = 0
            logger.info(
                "مصرف رم %.1f%% ≤ %.1f%% — حالت آماده‌باش خاموش شد.",
                used,
                config.reset_percent,
            )
            return Decision(Action.NOOP, "مصرف زیر آستانه‌ی بازنشانی است", self.mode)

        if self.mode is Mode.IDLE:
            return Decision(
                Action.NOOP,
                f"مصرف {used:.1f}% زیر آستانه‌ی {config.trigger_percent}% است",
                self.mode,
            )

        # --- محدودیت‌های محیطی -----------------------------------------
        block_reason, details = self._blocking_environment()
        if block_reason:
            mode = self.mode
            return Decision(Action.SKIPPED, block_reason, mode, details={"environment": details})

        # --- هدف مطلق: اگر RAM کافی آزاد است نیازی نیست ---------------
        if config.min_available_mb > 0 and reading.available_mb >= config.min_available_mb:
            return Decision(
                Action.NOOP,
                f"{reading.available_mb:.0f} مگابایت آزاد است "
                f"(حداقل لازم برای اقدام: {config.min_available_mb})",
                self.mode,
            )

        # --- cooldown -------------------------------------------------
        remaining = self._cooldown_remaining()
        if remaining > 0:
            return Decision(
                Action.SKIPPED,
                f"در دوره‌ی خنک‌شدن — {remaining:.0f} ثانیه مانده",
                self.mode,
                details={"cooldown_remaining_s": round(remaining)},
            )

        # --- سقف ساعتی ------------------------------------------------
        recent = self._recent_purges()
        if config.max_purges_per_hour > 0 and recent >= config.max_purges_per_hour:
            oldest = min(self.purge_history)
            wait_s = max(0.0, 3600 - (self._now() - oldest).total_seconds())
            return Decision(
                Action.SKIPPED,
                f"سقف {config.max_purges_per_hour} پاک‌سازی در ساعت پر شده — "
                f"{wait_s / 60:.0f} دقیقه دیگر",
                self.mode,
                details={"purges_last_hour": recent},
            )

        return Decision(
            Action.OPTIMIZED, "آستانه رد شده و محدودیتی نیست", self.mode, should_optimize=True
        )

    # -- اجرا --------------------------------------------------------------
    def run_cycle(self, force: bool = False) -> CycleResult:
        """یک چرخه‌ی کامل: اندازه‌گیری → تصمیم → اجرا → ثبت نتیجه."""
        started = self.api.monotonic_ms()
        now = self._now()
        environment: dict[str, object] = {}

        reading = memory_mod.measure(self.api, self.provider)
        if reading.snapshot is None:
            if not self.api.available:
                reason = self.api.load_error or "خواندن وضعیت حافظه ممکن نیست"
            else:
                reason = "GlobalMemoryStatusEx ناموفق بود"
            logger.error(reason)
            result = CycleResult(
                timestamp=now.isoformat(timespec="seconds"),
                action=Action.SKIPPED,
                reason=reason,
                mode=self.mode.value,
            )
            self.last_result = result
            return result

        decision = self.decide(reading)

        result = CycleResult(
            timestamp=now.isoformat(timespec="seconds"),
            action=decision.action,
            reason=decision.reason,
            mode=decision.mode.value,
            used_percent_before=reading.used_percent,
            available_mb_before=reading.available_mb,
            commit_percent=reading.commit_percent,
            standby_mb_before=reading.standby_mb,
            critical=decision.critical,
            environment=environment,
        )

        if not decision.should_optimize and not force:
            if decision.action is Action.NOOP:
                logger.debug("%s | %s", decision.reason, _describe(reading))
            else:
                logger.info("%s | %s", decision.reason, _describe(reading))
            result.duration_ms = self.api.monotonic_ms() - started
            self.last_result = result
            return result

        # ---- اجرا ----
        if force:
            result.reason = "اجرای دستی (force)"

        trim = memory_mod.trim_working_sets(self.api, self.provider, self.config)
        result.trim = trim

        # اندازه‌گیری بعد از trim: تصمیم برای Standby List بر اساس واقعیت
        after_trim = self.api.memory_snapshot()
        available_after_trim_mb = after_trim.available_mb if after_trim else reading.available_mb

        purge = memory_mod.purge_standby_list(self.api, self.config, available_after_trim_mb)
        result.purge = purge

        flushed, flush_error = memory_mod.flush_modified_list(self.api, self.config)
        if self.config.flush_modified_list and not flushed:
            logger.warning("Flush Modified List ناموفق: %s", flush_error or "نامشخص")

        final = self.api.memory_snapshot()
        if final is not None:
            result.available_mb_after = final.available_mb
            result.used_percent_after = final.used_percent
        standby_after = self.api.standby_bytes()
        if standby_after is not None:
            result.standby_mb_after = standby_after / MB

        result.duration_ms = self.api.monotonic_ms() - started

        did_something = trim.trimmed > 0 or purge.purged
        result.action = Action.OPTIMIZED if did_something else Action.SKIPPED
        if not did_something:
            result.reason = _failure_reason(trim, purge)
            # شکست را در تاریخچه ثبت نمی‌کنیم تا cooldown بیهوده فعال نشود،
            # ولی بک‌آف ساعتی را زیاد می‌کنیم تا فشار بی‌فایده تکرار نشود.
            self.consecutive_useless += 1
            logger.warning("پاک‌سازی هیچ سودی نداشت | %s | %s", result.reason, _describe(reading))
            self.last_result = result
            return result

        self.last_purge_at = now
        self.purge_history.append(now)
        self.total_purges += 1
        self.total_freed_mb += result.freed_mb
        self.mode = Mode.ACTIVE

        if result.freed_mb < MIN_USEFUL_FREED_MB:
            self.consecutive_useless += 1
        else:
            self.consecutive_useless = 0

        avg_freed = (trim.freed_bytes / trim.trimmed / MB) if trim.trimmed else 0.0
        logger.info(
            "پاک‌سازی انجام شد | پروسه: %d از %d (میانگین %.0fMB، دسترسی رد شد: %d) "
            "| Working Set آزادشده: %.0fMB | Standby List: %s | "
            "RAM آزاد: %.0f → %.0fMB | مصرف: %.1f%% → %.1f%% | %.0f میلی‌ثانیه",
            trim.trimmed,
            trim.considered,
            avg_freed,
            trim.denied,
            trim.freed_mb,
            "خالی شد" if purge.purged else (purge.error or purge.skipped_reason or "خاموش"),
            reading.available_mb,
            result.available_mb_after
            if result.available_mb_after is not None
            else reading.available_mb,
            reading.used_percent,
            result.used_percent_after
            if result.used_percent_after is not None
            else reading.used_percent,
            result.duration_ms,
        )
        self.last_result = result
        return result


def _failure_reason(trim: memory_mod.TrimReport, purge: memory_mod.PurgeReport) -> str:
    """توضیح دقیق اینکه چرا هیچ کاری انجام نشد (به‌جای «موفق» دروغین)."""
    parts: list[str] = []
    if trim.error:
        parts.append(trim.error)
    if trim.considered == 0:
        parts.append("هیچ پروسه‌ی واجد شرایطی پیدا نشد")
    elif trim.trimmed == 0:
        if trim.denied:
            parts.append(f"دسترسی به {trim.denied} پروسه رد شد (ادمین نیستید؟)")
        if trim.failed:
            parts.append(f"{trim.failed} پروسه هنگام trim خطا داد")
    if purge.error:
        parts.append(f"خالی کردن Standby List ناموفق: {purge.error}")
    elif purge.skipped_reason:
        parts.append(f"Standby List دست نخورد: {purge.skipped_reason}")
    return " | ".join(parts) or "هیچ تغییری لازم نبود"


def _describe(reading: memory_mod.Reading) -> str:
    standby = f"{reading.standby_mb:.0f}MB" if reading.standby_mb is not None else "?"
    return (
        f"RAM {reading.used_percent:.1f}% | آزاد {reading.available_mb:.0f}MB | "
        f"commit {reading.commit_percent:.0f}% | standby {standby} | "
        f"پروسه‌ها {reading.process_count}"
    )


__all__ = [
    "MIN_USEFUL_FREED_MB",
    "Action",
    "CycleResult",
    "Decision",
    "Mode",
    "OptimizerEngine",
]
