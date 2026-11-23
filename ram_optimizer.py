# -*- coding: utf-8 -*-
"""
================================================================================
 RamOptimizer Core — هسته‌ی آزادسازی خودکار حافظه‌ی RAM
================================================================================
 این ماژول دقیقاً همان کاری را می‌کند که برنامه‌های معروف «بهینه‌سازی رم» انجام
 می‌دهند (مثل Wise Memory Optimizer یا گزینه‌ی Empty Standby List در RAMMap
 مایکروسافت):

   1) EmptyWorkingSet :
      به ویندوز می‌گوید صفحات حافظه‌ایِ هر پروسه که مدتی است استفاده نشده‌اند
      را از Working Set آن پروسه خارج کند. این دقیقاً همان «حافظه‌ای است که
      برنامه اشغال کرده ولی دیگر استفاده نمی‌کند».

   2) NtSetSystemInformation(MemoryPurgeStandbyList) :
      لیست Standby (حافظه‌ی کشِ آزادشده) را هم خالی می‌کند تا واقعاً به
      حافظه‌ی آزاد سیستم اضافه شود.

 این ماژول دو کاربرد دارد:
   - اجرای مستقیم برای تست (حالت کنسول):   python ram_optimizer.py
   - استفاده توسط سرویس ویندوز (ram_optimizer_service.py)
================================================================================
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from ctypes import wintypes
from logging.handlers import RotatingFileHandler

import psutil

# ============================================================================
#  ثابت‌های پیکربندی
#  (برنامه عمداً هیچ فایل تنظیمات یا رابط کاربری ندارد؛ اگر روزی خواستید رفتار
#  را تغییر دهید فقط همین مقادیر را عوض کنید و دوباره exe بسازید)
# ============================================================================

CHECK_INTERVAL_SECONDS   = 60       # هر چند ثانیه یک‌بار وضعیت رم بررسی شود
MEMORY_THRESHOLD_PERCENT = 55       # وقتی مصرف رم >= این درصد شد، پاک‌سازی انجام شود
PURGE_STANDBY_LIST       = True     # خالی کردن Standby List (کش حافظه) هم انجام شود؟
FLUSH_MODIFIED_LIST      = False    # صفحات تغییرکرده هم روی دیسک نوشته شوند؟ (پیش‌فرض خاموش)
LOG_MAX_BYTES            = 2 * 1024 * 1024   # حداکثر حجم هر فایل لاگ
LOG_BACKUP_COUNT         = 3                 # تعداد نسخه‌های چرخشی لاگ

LOGGER_NAME = "RamOptimizer"
logger = logging.getLogger(LOGGER_NAME)
logger.addHandler(logging.NullHandler())

# ============================================================================
#  آماده‌سازی DLL های ویندوز
# ============================================================================

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi    = ctypes.WinDLL("psapi",    use_last_error=True)
ntdll    = ctypes.WinDLL("ntdll",    use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

# --- امضای توابع (برای جلوگیری از خرابی handle ها در ویندوز ۶۴ بیتی) ---
kernel32.GetCurrentProcess.restype  = wintypes.HANDLE
kernel32.GetCurrentProcess.argtypes = []

kernel32.OpenProcess.restype  = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

kernel32.CloseHandle.restype  = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

psapi.EmptyWorkingSet.restype  = wintypes.BOOL
psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]

ntdll.NtSetSystemInformation.restype  = wintypes.LONG   # NTSTATUS
ntdll.NtSetSystemInformation.argtypes = [wintypes.INT, wintypes.LPVOID, wintypes.ULONG]

# --- ثابت‌های API ---
PROCESS_SET_QUOTA                 = 0x0100
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY             = 0x0008
SE_PRIVILEGE_ENABLED    = 0x00000002
ERROR_SUCCESS           = 0

SYSTEM_MEMORY_LIST_INFORMATION = 0x0050   # SystemInformationClass = 80
MEMORY_FLUSH_MODIFIED_LIST     = 3
MEMORY_PURGE_STANDBY_LIST      = 4

SYSTEM_PIDS = {0, 4}   # System Idle Process و System — این‌ها را دست نمی‌زنیم

PRIVILEGES_NEEDED = (
    "SeDebugPrivilege",               # باز کردن همه‌ی پروسه‌ها
    "SeProfileSingleProcessPrivilege",# لازم برای خالی کردن Standby List
    "SeIncreaseQuotaPrivilege",       # برای دسترسی کامل‌تر به کوئوتای پروسه‌ها
)


# ============================================================================
#  ساختارهای موردنیاز AdjustTokenPrivileges
# ============================================================================

class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]


class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", wintypes.DWORD),
                ("Privileges", LUID_AND_ATTRIBUTES * 1)]


advapi32.OpenProcessToken.restype  = wintypes.BOOL
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                      ctypes.POINTER(wintypes.HANDLE)]
advapi32.LookupPrivilegeValueW.restype  = wintypes.BOOL
advapi32.LookupPrivilegeValueW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                           ctypes.POINTER(LUID)]
advapi32.AdjustTokenPrivileges.restype  = wintypes.BOOL
advapi32.AdjustTokenPrivileges.argtypes = [wintypes.HANDLE, wintypes.BOOL,
                                           ctypes.POINTER(TOKEN_PRIVILEGES),
                                           wintypes.DWORD, wintypes.LPVOID,
                                           wintypes.LPVOID]


def enable_privilege(privilege_name: str) -> bool:
    """یک اختیار (Privilege) ویندوز را برای پروسه‌ی فعلی فعال می‌کند."""
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(),
                                     TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
                                     ctypes.byref(token)):
        return False
    try:
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, privilege_name, ctypes.byref(luid)):
            return False
        tp = TOKEN_PRIVILEGES()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
        ok = advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(tp),
                                            0, None, None)
        err = ctypes.get_last_error()
        return bool(ok) and err == ERROR_SUCCESS
    finally:
        kernel32.CloseHandle(token)


def enable_all_privileges() -> None:
    """فعال‌سازی اختیارهای لازم؛ در صورت نبود دسترسی ادمین فقط هشدار می‌دهد."""
    for name in PRIVILEGES_NEEDED:
        if enable_privilege(name):
            logger.debug("اختیار %s فعال شد.", name)
        else:
            logger.warning(
                "اختیار %s فعال نشد — برنامه احتمالاً بدون دسترسی Administrator "
                "اجرا شده؛ پاک‌سازی فقط روی بخشی از حافظه اثر می‌گذارد.", name)


# ============================================================================
#  لاگ
# ============================================================================

def _log_file_path() -> str | None:
    """مسیر فایل لاگ: اول ProgramData، در غیر این صورت کنار برنامه."""
    candidates = []
    program_data = os.environ.get("ProgramData")
    if program_data:
        candidates.append(os.path.join(program_data, "RamOptimizer"))
    base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.abspath(__file__)))
    candidates.append(base)

    for directory in candidates:
        try:
            os.makedirs(directory, exist_ok=True)
            path = os.path.join(directory, "ram_optimizer.log")
            with open(path, "a", encoding="utf-8"):
                pass
            return path
        except OSError:
            continue
    return None


def setup_logging() -> None:
    """راه‌اندازی لاگ (فایل چرخشی + کنسول). فقط یک‌بار اجرا می‌شود."""
    if getattr(setup_logging, "_done", False):
        return
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    path = _log_file_path()
    if path:
        file_handler = RotatingFileHandler(path, maxBytes=LOG_MAX_BYTES,
                                           backupCount=LOG_BACKUP_COUNT,
                                           encoding="utf-8")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    try:
        if sys.stderr is not None:
            console = logging.StreamHandler()
            console.setFormatter(fmt)
            logger.addHandler(console)
    except Exception:
        pass
    setup_logging._done = True


# ============================================================================
#  قلب برنامه: آزادسازی حافظه
# ============================================================================

def trim_all_working_sets() -> int:
    """
    EmptyWorkingSet را روی تمام پروسه‌های سیستم صدا می‌زند.
    (کار برنامه‌های RAM Optimizer: تخلیه‌ی رمی که برنامه‌ها گرفته‌اند ولی
    دیگر استفاده نمی‌کنند.)
    خروجی: تعداد پروسه‌هایی که با موفقیت پاک‌سازی شدند.
    """
    own_pid = os.getpid()
    trimmed = 0
    for proc in psutil.process_iter():
        pid = proc.pid
        if pid in SYSTEM_PIDS or pid == own_pid:
            continue
        handle = None
        try:
            handle = kernel32.OpenProcess(
                PROCESS_SET_QUOTA | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                continue
            if psapi.EmptyWorkingSet(handle):
                trimmed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        except Exception:
            continue
        finally:
            if handle:
                kernel32.CloseHandle(handle)
    return trimmed


def _memory_list_command(command: int) -> bool:
    """اجرای یک دستور روی Memory List ویندوز (NtSetSystemInformation)."""
    value = wintypes.ULONG(command)
    status = ntdll.NtSetSystemInformation(SYSTEM_MEMORY_LIST_INFORMATION,
                                          ctypes.byref(value),
                                          ctypes.sizeof(value))
    return status == 0   # STATUS_SUCCESS


def purge_standby_list() -> bool:
    """خالی کردن Standby List — معادل «Empty Standby List» در RAMMap مایکروسافت."""
    return _memory_list_command(MEMORY_PURGE_STANDBY_LIST)


def flush_modified_list() -> bool:
    """نوشتن صفحات تغییرکرده روی دیسک (اختیاری — پیش‌فرض خاموش است)."""
    return _memory_list_command(MEMORY_FLUSH_MODIFIED_LIST)


def check_and_optimize(force: bool = False) -> bool:
    """
    وضعیت رم را بررسی می‌کند و اگر به آستانه رسیده بود، پاک‌سازی انجام می‌دهد.
    خروجی: True اگر پاک‌سازی انجام شده باشد.
    """
    mem_before = psutil.virtual_memory()

    if not force and mem_before.percent < MEMORY_THRESHOLD_PERCENT:
        logger.debug("مصرف رم %.1f%% است (آستانه: %d%%) — نیازی به پاک‌سازی نیست.",
                     mem_before.percent, MEMORY_THRESHOLD_PERCENT)
        return False

    trimmed = trim_all_working_sets()
    purged  = purge_standby_list() if PURGE_STANDBY_LIST else False
    flushed = flush_modified_list() if FLUSH_MODIFIED_LIST else False

    mem_after = psutil.virtual_memory()
    freed_mb = max(0, mem_before.used - mem_after.used) / (1024 * 1024)

    logger.info(
        "پاک‌سازی انجام شد | پروسه‌های پاک‌شده: %d | Standby List: %s | "
        "رم: %.1f%% ← %.1f%% | آزادشده: حدود %.0f مگابایت",
        trimmed,
        "OK" if purged else ("-" if not PURGE_STANDBY_LIST else "ناموفق"),
        mem_before.percent, mem_after.percent, freed_mb)
    if flushed:
        logger.debug("Modified List هم flush شد.")
    return True


# ============================================================================
#  اجرای مستقیم (حالت کنسول — برای تست بدون نصب سرویس)
# ============================================================================

def run_console() -> int:
    setup_logging()
    enable_all_privileges()

    if "--once" in sys.argv:
        logger.info("اجرای یک‌باره (تست) — پاک‌سازی بدون توجه به آستانه...")
        check_and_optimize(force=True)
        return 0

    logger.info("حالت کنسول — بررسی هر %d ثانیه | آستانه: %d%%",
                CHECK_INTERVAL_SECONDS, MEMORY_THRESHOLD_PERCENT)
    logger.info("برای توقف Ctrl+C بزنید.")
    try:
        while True:
            try:
                check_and_optimize()
            except Exception:
                logger.exception("خطای غیرمنتظره در چرخه بهینه‌سازی.")
            time.sleep(CHECK_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        logger.info("توقف توسط کاربر.")
    return 0


if __name__ == "__main__":
    sys.exit(run_console())
