# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — منبع واحد حقیقت برای بیلد سرویس.

با ``build_exe.bat`` یا ``pyinstaller RamOptimizerService.spec`` ساخته می‌شود.
حالت ``onedir`` عمداً استفاده می‌شود: exe تک‌فایلی هر بار خودش را در TEMP باز
می‌کند و مدیر سرویس ویندوز اغلب در ۳۰ ثانیه به آن وصل نمی‌شود
(خطای «service did not respond in a timely fashion»).
"""
from __future__ import annotations

import os

from PyInstaller.utils.hooks import collect_submodules

# در spec، ``SPECPATH`` پوشه‌ی همین فایل است (مستقل از این‌که از کجا اجرا شود).
project_root = SPECPATH  # noqa: F821  (متغیر تزریق‌شده توسط PyInstaller)

# ماژول‌های pywin32 که PyInstaller خودش تشخیص نمی‌دهد ولی سرویس لازم دارد.
hidden = [
    "win32timezone",
    "win32service",
    "win32serviceutil",
    "win32event",
    "servicemanager",
    "win32api",
    "win32con",
    "win32evtlogutil",
    "pywintypes",
] + collect_submodules("ramopt")

a = Analysis(
    ["ram_optimizer_service.py"],
    pathex=[project_root],
    binaries=[],
    datas=[],
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # فقط ماژول‌هایی که واقعاً استفاده نمی‌کنیم (حذف بیش از حد، import های
    # غیرمستقیم pywin32/psutil را می‌شکند)
    excludes=["tkinter", "pydoc", "doctest", "test"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RamOptimizerService",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # console=True عمدی است: همان exe هم CLI است (test --dry-run، status، …) و
    # بدون کنسول هیچ خروجی‌ای نشان نمی‌دهد. سرویس وقتی SCM آن را در session 0
    # اجرا می‌کند پنجره‌ای نشان نمی‌دهد.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=os.path.join(project_root, "version_info.txt")
    if os.path.isfile(os.path.join(project_root, "version_info.txt"))
    else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RamOptimizerService",
)
