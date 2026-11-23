# -*- coding: utf-8 -*-
"""لایه‌ی نازک روی Win32.

تمام فراخوانی‌های ``ctypes`` این‌جا متمرکز شده‌اند تا:

* منطق برنامه (``engine``) در تست‌ها با mock قابل اجرا باشد؛
* امضای توابع یک‌جا و درست تعریف شود (``restype``/``argtypes``)؛
* خطاهای NTSTATUS و Win32 با پیام قابل‌فهم برگردند.

روی سیستمی غیر از ویندوز، ماژول با ``available=False`` بارگذاری می‌شود تا
تست‌های مربوط به سیاست/لاگ بدون ویندوز هم اجرا شوند.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass

logger = logging.getLogger("RamOptimizer")

IS_WINDOWS = sys.platform == "win32"

#: انواع با عرض ثابت (روی لینوکس ``wintypes.DWORD`` هشت بایت است و چیدمان
#: ساختارها را خراب می‌کند؛ در چیدمان ساختارها این معادل‌ها را استفاده می‌کنیم).
DWORD = ctypes.c_uint32
LONG = ctypes.c_int32
WORD = ctypes.c_uint16
BYTE = ctypes.c_uint8
BOOL = ctypes.c_int32
SIZE_T = ctypes.c_size_t

# ----------------------------------------------------------------------------
# ثابت‌ها
# ----------------------------------------------------------------------------

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_SET_QUOTA = 0x0100
PROCESS_SET_INFORMATION = 0x0200
PROCESS_ALL_ACCESS = 0x1FFFFF

TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008
SE_PRIVILEGE_ENABLED = 0x00000002
ERROR_SUCCESS = 0

#: کلاس اطلاعاتی Memory List (نسخه‌ی 80 در SYSTEM_INFORMATION_CLASS).
SystemMemoryListInformation = 0x0050

#: SYSTEM_MEMORY_LIST_COMMAND
MEMORY_CAPTURE_ACCESSED_BITS = 0
MEMORY_EMPTY_WORKING_SETS = 2
MEMORY_FLUSH_MODIFIED_LIST = 3
MEMORY_PURGE_STANDBY_LIST = 4
MEMORY_PURGE_LOW_PRIORITY_STANDBY_LIST = 5

#: QUERY_USER_NOTIFICATION_STATE
QUNS_NOT_PRESENT = 1
QUNS_BUSY = 2
QUNS_RUNNING_D3D_FULL_SCREEN = 3
QUNS_PRESENTATION_MODE = 4
QUNS_ACCEPTS_NOTIFICATIONS = 5
QUNS_QUIET_TIME = 6
QUNS_APP = 7

#: وضعیت‌هایی که یعنی «دست به حافظه نزن» (بازی تمام‌صفحه، ارائه، نمایشگر قفل…).
BUSY_USER_STATES = frozenset(
    {QUNS_NOT_PRESENT, QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE}
)

_NTSTATUS_NAMES = {
    0xC0000061: "STATUS_PRIVILEGE_NOT_HELD",
    0xC0000022: "STATUS_ACCESS_DENIED",
    0xC000000D: "STATUS_INVALID_PARAMETER",
    0xC0000001: "STATUS_UNSUCCESSFUL",
    0xC0000010: "STATUS_INVALID_DEVICE_REQUEST",
    0xC000009A: "STATUS_INSUFFICIENT_RESOURCES",
    0xC0000142: "STATUS_DLL_INIT_FAILED",
}


def ntstatus_name(status: int) -> str:
    """تبدیل NTSTATUS به نام خوانا (برای لاگ عیب‌یابی).

    NTSTATUS در ctypes با ``LONG`` (int32 علامت‌دار) برمی‌گردد، ولی برای
    خوانایی/تست ممکن است به‌صورت مقدار 32 بیتی بدون علامت (0xC0000061) هم
    داده شود؛ هر دو حالت یکسان پاسخ می‌دهند.
    """
    value = int(status) & 0xFFFFFFFF
    # بیت ۳۱ = خطا (severity == error) → STATUS_SUCCESS نیست
    if value & 0x80000000 == 0:
        return "STATUS_SUCCESS"
    return _NTSTATUS_NAMES.get(value, f"NTSTATUS 0x{value:08X}")


# ----------------------------------------------------------------------------
# ساختارها
# ----------------------------------------------------------------------------


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", DWORD), ("HighPart", LONG)]


class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", DWORD)]


class TOKEN_PRIVILEGES(ctypes.Structure):
    _fields_ = [("PrivilegeCount", DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]


class MEMORYSTATUSEX(ctypes.Structure):
    # چیدمان ABI ویندوز: حداکثر تراز ۸ بایت (پیش‌فرض پایتون ۳.۱۲ = ۱۶)
    _pack_ = 8
    """وضعیت حافظه از دید ویندوز (معادل چیزی که Task Manager نشان می‌دهد)."""

    _fields_ = [
        ("dwLength", DWORD),
        ("dwMemoryLoad", DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


class SYSTEM_MEMORY_LIST_INFORMATION(ctypes.Structure):
    # چیدمان ABI ویندوز: حداکثر تراز ۸ بایت (پیش‌فرض پایتون ۳.۱۲ = ۱۶)
    _pack_ = 8
    """شمارش صفحات هر لیست حافظه — همان اعدادی که RAMMap نشان می‌دهد."""

    _fields_ = [
        ("ZeroPageCount", ctypes.c_size_t),
        ("FreePageCount", ctypes.c_size_t),
        ("ModifiedPageCount", ctypes.c_size_t),
        ("ModifiedNoWritePageCount", ctypes.c_size_t),
        ("BadPageCount", ctypes.c_size_t),
        ("PageCountByPriority", ctypes.c_size_t * 8),
        ("RepurposedPagesByPriority", ctypes.c_size_t * 8),
        ("ModifiedPageCountPageFile", ctypes.c_size_t),
    ]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    """ساختار استاندارد GetProcessMemoryInfo (روی x64 = 72 بایت).

    ``PROCESS_MEMORY_COUNTERS_EX`` فقط یک فیلد بیشتر (``PrivateUsage``) دارد و
    همان ۷۲ بایت اول را دارد، پس می‌توان همیشه از نسخه‌ی استاندارد استفاده کرد
    و در صورت نیاز همان ۷۲ بایت را به EX تفسیر کرد. این کار وابستگی به
    ``SIZE_T`` در چیدمان را کم می‌کند.
    """

    _pack_ = 8
    _fields_ = [
        ("cb", DWORD),
        ("PageFaultCount", DWORD),
        ("PeakWorkingSetSize", SIZE_T),
        ("WorkingSetSize", SIZE_T),
        ("QuotaPeakPagedPoolUsage", SIZE_T),
        ("QuotaPagedPoolUsage", SIZE_T),
        ("QuotaPeakNonPagedPoolUsage", SIZE_T),
        ("QuotaNonPagedPoolUsage", SIZE_T),
        ("PagefileUsage", SIZE_T),
        ("PeakPagefileUsage", SIZE_T),
    ]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    # چیدمان ABI ویندوز: حداکثر تراز ۸ بایت (پیش‌فرض پایتون ۳.۱۲ = ۱۶)
    _pack_ = 8
    _fields_ = [
        ("ACLineStatus", BYTE),
        ("BatteryFlag", BYTE),
        ("BatteryLifePercent", BYTE),
        ("Reserved1", BYTE),
        ("BatteryLifeTime", DWORD),
        ("BatteryFullLifeTime", DWORD),
    ]


@dataclass(frozen=True)
class MemorySnapshot:
    """عکس لحظه‌ای از حافظه — همه بر حسب بایت.

    ``used_percent`` همان عدد «Memory» در Task Manager است:
    ``(total - available) / total`` که standby/cache را هم شامل می‌شود.
    ``commit_percent`` فشار واقعی commit است (چیزی که باعث خطای Out of Memory
    می‌شود) و با پاک‌سازی کش تغییر نمی‌کند؛ به همین دلیل عدد صادقانه‌تری برای
    لاگ است.
    """

    total_bytes: int
    available_bytes: int
    used_percent: float
    commit_used_bytes: int
    commit_limit_bytes: int
    commit_percent: float

    @property
    def available_mb(self) -> float:
        return self.available_bytes / (1024 * 1024)

    @property
    def total_mb(self) -> float:
        return self.total_bytes / (1024 * 1024)

    @property
    def used_mb(self) -> float:
        return (self.total_bytes - self.available_bytes) / (1024 * 1024)


# ----------------------------------------------------------------------------
# پشته‌ی API
# ----------------------------------------------------------------------------


class Win32Api:
    """پوشش نازک روی توابع ویندوز. همه‌ی متدها روی غیر ویندوز بی‌خطرند."""

    def __init__(self) -> None:
        self.available = False
        self.load_error: str = ""
        self._page_size: int | None = None
        if not IS_WINDOWS:
            self.load_error = "این برنامه فقط روی ویندوز کار می‌کند"
            return
        try:  # pragma: no cover - فقط ویندوز
            self._load()
            self.available = True
        except (OSError, AttributeError, ValueError) as exc:  # pragma: no cover
            self.load_error = str(exc)
            logger.error("بارگذاری توابع ویندوز ناموفق بود: %s", exc)

    # -- بارگذاری ----------------------------------------------------------
    def _load(self) -> None:  # pragma: no cover - فقط ویندوز
        self.kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True)
        self.ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
        self.advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)

        k32 = self.kernel32

        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.GetCurrentProcess.argtypes = []

        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

        k32.CloseHandle.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]

        k32.GetSystemInfo.argtypes = [ctypes.POINTER(_SystemInfo)]
        k32.GetSystemInfo.restype = None

        k32.GlobalMemoryStatusEx.restype = wintypes.BOOL
        k32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(MEMORYSTATUSEX)]

        k32.GetSystemPowerStatus.restype = wintypes.BOOL
        k32.GetSystemPowerStatus.argtypes = [ctypes.POINTER(SYSTEM_POWER_STATUS)]

        k32.GetTickCount64.restype = ctypes.c_ulonglong
        k32.GetTickCount64.argtypes = []

        self.psapi.EmptyWorkingSet.restype = wintypes.BOOL
        self.psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
        self.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        self.psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
            wintypes.DWORD,
        ]

        # EmptyWorkingSet/GetProcessMemoryInfo روی ویندوز ۷+ در kernel32 هم
        # موجودند (K32...) و مایکروسافت استفاده از آنها را توصیه می‌کند.
        if hasattr(k32, "K32EmptyWorkingSet"):
            k32.K32EmptyWorkingSet.restype = wintypes.BOOL
            k32.K32EmptyWorkingSet.argtypes = [wintypes.HANDLE]
        if hasattr(k32, "K32GetProcessMemoryInfo"):
            k32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
            k32.K32GetProcessMemoryInfo.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(PROCESS_MEMORY_COUNTERS),
                wintypes.DWORD,
            ]

        self.ntdll.NtSetSystemInformation.restype = wintypes.LONG
        self.ntdll.NtSetSystemInformation.argtypes = [wintypes.INT, wintypes.LPVOID, wintypes.ULONG]

        self.ntdll.NtQuerySystemInformation.restype = wintypes.LONG
        self.ntdll.NtQuerySystemInformation.argtypes = [
            wintypes.INT,
            wintypes.LPVOID,
            wintypes.ULONG,
            ctypes.POINTER(wintypes.ULONG),
        ]

        self.advapi32.OpenProcessToken.restype = wintypes.BOOL
        self.advapi32.OpenProcessToken.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        ]
        self.advapi32.LookupPrivilegeValueW.restype = wintypes.BOOL
        self.advapi32.LookupPrivilegeValueW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            ctypes.POINTER(LUID),
        ]
        self.advapi32.AdjustTokenPrivileges.restype = wintypes.BOOL
        self.advapi32.AdjustTokenPrivileges.argtypes = [
            wintypes.HANDLE,
            wintypes.BOOL,
            ctypes.POINTER(TOKEN_PRIVILEGES),
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.LPVOID,
        ]

        # HRESULT در ctypes.wintypes تعریف نشده است (فقط در برخی نسخه‌ها)
        self.shell32.SHQueryUserNotificationState.restype = ctypes.c_long
        self.shell32.SHQueryUserNotificationState.argtypes = [ctypes.POINTER(wintypes.INT)]

    # -- اختیارها ----------------------------------------------------------
    def enable_privilege(self, privilege_name: str) -> bool:  # pragma: no cover - ویندوز
        """فعال‌سازی یک Privilege برای پروسه‌ی جاری."""
        if not self.available:
            return False
        token = wintypes.HANDLE()
        if not self.advapi32.OpenProcessToken(
            self.kernel32.GetCurrentProcess(),
            TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
            ctypes.byref(token),
        ):
            return False
        try:
            luid = LUID()
            if not self.advapi32.LookupPrivilegeValueW(None, privilege_name, ctypes.byref(luid)):
                return False
            tp = TOKEN_PRIVILEGES()
            tp.PrivilegeCount = 1
            tp.Privileges[0].Luid = luid
            tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
            ctypes.set_last_error(0)
            ok = self.advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
            # AdjustTokenPrivileges موفق «True» برمی‌گرداند حتی وقتی اختیار
            # واقعاً فعال نشده؛ باید last_error را چک کرد.
            return bool(ok) and ctypes.get_last_error() == ERROR_SUCCESS
        finally:
            self.kernel32.CloseHandle(token)

    def check_privilege(self, privilege_name: str) -> bool:  # pragma: no cover
        """فقط برای گزارش وضعیت: آیا اختیار در توکن موجود/فعال است؟"""
        return self.enable_privilege(privilege_name)

    # -- حافظه‌ی سیستم -----------------------------------------------------
    @property
    def page_size(self) -> int:  # pragma: no cover
        if self._page_size is None:
            if not self.available:
                return 4096
            info = _SystemInfo()
            self.kernel32.GetSystemInfo(ctypes.byref(info))
            self._page_size = int(info.dwPageSize) or 4096
        return self._page_size

    def memory_snapshot(self) -> MemorySnapshot | None:  # pragma: no cover - ویندوز
        if not self.available:
            return None
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if not self.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        total = int(status.ullTotalPhys)
        available = int(status.ullAvailPhys)
        used_percent = ((total - available) / total * 100.0) if total else 0.0
        commit_limit = int(status.ullTotalPageFile)
        commit_used = max(0, commit_limit - int(status.ullAvailPageFile))
        commit_percent = (commit_used / commit_limit * 100.0) if commit_limit else 0.0
        return MemorySnapshot(
            total_bytes=total,
            available_bytes=available,
            used_percent=used_percent,
            commit_used_bytes=commit_used,
            commit_limit_bytes=commit_limit,
            commit_percent=commit_percent,
        )

    def memory_list_info(self) -> SYSTEM_MEMORY_LIST_INFORMATION | None:  # pragma: no cover
        """شمارش صفحات Free/Modified/Standby."""
        if not self.available:
            return None
        info = SYSTEM_MEMORY_LIST_INFORMATION()
        returned = wintypes.ULONG()
        status = self.ntdll.NtQuerySystemInformation(
            SystemMemoryListInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
            ctypes.byref(returned),
        )
        if status != 0:
            logger.debug("NtQuerySystemInformation(MemoryList) ناموفق: %s", ntstatus_name(status))
            return None
        return info

    def standby_bytes(self) -> int | None:  # pragma: no cover
        """حجم Standby List (کش) بر حسب بایت."""
        info = self.memory_list_info()
        if info is None:
            return None
        pages = sum(int(count) for count in info.PageCountByPriority)
        return pages * self.page_size

    def memory_list_command(self, command: int) -> tuple[bool, str]:  # pragma: no cover
        """اجرای یک SYSTEM_MEMORY_LIST_COMMAND. خروجی: (موفق؟, توضیح خطا)."""
        if not self.available:
            return False, "ویندوز در دسترس نیست"
        value = wintypes.ULONG(command)
        status = self.ntdll.NtSetSystemInformation(
            SystemMemoryListInformation, ctypes.byref(value), ctypes.sizeof(value)
        )
        if status == 0:
            return True, ""
        return False, ntstatus_name(status)

    # -- پروسه‌ها ----------------------------------------------------------
    def open_process(self, pid: int, access: int) -> int | None:  # pragma: no cover
        if not self.available:
            return None
        handle = self.kernel32.OpenProcess(access, False, pid)
        return int(handle) if handle else None

    def close_handle(self, handle: int) -> None:  # pragma: no cover
        if self.available:
            self.kernel32.CloseHandle(wintypes.HANDLE(handle))

    def empty_working_set(self, handle: int) -> bool:  # pragma: no cover
        if hasattr(self.kernel32, "K32EmptyWorkingSet"):
            return bool(self.kernel32.K32EmptyWorkingSet(wintypes.HANDLE(handle)))
        return bool(self.psapi.EmptyWorkingSet(wintypes.HANDLE(handle)))

    def working_set_size(self, handle: int) -> int:  # pragma: no cover
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        getter = getattr(self.kernel32, "K32GetProcessMemoryInfo", None) or getattr(
            self.psapi, "GetProcessMemoryInfo", None
        )
        if getter is None:
            return 0
        if not getter(wintypes.HANDLE(handle), ctypes.byref(counters), counters.cb):
            return 0
        return int(counters.WorkingSetSize)

    # -- محیط کاربر --------------------------------------------------------
    def user_notification_state(self) -> int | None:  # pragma: no cover
        """وضعیت کاربر: تمام‌صفحه/مشغول/قفل/ارائه… (shell32)."""
        if not self.available:
            return None
        state = wintypes.INT()
        try:
            if self.shell32.SHQueryUserNotificationState(ctypes.byref(state)) != 0:
                return None
        except OSError:
            return None
        return int(state.value)

    def is_on_battery(self) -> bool:  # pragma: no cover
        if not self.available:
            return False
        status = SYSTEM_POWER_STATUS()
        if not self.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return False
        # BatteryFlag 128 = بدون باتری، 255 = نامشخص (دسکتاپ)
        if status.BatteryFlag in (128, 255):
            return False
        return status.ACLineStatus == 0

    def monotonic_ms(self) -> float:  # pragma: no cover
        if not self.available:
            return time.monotonic() * 1000.0
        return float(self.kernel32.GetTickCount64())


class _SystemInfo(ctypes.Structure):
    # چیدمان ABI ویندوز: حداکثر تراز ۸ بایت (پیش‌فرض پایتون ۳.۱۲ = ۱۶)
    _pack_ = 8
    _fields_ = [
        ("wProcessorArchitecture", WORD),
        ("wReserved", WORD),
        ("dwPageSize", DWORD),
        ("lpMinimumApplicationAddress", ctypes.c_void_p),
        ("lpMaximumApplicationAddress", ctypes.c_void_p),
        ("dwActiveProcessorMask", ctypes.c_size_t),
        ("dwNumberOfProcessors", DWORD),
        ("dwProcessorType", DWORD),
        ("dwAllocationGranularity", DWORD),
        ("wProcessorLevel", WORD),
        ("wProcessorRevision", WORD),
    ]


__all__ = [
    "BUSY_USER_STATES",
    "IS_WINDOWS",
    "MEMORY_EMPTY_WORKING_SETS",
    "MEMORY_FLUSH_MODIFIED_LIST",
    "MEMORY_PURGE_LOW_PRIORITY_STANDBY_LIST",
    "MEMORY_PURGE_STANDBY_LIST",
    "PROCESS_QUERY_LIMITED_INFORMATION",
    "PROCESS_SET_QUOTA",
    "MemorySnapshot",
    "Win32Api",
    "ntstatus_name",
]
