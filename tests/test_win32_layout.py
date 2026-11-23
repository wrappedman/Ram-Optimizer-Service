# -*- coding: utf-8 -*-
"""تست چیدمان/کمکی‌های لایه‌ی Win32 که روی هر سیستم‌عاملی قابل اجراست.

این تست‌ها همان سه باگی را پوشش می‌دهند که اولین اجرای CI روی ویندوز پیدا
کرد: آفست «success» در NTSTATUS، نبود ``wintypes.HRESULT`` و تراز ۱۶ بایتی
ساختارها در پایتون ۳.۱۲.
"""

from __future__ import annotations

import ctypes

from ramopt import win32


def test_ntstatus_accepts_signed_and_unsigned_values():
    assert win32.ntstatus_name(0) == "STATUS_SUCCESS"
    # مقدار بدون علامت
    assert win32.ntstatus_name(0xC0000061) == "STATUS_PRIVILEGE_NOT_HELD"
    # همان مقدار به‌صورت int32 علامت‌دار که ctypes با LONG برمی‌گرداند
    assert win32.ntstatus_name(-1073741727) == "STATUS_PRIVILEGE_NOT_HELD"
    assert win32.ntstatus_name(0xC0000022) == "STATUS_ACCESS_DENIED"
    assert win32.ntstatus_name(0x80000005).startswith("NTSTATUS 0x80000005")


def test_wintypes_has_no_hresult_so_we_do_not_use_it():
    """``ctypes.wintypes.HRESULT`` روی ویندوز هم وجود ندارد؛ استفاده از آن
    کل بارگذاری ماژول را می‌شکست (اولین اجرای CI ویندوز این را پیدا کرد)."""
    assert not hasattr(ctypes.wintypes, "HRESULT")


def test_structures_are_packed_for_windows_abi():
    """تراز پیش‌فرض ctypes در پایتون ۳.۱۲ برابر ۱۶ است؛ ویندوز حداکثر ۸."""
    for structure in (
        win32.MEMORYSTATUSEX,
        win32.SYSTEM_MEMORY_LIST_INFORMATION,
        win32.PROCESS_MEMORY_COUNTERS,
        win32.SYSTEM_POWER_STATUS,
    ):
        assert structure._pack_ == 8, structure.__name__


def test_counter_structure_sizes():
    assert ctypes.sizeof(win32.MEMORYSTATUSEX) == 64
    assert ctypes.sizeof(win32.SYSTEM_POWER_STATUS) == 12
    if _is_x64():
        assert ctypes.sizeof(win32.PROCESS_MEMORY_COUNTERS) == 72
        assert ctypes.sizeof(win32.SYSTEM_MEMORY_LIST_INFORMATION) == 176


def _is_x64() -> bool:
    return ctypes.sizeof(ctypes.c_void_p) == 8


def test_windows_only_test_file_only_references_existing_structures():
    """تست ویندوزی نباید به ساختاری اشاره کند که وجود ندارد.

    (اولین اجرای CI ویندوز همین را پیدا کرد: تست به
    ``PROCESS_MEMORY_COUNTERS_EX`` اشاره می‌کرد که حذف شده بود و روی لینوکس
    skip می‌شد، پس هیچ‌وقت دیده نشد.)
    """
    import ast
    import pathlib

    source = (pathlib.Path(__file__).parent / "test_windows_api.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    referenced = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "win32"
    }
    missing = sorted(name for name in referenced if not hasattr(win32, name))
    assert missing == [], f"این نام‌ها در ramopt.win32 وجود ندارند: {missing}"
