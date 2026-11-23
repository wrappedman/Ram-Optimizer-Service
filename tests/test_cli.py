# -*- coding: utf-8 -*-
"""تست خط فرمان: خروجی‌ها، کدهای خروج و رفتار روی غیر ویندوز."""

from __future__ import annotations

import json

import pytest

from ramopt import paths
from ramopt.cli import main


def test_version_command(capsys):
    assert main(["version"]) == 0
    output = capsys.readouterr().out
    assert "RAM Optimizer Service 2.0.0" in output
    assert "data dir" in output


def test_config_init_creates_file(tmp_path, capsys):
    target = tmp_path / "config.ini"
    assert main(["--config", str(target), "config", "--init"]) == 0
    assert target.is_file()
    content = target.read_text(encoding="utf-8")
    assert "[policy]" in content
    assert "trigger_percent = 75" in content


def test_config_validate_reports_errors(tmp_path, capsys):
    target = tmp_path / "bad.ini"
    target.write_text("[policy]\ntrigger_percent = 500\n", encoding="utf-8")
    assert main(["--config", str(target), "config", "--validate"]) == 1
    assert "problem" in capsys.readouterr().out


def test_config_validate_ok(tmp_path, capsys):
    target = tmp_path / "good.ini"
    assert main(["--config", str(target), "config", "--init"]) == 0
    assert main(["--config", str(target), "config", "--validate"]) == 0
    out = capsys.readouterr().out
    assert "is valid" in out
    assert str(target) in out  # مسیر نمایش‌داده‌شده باید همان فایل داده‌شده باشد


def test_config_show_prints_all_sections(capsys):
    assert main(["config", "--show"]) == 0
    out = capsys.readouterr().out
    for section in ("[general]", "[policy]", "[standby]", "[targets]", "[safety]", "[logging]"):
        assert section in out


def test_status_without_file(capsys):
    assert main(["status"]) == 1
    assert "not found" in capsys.readouterr().out


def test_status_reads_json(isolated_data_dir, capsys):
    payload = {
        "version": "2.0.0",
        "state": "running",
        "pid": 42,
        "last_action": "optimized",
        "last_reason": "آستانه رد شد",
        "memory": {
            "used_percent": 81.0,
            "available_mb": 2000,
            "commit_percent": 40,
            "standby_mb": 500,
        },
        "counters": {"purges": 2, "freed_mb": 300.0, "errors": 0, "cycles": 10},
    }
    with open(paths.status_file(), "w", encoding="utf-8") as handle:
        json.dump(payload, handle)

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "optimized" in out and "2 passes" in out

    capsys.readouterr()
    assert main(["status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["pid"] == 42


def test_log_command_tails_file(isolated_data_dir, capsys):
    with open(paths.log_file(), "w", encoding="utf-8") as handle:
        handle.write("line1\nline2\nline3\n")
    assert main(["log", "--lines", "2"]) == 0
    out = capsys.readouterr().out
    assert "line3" in out and "line1" not in out


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="فقط برای غیر ویندوز")
def test_windows_only_commands_fail_cleanly_on_posix(capsys):
    for argv in (
        ["test", "--dry-run"],
        ["console"],
        ["once"],
        ["service", "query"],
    ):
        assert main(argv) == 3, argv
    assert "only works on Windows" in capsys.readouterr().out


def test_unknown_command_exits_with_argparse_error():
    with pytest.raises(SystemExit) as excinfo:
        main(["nonsense"])
    assert excinfo.value.code == 2
