# -*- coding: utf-8 -*-
"""نصب/حذف/کنترل سرویس ویندوز.

چرا از ``win32serviceutil.HandleCommandLine`` مستقیم استفاده نمی‌کنیم؟

* آن مسیر، کلاس سرویس را از رشته‌ای که در رجیستری ذخیره می‌شود بارگذاری
  می‌کند (``<exe>.<ClassName>``)؛ برای exe ساخته‌شده با PyInstaller، نام
  ``__main__`` ممکن است به فایل exe اشاره نکند و نصب/استارت با خطای گمراه‌کننده
  شکست بخورد. این‌جا مستقیم و صریح نصب می‌کنیم.
* نسخه‌ی قبلی هیچ **failure action** تنظیم نمی‌کرد؛ اگر سرویس کرش می‌کرد،
  ویندوز هیچ تلاشی برای ری‌استارت نمی‌کرد. این‌جا سه بار ری‌استارت با تأخیر
  تصاعدی تنظیم می‌شود.
* ``delayed-auto`` استفاده می‌شود تا سرویس با طوفان سرویس‌های بوت رقابت نکند.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time

from ramopt import paths
from ramopt.version import (
    EVENT_SOURCE_NAME,
    SERVICE_DESCRIPTION,
    SERVICE_DISPLAY_NAME,
    SERVICE_NAME,
)

logger = logging.getLogger("RamOptimizer")

#: مسیر exe سرویس در build onedir: <release>\RamOptimizerService\RamOptimizerService.exe
SERVICE_EXE_NAME = "RamOptimizerService.exe"

#: SC_ACTION_TYPE
SC_ACTION_RESTART = 1

EXIT_OK = 0
EXIT_ERROR = 1


def _log(message: str) -> None:
    print(message)


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _python_service_exe() -> str:
    """در حالت اجرا با پایتون، pythonservice.exe همان چیزی است که باید ثبت شود."""
    import win32serviceutil

    return win32serviceutil.LocatePythonServiceExe()


def _command_line(exe: str, script: str | None) -> str:
    """خط فرمان ImagePath. اگر پایتون باشد، اسکریپت هم لازم است."""
    if script:
        return f'"{exe}" "{script}"'
    return f'"{exe}"'


def _run(args: list[str]) -> tuple[int, str]:
    """اجرای sc.exe و برگرداندن (کد خروج، خروجی)."""
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=30)
        return completed.returncode, (completed.stdout or "") + (completed.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        return EXIT_ERROR, str(exc)


def install(wait_seconds: int = 0) -> int:
    if sys.platform != "win32":
        _log("این دستور فقط روی ویندوز کار می‌کند.")
        return EXIT_ERROR

    import pywintypes
    import win32service

    exe = _python_service_exe() if not getattr(sys, "frozen", False) else sys.executable
    script = None
    if not getattr(sys, "frozen", False):
        script = os.path.join(_project_root(), "ram_optimizer_service.py")
        if not os.path.isfile(script):
            _log(f"[خطا] اسکریپت سرویس پیدا نشد: {script}")
            return EXIT_ERROR

    image_path = _command_line(exe, script)
    _log(f"نصب سرویس با ImagePath = {image_path}")

    hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
    try:
        # اگر سرویس از قبل هست: پیام واضح بده و پیشنهاد ارتقا بده
        try:
            hs_existing = win32service.OpenService(
                hscm, SERVICE_NAME, win32service.SERVICE_ALL_ACCESS
            )
            win32service.CloseServiceHandle(hs_existing)
            _log(
                f"سرویس «{SERVICE_NAME}» از قبل نصب است.\n"
                "برای ارتقا از نسخه‌ی جدید:  ramopt service remove  سپس  ramopt service install\n"
                "یا  ramopt service repair  (فقط مسیر exe و تنظیمات را اصلاح می‌کند)"
            )
            return EXIT_ERROR
        except pywintypes.error:
            pass  # سرویس وجود ندارد — خوب است

        hs = win32service.CreateService(
            hscm,
            SERVICE_NAME,
            SERVICE_DISPLAY_NAME,
            win32service.SERVICE_ALL_ACCESS,
            win32service.SERVICE_WIN32_OWN_PROCESS,
            win32service.SERVICE_AUTO_START,
            win32service.SERVICE_ERROR_NORMAL,
            image_path,
            None,
            0,
            None,  # هیچ وابستگی‌ای لازم نیست
            None,
            None,
        )
        try:
            win32service.ChangeServiceConfig2(
                hs, win32service.SERVICE_CONFIG_DESCRIPTION, SERVICE_DESCRIPTION
            )
            # شروع با تأخیر: سرویس‌های حیاتی سیستم اول بالا می‌آیند
            try:
                win32service.ChangeServiceConfig2(
                    hs, win32service.SERVICE_CONFIG_DELAYED_AUTO_START_INFO, True
                )
            except win32service.error as exc:  # pragma: no cover
                _log(f"⚠ delayed auto-start تنظیم نشد: {exc}. با auto معمولی ادامه می‌دهیم.")

            # self-healing: اگر سرویس کرش کرد، ویندوز دوباره بالا بیاوردش
            try:
                win32service.ChangeServiceConfig2(
                    hs,
                    win32service.SERVICE_CONFIG_FAILURE_ACTIONS,
                    {
                        "ResetPeriod": 24 * 60 * 60,  # شمارنده روزانه ریست شود
                        "RebootMsg": "",
                        "Command": "",
                        "Actions": [
                            (SC_ACTION_RESTART, 5_000),
                            (SC_ACTION_RESTART, 30_000),
                            (SC_ACTION_RESTART, 120_000),
                        ],
                    },
                )
            except win32service.error as exc:  # pragma: no cover
                _log(f"⚠ failure actions تنظیم نشد: {exc}")
            # failure actions روی «توقف با کد خطا» (نه فقط کرش) هم اعمال شود
            try:
                win32service.ChangeServiceConfig2(
                    hs, win32service.SERVICE_CONFIG_FAILURE_ACTIONS_FLAG, True
                )
            except (win32service.error, AttributeError):  # pragma: no cover
                pass
        finally:
            win32service.CloseServiceHandle(hs)
    finally:
        win32service.CloseServiceHandle(hscm)

    _register_event_source()
    _log("سرویس نصب شد (شروع خودکار با تأخیر + ری‌استارت خودکار در صورت خطا).")

    if wait_seconds >= 0:
        return start(wait_seconds or 20)
    return EXIT_OK


def _eventlog_key() -> str:
    return rf"HKLM\SYSTEM\CurrentControlSet\Services\EventLog\Application\{EVENT_SOURCE_NAME}"


def _register_event_source() -> None:
    """ثبت منبع رویداد تا در Event Viewer فیلترشدنی باشد."""
    backup_dir = os.path.join(
        os.environ.get("SystemRoot", "C:\\Windows"), "System32", "EventCreate.exe"
    )
    code, output = _run(
        [
            "reg",
            "add",
            _eventlog_key(),
            "/v",
            "EventMessageFile",
            "/t",
            "REG_EXPAND_SZ",
            "/d",
            backup_dir,
            "/f",
        ]
    )
    if code != 0:
        _log(
            "⚠ ثبت Event Source ناموفق "
            f"(سرویس همچنان از Event Log عمومی استفاده می‌کند): {output.strip()}"
        )
        return
    _run(
        [
            "reg",
            "add",
            _eventlog_key(),
            "/v",
            "TypesSupported",
            "/t",
            "REG_DWORD",
            "/d",
            "7",
            "/f",
        ]
    )
    logger.debug("Event source ثبت شد.")


def remove(wait_seconds: int = 15) -> int:
    if sys.platform != "win32":
        _log("این دستور فقط روی ویندوز کار می‌کند.")
        return EXIT_ERROR
    import pywintypes
    import win32service

    stop(wait_seconds)

    hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_ALL_ACCESS)
    try:
        try:
            hs = win32service.OpenService(hscm, SERVICE_NAME, win32service.SERVICE_ALL_ACCESS)
        except pywintypes.error:
            _log(f"سرویس «{SERVICE_NAME}» نصب نیست — کاری لازم نبود.")
            _remove_event_source()
            return EXIT_OK
        try:
            win32service.DeleteService(hs)
            _log("سرویس حذف شد.")
        finally:
            win32service.CloseServiceHandle(hs)
    finally:
        win32service.CloseServiceHandle(hscm)

    _remove_event_source()
    return EXIT_OK


def _remove_event_source() -> None:
    _run(["reg", "delete", _eventlog_key(), "/f"])


def _open_service():
    import win32service

    hscm = win32service.OpenSCManager(None, None, win32service.SC_MANAGER_CONNECT)
    return hscm, win32service.OpenService(hscm, SERVICE_NAME, win32service.SERVICE_ALL_ACCESS)


def start(wait_seconds: int = 20) -> int:
    if sys.platform != "win32":
        return EXIT_ERROR
    import pywintypes
    import win32service

    try:
        hscm, hs = _open_service()
    except pywintypes.error as exc:
        _log(f"[خطا] سرویس پیدا نشد ({exc.strerror}). اول نصب کنید: ramopt service install")
        return EXIT_ERROR
    try:
        try:
            win32service.StartService(hs, None)
            _log("دستور شروع ارسال شد…")
        except pywintypes.error as exc:
            if exc.winerror == 1056:  # ERROR_SERVICE_ALREADY_RUNNING
                _log("سرویس از قبل در حال اجراست.")
                return EXIT_OK
            raise
    finally:
        win32service.CloseServiceHandle(hs)
        win32service.CloseServiceHandle(hscm)

    state = _wait_for_state(win32service.SERVICE_RUNNING, wait_seconds)
    if state == win32service.SERVICE_RUNNING:
        _log("سرویس در حال اجراست. ✔")
        _print_log_hint()
        return EXIT_OK
    _log(
        "[خطا] سرویس در زمان مقرر به وضعیت RUNNING نرسید.\n"
        f"   لاگ: {paths.log_file()}\n"
        f"   کرش: {paths.crash_log_file()}\n"
        '   برای دیدن خطای دقیق:  ramopt test --dry-run  یا  "<exe>" debug'
    )
    return EXIT_ERROR


def stop(wait_seconds: int = 15) -> int:
    if sys.platform != "win32":
        return EXIT_ERROR
    import pywintypes
    import win32service

    try:
        hscm, hs = _open_service()
    except pywintypes.error:
        _log("سرویس نصب نیست.")
        return EXIT_OK
    try:
        try:
            win32service.ControlService(hs, win32service.SERVICE_CONTROL_STOP)
            _log("دستور توقف ارسال شد…")
        except pywintypes.error as exc:
            if exc.winerror == 1062:  # ERROR_SERVICE_NOT_ACTIVE
                _log("سرویس در حال اجرا نبود.")
                return EXIT_OK
            raise
        _wait_for_state(win32service.SERVICE_STOPPED, wait_seconds, hs=hs)
        _log("سرویس متوقف شد.")
        return EXIT_OK
    finally:
        win32service.CloseServiceHandle(hs)
        win32service.CloseServiceHandle(hscm)


def control(action: str, wait_seconds: int = 15) -> int:
    """pause / continue / query"""
    if sys.platform != "win32":
        return EXIT_ERROR
    import pywintypes
    import win32service

    code = {
        "pause": win32service.SERVICE_CONTROL_PAUSE,
        "continue": win32service.SERVICE_CONTROL_CONTINUE,
    }.get(action)
    try:
        hscm, hs = _open_service()
    except pywintypes.error:
        _log("سرویس نصب نیست.")
        return EXIT_ERROR
    try:
        if action == "query":
            status = win32service.QueryServiceStatus(hs)
            _log(f"وضعیت: {_state_name(status[1])}  (checkpoint {status[4]})")
            return EXIT_OK
        if code is None:
            _log(f"دستور ناشناخته: {action}")
            return EXIT_ERROR
        try:
            win32service.ControlService(hs, code)
            _log(f"دستور {action} ارسال شد.")
            return EXIT_OK
        except pywintypes.error as exc:
            _log(f"[خطا] {exc.strerror} ({exc.winerror})")
            return EXIT_ERROR
    finally:
        win32service.CloseServiceHandle(hs)
        win32service.CloseServiceHandle(hscm)


def _wait_for_state(target: int, seconds: int, hs=None) -> int | None:
    import pywintypes
    import win32service

    own_handles = False
    if hs is None:
        try:
            _hscm, hs = _open_service()
            own_handles = True
        except pywintypes.error:
            return None
    try:
        deadline = time.monotonic() + max(1, seconds)
        while time.monotonic() < deadline:
            status = win32service.QueryServiceStatus(hs)
            if status[1] == target:
                return target
            if target == win32service.SERVICE_RUNNING and status[1] == win32service.SERVICE_STOPPED:
                return status[1]
            time.sleep(0.5)
        return win32service.QueryServiceStatus(hs)[1] if hs else None
    finally:
        if own_handles:
            win32service.CloseServiceHandle(hs)


def _state_name(state: int) -> str:
    import win32service

    names = {
        win32service.SERVICE_STOPPED: "STOPPED",
        win32service.SERVICE_START_PENDING: "START_PENDING",
        win32service.SERVICE_STOP_PENDING: "STOP_PENDING",
        win32service.SERVICE_RUNNING: "RUNNING",
        win32service.SERVICE_CONTINUE_PENDING: "CONTINUE_PENDING",
        win32service.SERVICE_PAUSE_PENDING: "PAUSE_PENDING",
        win32service.SERVICE_PAUSED: "PAUSED",
    }
    return names.get(state, f"UNKNOWN({state})")


def _print_log_hint() -> None:
    _log(f"لاگ: {paths.log_file()}   |   وضعیت: {paths.status_file()}")


def handle_service_command(action: str, wait: int = 15) -> int:
    """نقطه‌ی ورود دستور ``ramopt service <action>``."""
    if sys.platform != "win32":
        _log("دستورهای سرویس فقط روی ویندوز کار می‌کنند.")
        return EXIT_ERROR

    if action == "install":
        return install(wait_seconds=wait)
    if action == "remove":
        return remove(wait_seconds=wait)
    if action == "start":
        return start(wait_seconds=wait)
    if action == "stop":
        return stop(wait_seconds=wait)
    if action == "restart":
        stop(wait_seconds=wait)
        return start(wait_seconds=wait)
    if action in ("pause", "continue", "query"):
        return control(action, wait_seconds=wait)
    if action == "repair":
        return repair()
    _log(f"دستور ناشناخته: {action}")
    return EXIT_ERROR


def repair() -> int:
    """اصلاح مسیر exe و تنظیمات یک نصب موجود (برای ارتقای in-place)."""
    if sys.platform != "win32":
        return EXIT_ERROR
    import pywintypes
    import win32service

    exe = sys.executable if getattr(sys, "frozen", False) else _python_service_exe()
    script = None
    if not getattr(sys, "frozen", False):
        script = os.path.join(_project_root(), "ram_optimizer_service.py")
    image_path = _command_line(exe, script)

    try:
        hscm, hs = _open_service()
    except pywintypes.error:
        _log("سرویس نصب نیست؛ از install استفاده کنید.")
        return EXIT_ERROR
    try:
        win32service.ChangeServiceConfig(
            hs,
            win32service.SERVICE_NO_CHANGE,
            win32service.SERVICE_AUTO_START,
            win32service.SERVICE_NO_CHANGE,
            image_path,
            None,
            0,
            None,
            None,
            None,
            SERVICE_DISPLAY_NAME,
        )
        win32service.ChangeServiceConfig2(
            hs, win32service.SERVICE_CONFIG_DESCRIPTION, SERVICE_DESCRIPTION
        )
        win32service.ChangeServiceConfig2(
            hs,
            win32service.SERVICE_CONFIG_FAILURE_ACTIONS,
            {
                "ResetPeriod": 86400,
                "RebootMsg": "",
                "Command": "",
                "Actions": [(SC_ACTION_RESTART, 5_000), (SC_ACTION_RESTART, 30_000)],
            },
        )
        _log(f"سرویس اصلاح شد: {image_path}")
        _register_event_source()
        return EXIT_OK
    finally:
        win32service.CloseServiceHandle(hs)
        win32service.CloseServiceHandle(hscm)


__all__ = [
    "EXIT_ERROR",
    "EXIT_OK",
    "control",
    "handle_service_command",
    "install",
    "remove",
    "repair",
    "start",
    "stop",
]
