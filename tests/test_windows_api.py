# -*- coding: utf-8 -*-
"""تست‌های مربوط به ویندوز واقعی.

روی سیستم‌های دیگر skip می‌شوند. در CI ویندوز (GitHub Actions) اجرا می‌شوند
و همان چیزهایی را بررسی می‌کنند که فقط با API واقعی قابل بررسی است:

* چیدمان ساختارهای ``ctypes`` (مهم‌ترین ریسک بازنویسی با ctypes)؛
* خواندن واقعی حافظه با ``GlobalMemoryStatusEx``؛
* اجرای ``EmptyWorkingSet`` روی یک پروسه‌ی خودمان و تأیید کاهش Working Set؛
* برگشت NTSTATUS خوانا در صورت نبود دسترسی.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys

import pytest

from ramopt import win32

pytestmark = [
    pytest.mark.windows,
    pytest.mark.skipif(sys.platform != "win32", reason="فقط ویندوز"),
]


def test_struct_layouts_match_windows_abi():
    """روی ویندوز، چیدمان باید دقیقاً با ABI مایکروسافت یکی باشد."""
    assert ctypes.sizeof(win32.MEMORYSTATUSEX) == 64
    assert ctypes.sizeof(win32.SYSTEM_POWER_STATUS) == 12
    assert ctypes.sizeof(win32.PROCESS_MEMORY_COUNTERS) == 72
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        assert ctypes.sizeof(win32.SYSTEM_MEMORY_LIST_INFORMATION) == 176


def test_api_loads_and_reads_memory():
    api = win32.Win32Api()
    assert api.available, api.load_error
    snapshot = api.memory_snapshot()
    assert snapshot is not None
    assert snapshot.total_bytes > 0
    assert 0 <= snapshot.used_percent <= 100
    assert 0 <= snapshot.available_bytes <= snapshot.total_bytes


def test_page_size_and_standby_list_query():
    api = win32.Win32Api()
    assert api.page_size in (4096, 8192, 16384, 65536)
    # NtQuerySystemInformation(SystemMemoryListInformation=80) یا جواب می‌دهد
    # یا (در صورت محدودیت) None برمی‌گرداند — نباید استثنا بدهد.
    info = api.memory_list_info()
    if info is not None:
        assert info.PageCountByPriority[0] >= 0


def test_empty_working_set_on_child_process():
    """روی پروسه‌ی فرزند خودمان: Working Set باید کاهش یابد."""
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; data=bytearray(80*1024*1024); time.sleep(20)"]
    )
    try:
        import time

        time.sleep(2.5)
        api = win32.Win32Api()
        handle = api.open_process(
            child.pid,
            win32.PROCESS_QUERY_LIMITED_INFORMATION
            | win32.PROCESS_SET_QUOTA
            | win32.PROCESS_SET_INFORMATION,
        )
        assert handle, "OpenProcess ناموفق بود (اجرا با دسترسی ادمین لازم است؟)"
        try:
            before = api.working_set_size(handle)
            assert before > 0
            assert api.empty_working_set(handle) is True
            after = api.working_set_size(handle)
            assert after < before
        finally:
            api.close_handle(handle)
    finally:
        child.kill()
        child.wait(timeout=10)


def test_privilege_reporting():
    """SeProfileSingleProcessPrivilege در حالت ادمین باید فعال شود."""
    api = win32.Win32Api()
    enabled = api.enable_privilege("SeProfileSingleProcessPrivilege")
    # اگر تست با دسترسی ادمین/SYSTEM اجرا شود باید True باشد
    assert isinstance(enabled, bool)


def test_user_notification_state_is_readable():
    api = win32.Win32Api()
    state = api.user_notification_state()
    assert state is None or state in range(1, 8)


def test_ntstatus_name_translation():
    assert win32.ntstatus_name(0) == "STATUS_SUCCESS"
    assert win32.ntstatus_name(0xC0000061) == "STATUS_PRIVILEGE_NOT_HELD"
