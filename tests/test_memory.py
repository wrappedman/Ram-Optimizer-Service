# -*- coding: utf-8 -*-
"""تست لایه‌ی عملیات حافظه: انتخاب پروسه‌ها، شمارش واقعی آزادشده، Standby List."""

from __future__ import annotations

from ramopt import win32
from ramopt.config import Config
from ramopt.memory import (
    MB,
    TRIM_ACCESS,
    ProcessInfo,
    PurgeReport,
    purge_standby_list,
    trim_working_sets,
)


def test_trim_access_rights_are_the_documented_ones():
    """باگ B? نسخه‌ی قبل: ماسک دسترسی طوری بود که trim عملاً هیچ اثری نداشت."""
    assert TRIM_ACCESS & win32.PROCESS_SET_QUOTA
    assert TRIM_ACCESS & (win32.PROCESS_QUERY_LIMITED_INFORMATION)
    assert TRIM_ACCESS & win32.PROCESS_SET_INFORMATION
    from ramopt.win32 import PROCESS_ALL_ACCESS

    assert TRIM_ACCESS != PROCESS_ALL_ACCESS


def test_small_and_excluded_processes_are_skipped(base_config, fake_api, fake_provider):
    report = trim_working_sets(fake_api, fake_provider, base_config)
    names = {pid for pid, _ in fake_api.opened}
    assert 200 not in names, "dwm.exe مستثناست"
    assert 300 not in names, "پروسه‌ی ۵ مگابایتی نباید trim شود"
    assert 500 not in names, "MsMpEng.exe با الگو مستثناست"
    assert 4 not in names, "System Idle/System دست نمی‌خورند"
    assert report.skipped_small >= 1
    assert report.skipped_excluded >= 2


def test_largest_processes_first_and_capped(base_config, fake_api):
    from conftest import FakeProvider

    processes = [
        ProcessInfo(pid=i, name=f"p{i}.exe", working_set_bytes=(i * 100) * MB) for i in range(1, 11)
    ]
    config = Config(**{**base_config.__dict__, "max_processes": 3})
    report = trim_working_sets(fake_api, FakeProvider(processes), config)
    assert report.considered == 3
    assert [pid for pid, _ in fake_api.opened] == [10, 9, 8]


def test_process_that_shrank_before_handle_is_skipped(base_config, fake_api):
    """اگر پروسه بین گرفتن فهرست و باز کردن handle کوچک شده باشد، trim نمی‌شود."""
    from conftest import FakeProvider

    processes = [ProcessInfo(pid=900, name="shrunk.exe", working_set_bytes=500 * MB)]
    provider = FakeProvider(processes)
    provider.working_sets = {900: 2 * MB}  # حالا فقط ۲ مگابایت است

    report = trim_working_sets(fake_api, provider, base_config)
    # پروسه زیر آستانه است، پس حتی باز هم نمی‌شود
    assert report.trimmed == 0
    assert report.skipped_small == 1
    assert fake_api.opened == []

    # و اگر آستانه را صفر کنیم ولی پروسه هنگام باز شدن handle کوچک شده باشد:
    fake_api.opened.clear()
    provider.working_sets = {900: 400 * MB}
    report = trim_working_sets(fake_api, provider, base_config)
    assert report.trimmed == 1


def test_freed_bytes_are_measured_not_guessed(base_config, fake_api, fake_provider):
    from conftest import set_process_sizes

    set_process_sizes(fake_api, fake_provider, {100: 400, 101: 250, 400: 1000})
    report = trim_working_sets(fake_api, fake_provider, base_config)
    assert report.trimmed == 3
    assert report.freed_mb == 1650
    assert report.biggest[0][0] == "game.exe"
    assert report.biggest[0][1] == 1000 * MB


def test_denied_processes_are_counted(base_config, fake_api, fake_provider):
    fake_api.open_denied = True
    report = trim_working_sets(fake_api, fake_provider, base_config)
    assert report.trimmed == 0
    assert report.denied == report.considered > 0


def test_failed_open_reports_error(base_config):
    class Broken:
        available = False
        load_error = "no windows"

    report = trim_working_sets(Broken(), None, base_config)  # type: ignore[arg-type]
    assert report.error == "Windows API is not available"


def test_purge_is_skipped_when_enough_memory_after_trim(base_config):
    """باگ B9 نسخه‌ی قبل: کش همیشه خالی می‌شد؛ حالا فقط اگر لازم باشد."""

    class Api:
        def standby_bytes(self):
            return 1024 * MB

        def memory_list_command(self, command):  # pragma: no cover - نباید صدا زده شود
            raise AssertionError("نباید Standby List خالی شود")

    api = Api()
    config = Config(**{**base_config.__dict__, "min_free_mb_after_trim": 512})
    report = purge_standby_list(api, config, current_available_mb=2048)  # type: ignore[arg-type]
    assert report.attempted is False
    assert report.purged is False
    assert "512" in report.skipped_reason


def test_purge_runs_when_memory_is_still_tight(base_config, fake_api):
    config = Config(**{**base_config.__dict__, "min_free_mb_after_trim": 512})
    report = purge_standby_list(fake_api, config, current_available_mb=100)
    assert report.attempted is True
    assert report.purged is True
    assert report.standby_before_bytes == 2048 * MB
    assert report.standby_after_bytes == 0
    assert report.standby_freed_mb == 2048


def test_purge_disabled_by_config(base_config, fake_api):
    config = Config(**{**base_config.__dict__, "purge_standby_list": False})
    report = purge_standby_list(fake_api, config)
    assert report.purged is False
    assert fake_api.commands == []


def test_purge_error_is_reported(base_config, fake_api):
    fake_api.command_result = (False, "STATUS_PRIVILEGE_NOT_HELD")
    report = purge_standby_list(fake_api, base_config)
    assert report.attempted is True
    assert report.purged is False
    assert "PRIVILEGE" in report.error


def test_purge_report_dict_is_json_safe():
    report = PurgeReport(
        attempted=True, purged=True, standby_before_bytes=10 * MB, standby_after_bytes=0
    )
    data = report.as_dict()
    assert data["standby_freed_mb"] == 10.0
    assert data["standby_after_mb"] == 0.0
