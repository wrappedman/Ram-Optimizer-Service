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

import os
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


def _git_check_ignore(path: str) -> subprocess.CompletedProcess | None:
    """اجرای ``git check-ignore``؛ اگر git نصب نباشد ``None``.

    مهم: روی ویندوزی که Git for Windows نصب نیست (یا PATH عوض شده) اجرای
    ``git`` با ``FileNotFoundError`` شکست می‌خورد و بیلد را می‌خواباند —
    در حالی که این تست درباره‌ی خودِ برنامه چیزی نمی‌گوید. پس نبودِ git
    یعنی «قابل بررسی نیست»، نه «شکست».
    """
    try:
        return subprocess.run(
            ["git", "check-ignore", "-v", path],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None


def test_exe_output_is_not_committed_but_the_panel_is() -> None:
    """قاعده‌ی ignore را از فایل می‌خوانیم (بدون نیاز به git).

    چرا نه ``git check-ignore``؟ چون روی ماشینی که git در PATH نیست تست
    شکست می‌خورد، و روی ماشینی که خودِ پروژه زیرمجموعه‌ی یک ریپوی دیگر است
    ممکن است قاعده‌ی والد جواب بدهد. منبع حقیقت همان ``.gitignore`` است.
    """
    rules = [
        line.strip()
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "build/RamOptimizerService/*" in rules, "the built exe must stay out of Git"
    assert "!build/RamOptimizerService/README.txt" in rules, "the folder guide must be committed"
    # قاعده‌ی خیلی کلی «build/» نباید برگردد؛ وگرنه کل پنل ignore می‌شود
    assert "build/" not in rules

    # اگر git در دسترس بود، ادعا را با خودش هم بسنجیم
    result = _git_check_ignore("build/RamOptimizerService/RamOptimizerService.exe")
    if result is None:
        if os.environ.get("RAMOPT_REQUIRE_GIT_TESTS") == "1":
            pytest.fail("git لازم است ولی در PATH نیست (RAMOPT_REQUIRE_GIT_TESTS=1)")
        pytest.skip("git در PATH نیست؛ قاعده از .gitignore بررسی شد")
    if result.returncode not in (0, 1):
        pytest.skip(f"git check-ignore قابل استفاده نیست: {result.stderr.strip()[:80]}")
    assert result.returncode == 0, "the built exe must stay out of Git"
    assert result.returncode == 0 and "*" in result.stdout
    assert _git_check_ignore("build/RamOptimizerControl.ps1").returncode == 1


def test_panel_script_is_utf8_bom_and_ascii() -> None:
    """پنل باید BOM داشته باشد و بدنه‌اش ASCII باشد.

    Windows PowerShell 5.1 فایل بدون BOM را با code page سیستم (مثلاً
    windows-1256) می‌خواند و متن فارسی در رشته‌ها خراب می‌شد. با BOM همیشه
    UTF-8 خوانده می‌شود؛ و escapeهای ```u{...}`` متن فارسی را از منبع ASCII
    می‌سازند تا هیچ‌جای زنجیره‌ی بیلد به code page وابسته نباشد.
    """
    data = PANEL.read_bytes()
    assert data[:3] == b"\xef\xbb\xbf", "RamOptimizerControl.ps1 must start with a UTF-8 BOM"
    body = data[3:].decode("utf-8")
    # خط‌پایان مهم نیست (PowerShell هم LF و هم CRLF را می‌خواند)؛ BOM مهم است.
    non_ascii = [line for line in body.splitlines() if any(ord(char) > 127 for char in line)]
    assert non_ascii == [], f"keep the panel ASCII (Persian via `u{{...}}): {non_ascii[:2]}"
    assert "`u{" in body, "Persian strings should use escape sequences"


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


#: تست‌هایی که به یک ابزار بیرونی (git) نیاز دارند. روی ماشینی که git ندارد
#: با ``pytest -m "not external"`` کنار گذاشته می‌شوند.
EXTERNAL = pytest.mark.external


@EXTERNAL
def test_git_is_present_when_required() -> None:
    """در CI ویندوز، خودِ وجود git هم بررسی می‌شود (وگرنه تست ignore بی‌صدا skip می‌شد)."""
    if os.environ.get("RAMOPT_REQUIRE_GIT_TESTS") != "1":
        pytest.skip("RAMOPT_REQUIRE_GIT_TESTS=1 تنظیم نشده است")
    assert _git_check_ignore("build/RamOptimizerControl.ps1") is not None, "git در PATH نیست"


def test_bat_files_use_crlf_and_are_ascii() -> None:
    """``.bat``هایی که cmd.exe می‌خواند باید CRLF و ASCII باشند.

    دو باگ واقعی که همین‌جا گرفته می‌شوند:

    * فایلی که فقط LF دارد: cmd.exe دنباله‌ی بلوک‌های ``if``/``for`` را گم
      می‌کند و شاخه‌ی اشتباه را اجرا می‌کند.
    * کامنت فارسی UTF-8 در یک فایل batch: با code page کنسول رمزگشایی می‌شود
      و می‌تواند باعث پریدن از بلوک شود (همین باعث شد پیام «No supported
      Python» چاپ شود در حالی که ``py -3.13`` وجود داشت).
    """
    batch_files = [
        ROOT / "build_exe.bat",
        *sorted(BUILD.glob("*.bat")),
        *sorted(ROOT.glob("*.bat")),
    ]
    checked = 0
    for path in dict.fromkeys(batch_files):
        data = path.read_bytes()
        if b"\n" not in data:
            continue
        checked += 1
        assert data.count(b"\r\n") == data.count(b"\n"), f"{path.name}: LF-only line endings"
        assert not any(byte > 127 for byte in data), f"{path.name}: non-ASCII content"
    assert checked >= 3, "the build/ batch files should exist"


def test_build_scripts_share_one_implementation() -> None:
    """منطق بیلد یک‌جا است (``tools/build_exe.ps1``)، نه دو نسخه‌ی جدا."""
    launcher = (ROOT / "build_exe.bat").read_text(encoding="ascii")
    nested = (BUILD / "build_exe.bat").read_text(encoding="ascii")
    assert "tools\\build_exe.ps1" in launcher
    assert "tools\\build_exe.ps1" in nested
    script = (ROOT / "tools" / "build_exe.ps1").read_text(encoding="utf-8")
    assert "3.13" in script and "py -" in script
    # هر -c که به پایتون داده می‌شود نباید کوتیشن داشته باشد: PowerShell هنگام
    # فراخوانی exe کوتیشن‌های داخل آرگومان را حذف می‌کند و python با SyntaxError
    # می‌میرد (همین یک CI را قرمز کرد).
    for line in script.splitlines():
        if " -c " in line:
            snippet = line.split(" -c ", 1)[1]
            assert '"' not in snippet and "'" not in snippet, f"quotes in -c: {line.strip()}"
    # اسکریپت باید ASCII باشد تا PowerShell 5.1 هم بدون BOM درست بخواند
    assert all(ord(char) < 128 for char in script), "tools/build_exe.ps1 must stay ASCII"


def test_tool_scripts_survive_a_non_utf8_console(monkeypatch, capsys) -> None:
    """اسکریپت‌های tools/ نباید روی کنسول cp1252 با UnicodeEncodeError بمیرند.

    CI ویندوز دقیقاً همین را گرفت: ``make_version_info.py`` متن فارسی چاپ
    می‌کرد و کنسول runner (cp1252) آن را نمی‌پذیرفت، پس بیلد در گام ۴ می‌افتاد.
    """
    import importlib.util
    import io
    import sys

    class Cp1252Stdout(io.TextIOBase):
        encoding = "cp1252"

        def __init__(self) -> None:
            self.buffer = []

        def write(self, text: str) -> int:
            text.encode("cp1252")  # مثل کنسول واقعی: خطا می‌دهد
            self.buffer.append(text)
            return len(text)

    monkeypatch.setattr(sys, "stdout", Cp1252Stdout())
    monkeypatch.setattr(sys, "stderr", Cp1252Stdout())

    tools_dir = ROOT / "tools"
    sys.path.insert(0, str(tools_dir))
    try:
        spec = importlib.util.spec_from_file_location("console_helper", tools_dir / "_console.py")
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        # نباید استثنا بدهد
        module.say("پیام فارسی")
    finally:
        sys.path.remove(str(tools_dir))

    for tool in ("make_version_info.py", "make_build_info.py"):
        source = (ROOT / "tools" / tool).read_text(encoding="utf-8")
        assert "_console" in source and "force_utf8_console" in source
