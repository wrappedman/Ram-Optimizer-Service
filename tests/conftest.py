# -*- coding: utf-8 -*-
"""ابزارهای مشترک تست‌ها.

مهم‌ترین بخش، ``FakeApi`` است: یک جانشین کامل برای ``ramopt.win32.Win32Api``
که وضعیت حافظه و رفتار پروسه‌ها را شبیه‌سازی می‌کند. با آن می‌توان کل سیاست
(cooldown، هیسترزیس، بک‌آف، لیست استثنا، …) را روی لینوکس/مک هم تست کرد.
"""

from __future__ import annotations

import datetime as dt
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ramopt import win32
from ramopt.config import Config
from ramopt.memory import ProcessInfo

GB = 1024**3
MB = 1024**2


class FakeClock:
    """ساعت قابل کنترل تا cooldown/سقف ساعتی بدون sleep تست شوند."""

    def __init__(self, start: dt.datetime | None = None) -> None:
        self.current = start or dt.datetime(2026, 1, 1, 12, 0, 0)

    def now(self) -> dt.datetime:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += dt.timedelta(seconds=seconds)


class FakeApi:
    """جانشین ``Win32Api`` با کنترل کامل روی همه‌ی مقادیر برگشتی."""

    def __init__(
        self,
        total_gb: float = 16.0,
        used_gb: float = 12.0,
        standby_gb: float = 2.0,
        commit_percent: float = 40.0,
    ) -> None:
        self.available = True
        self.load_error = ""
        self.total_bytes = int(total_gb * GB)
        self.used_bytes = int(used_gb * GB)
        self.standby_total = int(standby_gb * GB)
        self.commit_percent = commit_percent

        self.user_state: int | None = win32.QUNS_ACCEPTS_NOTIFICATIONS
        self.on_battery = False
        self.privileges: list[str] = []
        self.commands: list[int] = []
        self.open_denied = False
        self.empty_working_set_ok = True
        self.command_result = (True, "")
        self.process_names: dict[int, str] = {}
        #: اندازه‌ی Working Set هر PID از دید API در لحظه‌ی باز کردن handle.
        #: None یعنی «همان اندازه‌ای که در فهرست پروسه‌ها آمده».
        self.working_sets: dict[int, int] | None = None
        #: پیش‌فرض هم‌زمان با فهرست پروسه‌ها ساخته می‌شود
        self.process_sizes: dict[int, int] | None = {
            proc.pid: proc.working_set_bytes for proc in default_process_list()
        }
        self.opened: list[tuple[int, int]] = []
        self._opens = 0
        self.trimmed_pids: set[int] = set()
        self._tick = 0.0
        self.snapshot_failures = 0

    # -- اختیار --------------------------------------------------------
    def enable_privilege(self, name: str) -> bool:
        self.privileges.append(name)
        return True

    # -- حافظه ---------------------------------------------------------
    def memory_snapshot(self) -> win32.MemorySnapshot | None:
        if self.snapshot_failures:
            self.snapshot_failures -= 1
            return None
        available = max(0, self.total_bytes - self.used_bytes)
        return win32.MemorySnapshot(
            total_bytes=self.total_bytes,
            available_bytes=available,
            used_percent=(self.used_bytes / self.total_bytes) * 100.0,
            commit_used_bytes=int(self.total_bytes * self.commit_percent / 100.0),
            commit_limit_bytes=self.total_bytes,
            commit_percent=self.commit_percent,
        )

    def standby_bytes(self) -> int:
        return self.standby_total

    def memory_list_command(self, command: int) -> tuple[bool, str]:
        self.commands.append(command)
        ok, error = self.command_result
        if ok and command == win32.MEMORY_PURGE_STANDBY_LIST:
            self.standby_total = 0
        return ok, error

    # -- پروسه‌ها -------------------------------------------------------
    def open_process(self, pid: int, access: int) -> int | None:
        self.opened.append((pid, access))
        if self.open_denied:
            return None
        self._opens += 1
        return 1000 + pid

    def close_handle(self, handle: int) -> None:
        return None

    def empty_working_set(self, handle: int) -> bool:
        if not self.empty_working_set_ok:
            return False
        before = self.working_set_size(handle)
        self.trimmed_pids.add(handle - 1000)
        # آزاد شدن واقعی حافظه‌ی سیستم بعد از trim
        self.used_bytes = max(0, self.used_bytes - before)
        return True

    def working_set_size(self, handle: int) -> int:
        """اندازه‌ی Working Set از دید API (پروسه‌ی trim‌شده صفر است)."""
        pid = handle - 1000
        if pid in self.trimmed_pids:
            return 0
        if self.working_sets is not None:
            return self.working_sets.get(pid, 0)
        if self.process_sizes is not None:
            return self.process_sizes.get(pid, 0)
        return 0

    # -- محیط ----------------------------------------------------------
    def user_notification_state(self) -> int | None:
        return self.user_state

    def is_on_battery(self) -> bool:
        return self.on_battery

    def monotonic_ms(self) -> float:
        self._tick += 37.0
        return self._tick


class FakeProvider:
    """فهرست پروسه‌های ثابت برای تست."""

    def __init__(self, processes: list[ProcessInfo] | None = None) -> None:
        self.processes = processes if processes is not None else default_process_list()
        self.calls = 0
        #: اندازه‌ی Working Set که API برای هر PID گزارش می‌کند
        self.working_sets: dict[int, int] = {
            proc.pid: proc.working_set_bytes for proc in self.processes
        }

    def list_processes(self) -> list[ProcessInfo]:
        self.calls += 1
        result = []
        for proc in self.processes:
            size = self.working_sets.get(proc.pid, proc.working_set_bytes)
            result.append(ProcessInfo(proc.pid, proc.name, size))
        return result

    def process_name(self, pid: int) -> str | None:
        for proc in self.processes:
            if proc.pid == pid:
                return proc.name
        return None


def set_process_sizes(api: FakeApi, provider: FakeProvider, sizes_mb: dict[int, float]) -> None:
    """جانشینی کامل فهرست پروسه‌ها با اندازه‌های داده‌شده (به مگابایت).

    نام هر PID از فهرست پیش‌فرض گرفته می‌شود تا استثناها هم قابل تست بمانند.
    """
    names = {proc.pid: proc.name for proc in default_process_list()}
    sizes = {pid: int(mb * MB) for pid, mb in sizes_mb.items()}
    provider.processes = [
        ProcessInfo(pid=pid, name=names.get(pid, f"pid{pid}.exe"), working_set_bytes=size)
        for pid, size in sizes.items()
    ]
    provider.working_sets = dict(sizes)
    api.working_sets = dict(sizes)


def default_process_list() -> list[ProcessInfo]:
    return [
        ProcessInfo(pid=4, name="System", working_set_bytes=200 * MB),
        ProcessInfo(pid=100, name="chrome.exe", working_set_bytes=900 * MB),
        ProcessInfo(pid=101, name="chrome.exe", working_set_bytes=700 * MB),
        ProcessInfo(pid=200, name="dwm.exe", working_set_bytes=300 * MB),  # مستثنا
        ProcessInfo(pid=300, name="notepad.exe", working_set_bytes=5 * MB),  # کوچک
        ProcessInfo(pid=400, name="game.exe", working_set_bytes=2048 * MB),
        ProcessInfo(pid=500, name="MsMpEng.exe", working_set_bytes=250 * MB),  # الگوی استثنا
    ]


@pytest.fixture()
def fake_api() -> FakeApi:
    return FakeApi()


@pytest.fixture()
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture()
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture()
def base_config() -> Config:
    """پیکربندی با تأخیر شروع صفر تا تست‌ها فوراً معنی بدهند."""
    return Config(
        check_interval_seconds=60,
        startup_delay_seconds=0,
        trigger_percent=75,
        reset_percent=65,
        cooldown_seconds=300,
        max_purges_per_hour=6,
        min_available_mb=0,
        purge_standby_list=True,
        min_free_mb_after_trim=0,  # تا تست‌ها به بالا بودن آزاد گیر نکنند
        min_process_ws_mb=20,
        max_processes=0,
        skip_when_fullscreen=True,
        skip_on_battery=False,
        quiet_hours="",
    )


@pytest.fixture(autouse=True)
def _capture_ramopt_logs():
    """``logger.propagate = False`` در ``logging_setup`` باعث می‌شود caplog
    هیچ رکوردی از ماژول‌های ramopt نبیند (و این به ترتیب اجرای تست‌ها وابسته
    بود: تا وقتی ``setup_logging`` صدا زده نشده بود کار می‌کرد).

    اینجاد propagation را برای طول هر تست روشن می‌کنیم تا ``caplog`` همیشه
    کار کند، و بعد از تست وضعیت اصلی را برمی‌گردانیم.
    """
    import logging

    logger = logging.getLogger("RamOptimizer")
    previous = logger.propagate
    previous_level = logger.level
    logger.propagate = True
    if logger.level == logging.NOTSET or logger.level > logging.DEBUG:
        logger.setLevel(logging.DEBUG)
    try:
        yield
    finally:
        logger.propagate = previous
        logger.setLevel(previous_level)


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """همه‌ی تست‌ها در پوشه‌ی موقت خودشان کار کنند (هیچ فایلی جای دیگر نوشته نشود)."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setenv("RAMOPT_DATA_DIR", str(data))
    return data
