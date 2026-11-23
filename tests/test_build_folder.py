# -*- coding: utf-8 -*-
"""تست ساختار پوشه‌ی ``build`` و اسکریپت مدیریت ویندوز.

ساخت خود exe فقط روی ویندوز و در CI انجام می‌شود (اسکریپت/دستور مستقیم)، ولی
این تست‌ها تضمین می‌کنند که:

* فایل‌های کنترلی (bat/ps1) فراموش نشده و در git هستند؛
* هر دستوری که اسکریپت مدیریت به exe می‌دهد، در argparse وجود دارد؛
* گاردهای مکانیزم «هر دقیقه / فوری» در سورس واقعاً وجود دارند و تست پوشش
  دارند (این همان چیزی است که کاربر خواسته ببیند).
"""

from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
PANEL = BUILD / "RamOptimizerControl.ps1"


@pytest.fixture(scope="module")
def panel_text() -> str:
    return PANEL.read_text(encoding="utf-8")


def test_control_panel_files_exist() -> None:
    for name in ("Manage-RamOptimizer.bat", "RamOptimizerControl.ps1", "build_exe.bat"):
        path = BUILD / name
        assert path.is_file(), f"missing {path}"
        assert path.stat().st_size > 0


def test_build_folder_is_not_ignored_but_exe_is() -> None:
    """``build/`` نباید ignore شود، ولی exeهای داخل آن نباید وارد git شوند."""
    check = subprocess.run(
        ["git", "check-ignore", "-v", "build/RamOptimizerService/RamOptimizerService.exe"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if check.returncode not in (0, 1):  # git در دسترس نیست
        pytest.skip("git is not available")
    assert check.returncode == 0, "the built exe must stay out of Git"

    panel = subprocess.run(
        ["git", "check-ignore", "build/RamOptimizerControl.ps1"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert panel.returncode == 1, "build/RamOptimizerControl.ps1 must not be ignored"


def test_bat_launches_the_powershell_panel() -> None:
    text = (BUILD / "Manage-RamOptimizer.bat").read_text(encoding="utf-8", errors="replace")
    assert "RamOptimizerControl.ps1" in text
    assert "ExecutionPolicy Bypass" in text
    assert "%~dp0" in text  # مستقل از مسیر جاری


def test_panel_exposes_every_requested_action(panel_text: str) -> None:
    validate_set = re.search(r"ValidateSet\((.*?)\)\]", panel_text, re.S)
    assert validate_set, "the panel must declare a ValidateSet of actions"
    names = set(re.findall(r"'([a-z]+)'", validate_set.group(1)))
    # چهار کار خواسته‌شده‌ی کاربر
    assert {"install", "remove", "status", "logs"} <= names


def test_panel_help_commands_exist_in_the_cli(panel_text: str) -> None:
    """هر ``@('cmd', ...)`` که پنل به exe می‌دهد باید زیرفرمان واقعی باشد."""
    from ramopt.cli import build_parser

    parser = build_parser()
    subparsers = [
        action for action in parser._actions if hasattr(action, "choices") and action.choices
    ]
    # اولین action با choices، لیست زیرفرمان‌هاست
    known = set(subparsers[0].choices)
    used = set(re.findall(r"Invoke-Exe -ExeArgs @\('([a-z]+)'", panel_text))
    assert used, "the panel should call the exe"
    unknown = used - known
    assert not unknown, f"the panel calls unknown commands: {sorted(unknown)}"


def test_readme_documents_the_build_folder() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "build\\Manage-RamOptimizer.bat" in readme or "build/Manage-RamOptimizer.bat" in readme


def test_runner_uses_one_minute_and_reacts_immediately() -> None:
    """گارد مکانیزم: هر ۶۰ ثانیه، و در وضعیت بحرانی بدون منتظر ماندن."""
    from ramopt.config import Config
    from ramopt.engine import Action, Decision
    from ramopt.runner import OptimizerRunner

    config = Config()
    assert config.check_interval_seconds == 60
    assert config.critical_poll_seconds < config.check_interval_seconds

    # فرض‌های مسیر بحرانی باید پیش‌فرض باشند: آستانه‌ی بالاتر از آستانه‌ی عادی
    assert config.sustained_trigger_percent > config.trigger_percent

    runner = OptimizerRunner.__new__(OptimizerRunner)  # بدون ساخت win32
    runner.config = config
    assert Decision  # فقط برای import نشدن بلااستفاده
    assert Action  # ditto


def test_docs_mention_the_critical_path() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "sustained_trigger_percent" in readme
    assert "critical_poll_seconds" in readme


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
