# -*- coding: utf-8 -*-
"""اندازه‌گیری و عملیات واقعی روی حافظه.

اینجا هیچ تصمیم‌گیری‌ای وجود ندارد؛ فقط «انجام بده و اندازه بگیر».
تصمیم‌ها در :mod:`ramopt.engine` هستند. همین جداسازی باعث می‌شود هر دو
بخش بدون ویندوز (با mock) قابل تست باشند.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from ramopt import win32
from ramopt.config import Config
from ramopt.version import SERVICE_NAME

logger = logging.getLogger("RamOptimizer")

MB = 1024 * 1024

#: حداقل دسترسی لازم برای EmptyWorkingSet طبق مستندات مایکروسافت:
#: «PROCESS_QUERY_INFORMATION یا PROCESS_QUERY_LIMITED_INFORMATION» + «PROCESS_SET_QUOTA».
#:
#: نکته‌ی فنی مهم: پیاده‌سازی سیستمی EmptyWorkingSet علاوه بر این‌ها
#: ``PROCESS_SET_INFORMATION`` هم می‌خواهد (چون ``NtSetInformationProcess`` را
#: صدا می‌زند). نبودنش باعث می‌شود برنامه بی‌صدا هیچ پروسه‌ای را پاک نکند —
#: دقیقاً همان شکلی که بعضی ابزارهای «رم کلینر» تقلبی رفتار می‌کنند. پس
#: دسترسی را اضافه می‌کنیم؛ قوی‌تر از حد لازم است ولی بزرگ‌ترین نیست
#: (``PROCESS_ALL_ACCESS`` را نمی‌گیریم).
TRIM_ACCESS = (
    win32.PROCESS_QUERY_LIMITED_INFORMATION
    | win32.PROCESS_SET_QUOTA
    | win32.PROCESS_SET_INFORMATION
)


# ----------------------------------------------------------------------------
# داده‌های خام
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    working_set_bytes: int


@dataclass(frozen=True)
class Reading:
    """وضعیت لحظه‌ای سیستم."""

    snapshot: win32.MemorySnapshot | None
    #: حجم Standby List (کش) در لحظه‌ی اندازه‌گیری
    standby_total_bytes: int | None
    process_count: int

    @property
    def used_percent(self) -> float:
        return self.snapshot.used_percent if self.snapshot else 0.0

    @property
    def available_mb(self) -> float:
        return self.snapshot.available_mb if self.snapshot else 0.0

    @property
    def commit_percent(self) -> float:
        return self.snapshot.commit_percent if self.snapshot else 0.0

    @property
    def standby_mb(self) -> float | None:
        return None if self.standby_total_bytes is None else self.standby_total_bytes / MB


@dataclass
class TrimReport:
    """نتیجه‌ی پاک‌سازی Working Setها — به تفکیک علت."""

    considered: int = 0  #: پروسه‌هایی که واقعاً برای trim انتخاب شدند
    trimmed: int = 0  #: EmptyWorkingSet موفق
    denied: int = 0  #: OpenProcess ناموفق (دسترسی)
    skipped_small: int = 0  #: کوچک‌تر از آستانه
    skipped_excluded: int = 0  #: در لیست استثنا
    failed: int = 0  #: EmptyWorkingSet ناموفق
    freed_bytes: int = 0  #: مجموع کاهش Working Set
    biggest: list[tuple[str, int]] = field(default_factory=list)  #: (نام, بایت) بزرگ‌ترین‌ها
    error: str = ""

    @property
    def freed_mb(self) -> float:
        return self.freed_bytes / MB

    def as_dict(self) -> dict[str, object]:
        return {
            "considered": self.considered,
            "trimmed": self.trimmed,
            "denied": self.denied,
            "skipped_small": self.skipped_small,
            "skipped_excluded": self.skipped_excluded,
            "failed": self.failed,
            "freed_mb": round(self.freed_mb, 1),
            "biggest": [{"name": name, "mb": round(size / MB, 1)} for name, size in self.biggest],
        }


@dataclass
class PurgeReport:
    attempted: bool = False
    purged: bool = False
    skipped_reason: str = ""
    error: str = ""
    standby_before_bytes: int | None = None
    standby_after_bytes: int | None = None

    @property
    def standby_freed_mb(self) -> float:
        if self.standby_before_bytes is None or self.standby_after_bytes is None:
            return 0.0
        return max(0, self.standby_before_bytes - self.standby_after_bytes) / MB

    def as_dict(self) -> dict[str, object]:
        return {
            "attempted": self.attempted,
            "purged": self.purged,
            "skipped_reason": self.skipped_reason,
            "error": self.error,
            "standby_before_mb": None
            if self.standby_before_bytes is None
            else round(self.standby_before_bytes / MB, 1),
            "standby_after_mb": None
            if self.standby_after_bytes is None
            else round(self.standby_after_bytes / MB, 1),
            "standby_freed_mb": round(self.standby_freed_mb, 1),
        }


# ----------------------------------------------------------------------------
# تأمین‌کننده‌ی فهرست پروسه‌ها
# ----------------------------------------------------------------------------


class ProcessProvider:
    """رابط پیش‌فرض: هر شیئی که این دو متد را داشته باشد کار می‌کند."""

    def list_processes(self) -> list[ProcessInfo]:  # pragma: no cover - انتزاعی
        raise NotImplementedError

    def process_name(self, pid: int) -> str | None:  # pragma: no cover - انتزاعی
        raise NotImplementedError


class PsutilProcessProvider(ProcessProvider):
    """پیاده‌سازی واقعی با psutil (کراس‌پلتفرم، برای تست هم مفید است)."""

    def list_processes(self) -> list[ProcessInfo]:
        import psutil

        result: list[ProcessInfo] = []
        # psutil.process_iter با attrs فقط اطلاعات لازم را می‌خواند و برای
        # پروسه‌هایی که موقع پیمایش تمام می‌شوند خطا نمی‌دهد.
        for proc in psutil.process_iter(["pid", "name", "memory_info"]):
            try:
                info = proc.info
                memory = info.get("memory_info")
                ws = int(getattr(memory, "rss", 0) or 0)
                result.append(
                    ProcessInfo(
                        pid=int(info["pid"]),
                        name=str(info.get("name") or ""),
                        working_set_bytes=ws,
                    )
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except (TypeError, ValueError, KeyError):
                continue
        return result

    def process_name(self, pid: int) -> str | None:
        import psutil

        try:
            return psutil.Process(pid).name()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None
        except Exception:  # pragma: no cover - دفاعی
            return None


# ----------------------------------------------------------------------------
# اندازه‌گیری
# ----------------------------------------------------------------------------


def measure(api: "win32.Win32Api", provider: ProcessProvider | None = None) -> Reading:
    """خواندن وضعیت حافظه + تعداد پروسه‌ها (برای لاگ و status.json)."""
    snapshot = api.memory_snapshot()
    standby = api.standby_bytes()
    process_count = len(provider.list_processes()) if provider is not None else 0
    return Reading(snapshot=snapshot, standby_total_bytes=standby, process_count=process_count)


# ----------------------------------------------------------------------------
# پاک‌سازی Working Setها
# ----------------------------------------------------------------------------


def trim_working_sets(
    api: "win32.Win32Api",
    provider: ProcessProvider,
    config: Config,
    own_pid: int | None = None,
) -> TrimReport:
    """خالی کردن Working Set پروسه‌های واجد شرایط.

    ترتیب کار (بهینه‌سازی نسبت به نسخه‌ی قبلی):

    1. فهرست پروسه‌ها یک‌بار خوانده می‌شود؛
    2. پروسه‌های کوچک‌تر از ``min_process_ws_mb`` و مستثناها حذف می‌شوند؛
       (روی trim یک پروسه‌ی ۲ مگابایتی هیچ سودی ندارد و فقط syscall است)
    3. بقیه بر اساس حجم نزولی مرتب و تا سقف ``max_processes`` انتخاب می‌شوند؛
    4. برای هر پروسه، قبل و بعد از EmptyWorkingSet حجم Working Set اندازه‌گیری
       می‌شود تا عدد «آزادشده» واقعی باشد نه تخمینی.
    """
    report = TrimReport()
    if not api.available:
        report.error = "Windows API is not available"
        return report

    me = os.getpid() if own_pid is None else own_pid
    min_ws_bytes = max(0, config.min_process_ws_mb) * MB

    try:
        processes = provider.list_processes()
    except Exception as exc:  # pragma: no cover - دفاعی
        report.error = f"could not read the process list: {exc}"
        logger.exception(report.error)
        return report

    own_names = {SERVICE_NAME.lower() + ".exe", "ramopt.exe", "python.exe"}
    candidates: list[ProcessInfo] = []
    for proc in processes:
        if proc.pid <= 4 or proc.pid == me:
            continue
        # از پاک کردن خودمان (سرویس یا نسخه‌ی کنسولی در حال اجرا) و
        # والدمان (مثلاً pythonservice.exe) دست نگه می‌داریم.
        if proc.name and proc.name.lower() in own_names and proc.working_set_bytes > 0:
            continue
        if config.is_excluded(proc.name):
            report.skipped_excluded += 1
            continue
        if proc.working_set_bytes and proc.working_set_bytes < min_ws_bytes:
            report.skipped_small += 1
            continue
        candidates.append(proc)

    # بزرگ‌ترین‌ها اول: بیشترین سود با کمترین تعداد فراخوانی
    candidates.sort(key=lambda p: p.working_set_bytes, reverse=True)
    if config.max_processes and len(candidates) > config.max_processes:
        candidates = candidates[: config.max_processes]

    report.considered = len(candidates)
    biggest: list[tuple[str, int]] = []

    for proc in candidates:
        handle = api.open_process(proc.pid, TRIM_ACCESS)
        if not handle:
            report.denied += 1
            continue
        try:
            before = api.working_set_size(handle)
            if not before:
                before = proc.working_set_bytes
            if before and before < min_ws_bytes:
                report.skipped_small += 1
                continue
            if api.empty_working_set(handle):
                after = api.working_set_size(handle)
                freed = max(0, int(before) - int(after))
                report.trimmed += 1
                report.freed_bytes += freed
                if freed:
                    biggest.append((proc.name or f"pid {proc.pid}", freed))
            else:
                report.failed += 1
        except OSError as exc:  # دسترسی یا پروسه‌ی از بین رفته
            report.failed += 1
            logger.debug("could not trim %s: %s", proc.name or proc.pid, exc)
        finally:
            api.close_handle(handle)

    biggest.sort(key=lambda item: item[1], reverse=True)
    report.biggest = biggest[:5]
    return report


# ----------------------------------------------------------------------------
# Standby List
# ----------------------------------------------------------------------------


def purge_standby_list(
    api: "win32.Win32Api", config: Config, current_available_mb: float | None = None
) -> PurgeReport:
    """خالی کردن Standby List — اما فقط وقتی واقعاً لازم است.

    نسخه‌ی قبلی همیشه و بلافاصله بعد از trim کش را خالی می‌کرد. کش عمداً
    برای سرعت سیستم نگه داشته می‌شود؛ اگر بعد از trim به‌اندازه‌ی کافی RAM
    آزاد شده باشد، خالی کردنش فقط سیستم را کند می‌کند.
    """
    report = PurgeReport()
    if not config.purge_standby_list:
        report.skipped_reason = "disabled in the configuration"
        return report

    if (
        current_available_mb is not None
        and config.min_free_mb_after_trim > 0
        and current_available_mb >= config.min_free_mb_after_trim
    ):
        report.skipped_reason = (
            f"already free after trimming, {current_available_mb:.0f} MB "
            f"(min_free_mb_after_trim: {config.min_free_mb_after_trim})"
        )
        return report

    report.attempted = True
    report.standby_before_bytes = api.standby_bytes()
    ok, error = api.memory_list_command(win32.MEMORY_PURGE_STANDBY_LIST)
    report.purged = ok
    report.error = error
    if ok:
        report.standby_after_bytes = api.standby_bytes()
    return report


def flush_modified_list(api: "win32.Win32Api", config: Config) -> tuple[bool, str]:
    """نوشتن صفحات تغییرکرده روی دیسک (به‌طور پیش‌فرض خاموش است)."""
    if not config.flush_modified_list:
        return False, ""
    return api.memory_list_command(win32.MEMORY_FLUSH_MODIFIED_LIST)


__all__ = [
    "MB",
    "ProcessInfo",
    "ProcessProvider",
    "PsutilProcessProvider",
    "PurgeReport",
    "Reading",
    "TrimReport",
    "flush_modified_list",
    "measure",
    "purge_standby_list",
    "trim_working_sets",
]
