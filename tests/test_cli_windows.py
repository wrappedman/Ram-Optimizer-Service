# -*- coding: utf-8 -*-
"""تست مسیرهای خط فرمان که فقط روی ویندوز اجرا می‌شوند.

با جایگزین‌کردن ``sys.platform``، ``Win32Api`` و ``PsutilProcessProvider``
همین کدها روی لینوکس هم اجرا می‌شوند؛ در غیر این صورت این مسیرها هیچ‌وقت در
CI تست نمی‌شدند.
"""

from __future__ import annotations

import json
import sys

import pytest

from conftest import FakeApi, FakeProvider, set_process_sizes
from ramopt import memory, win32
from ramopt.cli import main


@pytest.fixture()
def windows_like(monkeypatch):
    """محیط شبیه ویندوز: FakeApi + FakeProvider تزریق‌شده به CLI."""
    api = FakeApi(total_gb=16, used_gb=14, standby_gb=2)
    provider = FakeProvider()
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(win32, "Win32Api", lambda: api)
    monkeypatch.setattr(memory, "PsutilProcessProvider", lambda: provider)
    return api, provider


def test_dry_run_lists_targets_and_changes_nothing(windows_like, capsys):
    api, provider = windows_like
    set_process_sizes(api, provider, {100: 600, 400: 1500})

    assert main(["test", "--dry-run", "--include-fullscreen"]) == 0
    out = capsys.readouterr().out

    assert "dry run" in out
    assert "chrome.exe" in out
    assert api.trimmed_pids == set(), "در dry-run نباید هیچ پروسه‌ای trim شود"
    assert api.commands == [], "در dry-run نباید Standby List خالی شود"


def test_real_cycle_output(windows_like, capsys):
    api, provider = windows_like
    set_process_sizes(api, provider, {400: 1500})

    assert main(["test", "--force", "--include-fullscreen"]) == 0
    out = capsys.readouterr().out

    assert "optimized" in out
    assert "1500" in out
    assert api.trimmed_pids == {400}


def test_real_cycle_json_output(windows_like, capsys):
    api, provider = windows_like
    set_process_sizes(api, provider, {400: 1500})

    assert main(["test", "--force", "--include-fullscreen", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["action"] == "optimized"
    assert payload["trim"]["trimmed"] == 1
    assert payload["trim"]["freed_mb"] == 1500.0


def test_failed_cycle_exit_code(windows_like, capsys):
    """چرخه‌ای که هیچ کاری نکرد باید کد خروج غیرصفر بدهد (برای Task Scheduler)."""
    api, _provider = windows_like
    api.open_denied = True

    assert main(["test", "--force", "--include-fullscreen"]) == 1
    assert "nothing was changed" in capsys.readouterr().out
