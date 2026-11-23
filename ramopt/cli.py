# -*- coding: utf-8 -*-
"""خط فرمان برنامه: ``ramopt``.

دستورها::

    ramopt version                 نسخه و اطلاعات محیط
    ramopt status                  وضعیت فعلی از status.json
    ramopt config --init           ساخت فایل config.ini نمونه
    ramopt config --show           نمایش پیکربندی مؤثر
    ramopt config --validate       بررسی فایل پیکربندی
    ramopt test [--force]          یک چرخه‌ی واقعی (مثل سرویس) و نمایش نتیجه
    ramopt test --dry-run          فقط تصمیم‌گیری، بدون هیچ تغییری در سیستم
    ramopt console                 اجرای دائمی در پیش‌زمینه (بدون نصب سرویس)
    ramopt once                    یک چرخه‌ی واقعی بدون خروجی اضافه (برای Task)
    ramopt service install         نصب سرویس (auto-delayed + failure actions)
    ramopt service remove|start|stop|restart|pause|continue|query
    ramopt log [--lines N]         نمایش انتهای لاگ
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from ramopt import paths
from ramopt.config import as_dict, load_config, write_default_config
from ramopt.version import build_info

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOT_WINDOWS = 3


# ----------------------------------------------------------------------------
# کمکی‌ها
# ----------------------------------------------------------------------------


#: سینتکس قدیمی نسخه‌ی ۱: exe install --startup auto
#: توجه: "pause" عمداً این‌جا نیست؛ فرمان pause مربوط به سرویس در حال اجراست
#: و به شکل «service pause» نوشته می‌شود.
_SERVICE_ACTIONS = {
    "install",
    "remove",
    "start",
    "stop",
    "restart",
    "continue",
    "query",
    "repair",
}
_LEGACY_SERVICE_OPTIONS = {"--startup", "--username", "--password", "--wait"}


def normalize_argv(argv: list[str]) -> list[str]:
    """پشتیبانی از دستورهای نسخه‌ی ۱ بدون شکستن فرم جدید.

    * ``install --startup auto`` → ``service install`` (گزینه‌ها حذف می‌شوند)
    * ``install`` / ``remove`` / ``start`` / ``stop`` … → ``service <action>``
    """
    args = list(argv)
    if not args:
        return args
    if args[0] in _SERVICE_ACTIONS:
        return ["service", args[0]]
    if args[0] in _LEGACY_SERVICE_OPTIONS:
        return ["service", "install"]
    return args


def _force_utf8_console() -> None:
    """کنسول ویندوز اغلب cp1256/cp437 است و چاپ متن فارسی را می‌شکند."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def _print(text: str = "") -> None:
    """چاپ امن (در exe با کنسول نامعتبر نمی‌شکند)."""
    try:
        print(text)
    except (OSError, UnicodeEncodeError, ValueError):
        try:
            data = (text + "\n").encode("utf-8", "replace")
            sys.stdout.buffer.write(data)
        except Exception:
            pass


def _json_print(data) -> None:
    _print(json.dumps(data, ensure_ascii=False, indent=2))


def _require_windows() -> bool:
    if sys.platform != "win32":
        _print("خطا: این دستور فقط روی ویندوز کار می‌کند.")
        return False
    return True


def _load(args):
    config, issues = load_config(getattr(args, "config", None) or None)
    return config, issues


def _report_issues(issues, verbose: bool = True) -> None:
    for issue in issues:
        if verbose:
            _print(f"⚠ [{issue.section}] {issue.key} = {issue.value!r}: {issue.message}")


def _apply_log_level(config) -> None:
    """برای دستورهای مستقیم، لاگ روی کنسول + فایل با سطح پیکربندی."""
    from ramopt.logging_setup import setup_logging

    setup_logging(config, console=True)


# ----------------------------------------------------------------------------
# دستورها
# ----------------------------------------------------------------------------


def cmd_version(_args) -> int:
    info = build_info()
    _print(f"RAM Optimizer Service {info['version']}")
    for key in ("python", "frozen", "platform", "executable"):
        _print(f"  {key:10s}: {info[key]}")
    _print(f"  data dir  : {paths.data_dir()}")
    return EXIT_OK


def cmd_status(args) -> int:
    from ramopt.status import read_status

    data = read_status()
    if data is None:
        _print("status.json پیدا نشد — سرویس هرگز اجرا نشده یا پوشه‌ی داده‌ها متفاوت است.")
        _print(f"مسیر موردانتظار: {paths.status_file()}")
        return EXIT_ERROR
    if args.json:
        _json_print(data)
        return EXIT_OK

    memory: dict = data.get("memory") or {}
    counters: dict = data.get("counters") or {}
    _print(f"نسخه           : {data.get('version')}")
    _print(f"وضعیت          : {data.get('state')}   (PID {data.get('pid')})")
    _print(f"شروع           : {data.get('started_at')}")
    _print(f"آخرین چرخه     : {data.get('last_cycle_at')}")
    _print(f"آخرین اقدام    : {data.get('last_action')} — {data.get('last_reason')}")
    _print(
        "حافظه          : "
        f"{memory.get('used_percent', '?')}% مصرف | "
        f"{memory.get('available_mb', '?')}MB آزاد | "
        f"commit {memory.get('commit_percent', '?')}% | "
        f"standby {memory.get('standby_mb', '?')}MB"
    )
    _print(
        f"شمارنده‌ها      : {counters.get('purges', 0)} پاک‌سازی | "
        f"{counters.get('freed_mb', 0)}MB آزادشده | "
        f"{counters.get('errors', 0)} خطا | {counters.get('cycles', 0)} چرخه"
    )
    if data.get("next_allowed_at"):
        _print(f"پاک‌سازی بعدی  : از {data.get('next_allowed_at')} به بعد")
    for err in data.get("recent_errors") or []:
        _print(f"  آخرین خطا: {err.get('at')} — {err.get('message')}")
    return EXIT_OK


def cmd_config(args) -> int:
    if args.init:
        path = write_default_config(args.config or None, overwrite=args.force)
        action = "به‌روزرسانی شد" if args.force else "آماده است"
        _print(f"فایل پیکربندی {action}: {path}")
        return EXIT_OK

    config, issues = _load(args)
    effective_path = args.config or paths.config_file()
    if args.validate:
        if issues:
            _print(f"{len(issues)} مشکل در فایل پیکربندی:")
            _report_issues(issues)
            return EXIT_ERROR
        if not os.path.isfile(effective_path):
            _print(f"فایل پیکربندی وجود ندارد: {effective_path} (مقادیر پیش‌فرض استفاده می‌شوند)")
            return EXIT_OK
        _print("فایل پیکربندی معتبر است. ✔")
        _print(f"مسیر: {effective_path}")
        return EXIT_OK

    _report_issues(issues)
    data = as_dict(config)
    for section, values in _grouped(data).items():
        _print(f"[{section}]")
        for key, value in values.items():
            if isinstance(value, list):
                value = ", ".join(value)
            _print(f"  {key} = {value}")
        _print()
    _print(f"مسیر فایل پیکربندی: {effective_path}")
    return EXIT_OK


def cmd_test(args) -> int:
    """یک چرخه‌ی آزمایشی. با ``--dry-run`` هیچ تغییری در سیستم داده نمی‌شود."""
    if not _require_windows():
        return EXIT_NOT_WINDOWS

    from ramopt import memory as memory_mod
    from ramopt import win32
    from ramopt.engine import OptimizerEngine

    config, issues = _load(args)
    _report_issues(issues)
    _apply_log_level(config)

    if args.force:
        # برای تست دستی: cooldown و تأخیر شروع را نادیده بگیر
        config = _with_overrides(
            config,
            startup_delay_seconds=0,
            cooldown_seconds=0,
            max_purges_per_hour=0,
            skip_on_battery=False,
            quiet_hours="",
            skip_when_fullscreen=not args.include_fullscreen,
        )

    api = win32.Win32Api()
    if not api.available:
        _print(f"خطا: {api.load_error}")
        return EXIT_ERROR

    from ramopt.logging_setup import log_startup_banner

    log_startup_banner(config)
    for privilege in ("SeProfileSingleProcessPrivilege", "SeIncreaseQuotaPrivilege"):
        if not api.enable_privilege(privilege):
            _print(f"⚠ اختیار {privilege} فعال نشد — CMD را با «Run as administrator» باز کنید.")

    provider = memory_mod.PsutilProcessProvider()
    reading = memory_mod.measure(api, provider)

    if args.dry_run:
        engine = OptimizerEngine(config, api, provider)
        decision = engine.decide(reading)
        _print("—— حالت dry-run: هیچ تغییری در سیستم داده نمی‌شود ——")
        _print(
            f"حافظه: {reading.used_percent:.1f}% مصرف | {reading.available_mb:.0f}MB آزاد | "
            f"commit {reading.commit_percent:.0f}% | standby "
            f"{'?' if reading.standby_mb is None else f'{reading.standby_mb:.0f}MB'} | "
            f"{reading.process_count} پروسه"
        )
        _print(f"تصمیم: {decision.action.value} | حالت: {decision.mode.value}")
        _print(f"دلیل : {decision.reason}")
        candidates = [
            p
            for p in provider.list_processes()
            if not config.is_excluded(p.name)
            and p.working_set_bytes >= config.min_process_ws_mb * memory_mod.MB
            and p.pid > 4
        ]
        candidates.sort(key=lambda p: p.working_set_bytes, reverse=True)
        if config.max_processes:
            candidates = candidates[: config.max_processes]
        _print(f"\nپروسه‌هایی که پاک می‌شدند ({len(candidates)}):")
        for proc in candidates[:20]:
            _print(
                f"  {proc.working_set_bytes / memory_mod.MB:9.1f}MB  {proc.name}  (PID {proc.pid})"
            )
        if len(candidates) > 20:
            _print(f"  … و {len(candidates) - 20} پروسه‌ی دیگر")
        return EXIT_OK

    engine = OptimizerEngine(config, api, provider)
    result = engine.run_cycle(force=args.force)
    payload: dict = result.as_dict()
    if args.json:
        _json_print(payload)
    else:
        _print(f"اقدام : {payload['action']} — {payload['reason']}")
        _print(
            f"حافظه : {payload.get('used_percent_before')}% → {payload.get('used_percent_after')}% | "
            f"آزاد {payload.get('available_mb_before')}MB → {payload.get('available_mb_after')}MB"
        )
        if payload.get("trim"):
            trim: dict = payload["trim"]
            _print(
                f"trim  : {trim['trimmed']}/{trim['considered']} پروسه | "
                f"{trim['freed_mb']}MB Working Set | دسترسی رد شد: {trim['denied']} | "
                f"خطا: {trim['failed']}"
            )
            for item in trim.get("biggest", []):
                _print(f"         {item['mb']:8.1f}MB  {item['name']}")
        if payload.get("purge"):
            purge: dict = payload["purge"]
            status_text = (
                "خالی شد" if purge["purged"] else (purge["error"] or purge["skipped_reason"])
            )
            _print(
                f"standby: {status_text} | "
                f"{purge['standby_before_mb']}MB → {purge['standby_after_mb']}MB"
            )
        _print(f"زمان  : {payload['duration_ms']} میلی‌ثانیه")
        if payload["action"] == "skipped":
            _print("نتیجه : هیچ تغییری اعمال نشد (دلیل بالا).")
    return EXIT_OK if payload["action"] != "skipped" or args.dry_run else EXIT_ERROR


def cmd_console(args) -> int:
    if not _require_windows():
        return EXIT_NOT_WINDOWS
    from ramopt.logging_setup import install_crash_handlers
    from ramopt.runner import OptimizerRunner

    install_crash_handlers()
    config, issues = _load(args)
    _report_issues(issues)
    _apply_log_level(config)
    runner = OptimizerRunner(config=config)
    try:
        runner.run_forever()
    except KeyboardInterrupt:
        runner.stop()
        _print("متوقف شد.")
    return EXIT_OK


def cmd_once(args) -> int:
    """اجرای یک چرخه بدون نصب سرویس (برای استفاده در Task Scheduler)."""
    if not _require_windows():
        return EXIT_NOT_WINDOWS
    from ramopt.logging_setup import install_crash_handlers, setup_logging
    from ramopt.runner import OptimizerRunner

    install_crash_handlers()
    config, issues = _load(args)
    setup_logging(config)
    _report_issues(issues, verbose=False)
    runner = OptimizerRunner(config=config)
    runner.prepare()
    runner.run_once()
    result = runner.engine.last_result
    return EXIT_OK if result is not None and result.action.value != "error" else EXIT_ERROR


def _write_command(command: str) -> int:
    """نوشتن ``command.json`` برای سرویس در حال اجرا (pause/resume/reload)."""
    import json

    target = os.path.join(paths.data_dir(), "command.json")
    try:
        os.makedirs(paths.data_dir(), exist_ok=True)
        temp = target + ".tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump({"command": command, "created_at": _now_iso()}, handle)
        os.replace(temp, target)
    except OSError as exc:
        _print(f"خطا: نوشتن {target} ناموفق بود: {exc}")
        _print("برای این کار باید با دسترسی Administrator اجرا شود.")
        return EXIT_ERROR
    _print(f"دستور «{command}» ثبت شد. سرویس حداکثر در بررسی بعدی آن را اعمال می‌کند.")
    _print(f"فایل: {target}")
    return EXIT_OK


def _now_iso() -> str:
    import datetime

    return datetime.datetime.now().isoformat(timespec="seconds")


def cmd_pause(_args) -> int:
    return _write_command("pause")


def cmd_resume(_args) -> int:
    return _write_command("resume")


def cmd_reload(_args) -> int:
    return _write_command("reload")


def cmd_verify(args) -> int:
    """بررسی عملی سناریو: هر یک دقیقه + واکنش فوری در وضعیت بحرانی.

    فقط اندازه‌گیری می‌کند؛ هیچ trim/purge ای انجام نمی‌شود (برای همین
    ``--dry-run`` اجباری است). با ``--simulate-critical`` آستانه‌ی بحرانی
    موقتاً پایین می‌آید تا روی ماشین سالم هم مسیر فوری دیده شود.
    """
    import time

    from ramopt import memory as memory_mod
    from ramopt import paths
    from ramopt.config import Config, load_config

    config, issues = load_config(getattr(args, "config", None) or None)
    for issue in issues:
        _print(f"⚠ [{issue.section}] {issue.key}: {issue.message}")

    interval = config.check_interval_seconds
    critical_poll = config.critical_poll_seconds
    threshold = config.sustained_trigger_percent

    _print("سناریوی درخواستی")
    _print(f"  ۱) آزادسازی خودکار هر {interval} ثانیه در حالت عادی")
    _print(f"  ۲) به‌محض رسیدن مصرف به {threshold}% → همان لحظه (بدون انتظار)")
    _print(f"     حتی وسط خواب یک‌دقیقه‌ای: پایش سبک هر {config.critical_probe_seconds} ثانیه")
    _print(f"     و بعد از آن بررسی هر {critical_poll} ثانیه تا پایین آمدن")
    _print("")
    _print("پیکربندی مؤثر")
    _print(f"  check_interval_seconds    = {interval}")
    _print(f"  critical_poll_seconds     = {critical_poll}")
    _print(f"  critical_probe_seconds    = {config.critical_probe_seconds}")
    _print(f"  trigger_percent           = {config.trigger_percent}")
    _print(f"  sustained_trigger_percent = {threshold}")
    _print(f"  sustained_polls           = {config.sustained_polls}")
    _print(f"  cooldown_seconds          = {config.cooldown_seconds}")
    _print("")

    reading = memory_mod.measure(_api_for_verify())
    if reading.snapshot is None:
        _print("خطا: خواندن وضعیت حافظه ممکن نیست.")
        return EXIT_ERROR

    used = reading.used_percent
    total_mb = reading.snapshot.total_bytes / (1024 * 1024)
    pending = "?" if reading.standby_mb is None else f"{reading.standby_mb:.0f}"
    _print("وضعیت فعلی حافظه")
    _print(f"  مصرف              : {used:.1f}%")
    _print(f"  آزاد              : {reading.available_mb:.0f}MB از {total_mb:.0f}MB")
    _print(f"  Standby (قابل آزادسازی): {pending}MB")
    _print("")

    over_normal = used >= config.trigger_percent
    over_critical = used >= threshold
    _print("نتیجه‌ی ارزیابی")
    _print(f"  آستانه‌ی عادی ({config.trigger_percent}%) رد شده؟ {'بله' if over_normal else 'خیر'}")
    if over_critical:
        _print(f"  آستانه‌ی بحرانی ({threshold}%) رد شده → چرخه‌ی بعد فوراً اجرا می‌شود.")
        _print(f"  فاصله‌ی بررسی بعدی: {critical_poll} ثانیه.")
    else:
        _print(f"  بحرانی نیست → فاصله‌ی بررسی بعدی: {interval} ثانیه.")
        _print(
            f"  اگر مصرف به {threshold}% برسد، بدون انتظار برای این {interval} ثانیه اجرا می‌شود."
        )

    if args.simulate_critical:
        _print("")
        _print("شبیه‌سازی مسیر بحرانی (بدون تغییر سیستم: هیچ trim/purge ای اجرا نمی‌شود)")
        from ramopt.engine import Action as _Action
        from ramopt.engine import OptimizerEngine

        simulated = Config(**{**config.__dict__, "sustained_trigger_percent": 1})
        engine = OptimizerEngine(simulated, _api_for_verify())
        decision = engine.decide(reading)
        if not decision.critical:
            _print(f"  ⚠ مسیر بحرانی فعال نشد: {decision.reason}")
            _print("    (مانع محیطی مثل pause / تمام‌صفحه / باتری یا نبود آستانه)")
            return EXIT_ERROR
        _print(f"  مصرف فرضی بالای آستانه → تصمیم: {decision.action.value} (فوری)")
        _print("  ترتیب زمانی که سرویس اجرا می‌کند:")
        _print(f"    T+0s    خواندن حافظه → عبور از {threshold}% → همان لحظه پاس آزادسازی")
        _print("    T+0s    تصمیم با critical=True (cooldown و سقف ساعتی دور زده می‌شوند)")
        _print(f"    T+{critical_poll}s    بررسی بعدی (نه {interval}s)")
        _print(f"    T+{2 * critical_poll}s    بررسی بعدی … تا وقتی مصرف زیر {threshold}% بیاید")
        _print(f"    سپس    بازگشت به فاصله‌ی عادی {interval}s")
        assert decision.action is _Action.OPTIMIZED

    if args.watch > 0:
        _print("")
        _print(f"پایش {args.watch} ثانیه‌ای: هر تغییر وضعیت بحرانی گزارش می‌شود.")
        _print(f"  (سرویس واقعی هر {interval} ثانیه یک بار تصمیم می‌گیرد)")
        last = None
        deadline = time.monotonic() + args.watch
        while time.monotonic() < deadline:
            current = memory_mod.measure(_api_for_verify())
            if current.snapshot is not None:
                state = current.used_percent >= threshold
                if state != last:
                    stamp = time.strftime("%H:%M:%S")
                    label = "بحرانی" if state else "عادی"
                    _print(f"  [{stamp}] {current.used_percent:5.1f}% → {label}")
                    last = state
            time.sleep(min(2.0, max(0.5, critical_poll)))

    _print("")
    _print(f"لاگ‌ها: {paths.log_file()}")
    _print("برای دیدن رفتار واقعی: ramopt log --lines 50  یا  build\\Manage-RamOptimizer.bat logs")
    return EXIT_OK


def _api_for_verify():
    """همان API واقعی (روی ویندوز)؛ روی لینوکس/تست‌ها معادل psutil."""
    from ramopt import win32

    return win32.Win32Api() if sys.platform == "win32" else _PosixApi()


class _PosixApi:
    """معادل کوچک ``Win32Api`` با psutil — فقط برای ``ramopt verify`` در توسعه.

    سرویس واقعی هرگز از این استفاده نمی‌کند؛ اگر روی لینوکس ``verify`` را اجرا
    کنید همین استفاده می‌شود تا سناریو بدون ویندوز هم قابل بررسی باشد.
    """

    available = True
    load_error = ""

    def __init__(self) -> None:
        import psutil

        self._psutil = psutil
        self.monotonic_ms = lambda: int(__import__("time").monotonic() * 1000)

    def memory_snapshot(self):
        from ramopt.win32 import MemorySnapshot

        vm = self._psutil.virtual_memory()
        swap = self._psutil.swap_memory()
        commit_limit = int(vm.total + swap.total)
        commit_used = int(vm.used + swap.used)
        return MemorySnapshot(
            total_bytes=int(vm.total),
            available_bytes=int(vm.available),
            used_percent=float(vm.percent),
            commit_used_bytes=commit_used,
            commit_limit_bytes=commit_limit,
            commit_percent=round(commit_used * 100.0 / commit_limit, 1) if commit_limit else 0.0,
        )

    def standby_bytes(self) -> int | None:
        return None

    def user_notification_state(self) -> None:
        return None

    def is_on_battery(self) -> bool:
        return False


def cmd_log(args) -> int:
    log_path = paths.log_file()
    if not os.path.isfile(log_path):
        _print(f"فایل لاگ وجود ندارد: {log_path}")
        return EXIT_ERROR
    with open(log_path, encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    for line in lines[-args.lines :]:
        _print(line.rstrip("\n"))
    return EXIT_OK


def cmd_service(args) -> int:
    if not _require_windows():
        return EXIT_NOT_WINDOWS
    from ramopt.service_admin import handle_service_command

    return handle_service_command(args.action, wait=args.wait)


# ----------------------------------------------------------------------------
# ساختار آرگومان‌ها
# ----------------------------------------------------------------------------


def _with_overrides(config, **overrides):
    import dataclasses

    return dataclasses.replace(config, **overrides)


def _grouped(data: dict) -> dict[str, dict]:
    """گروه‌بندی مقادیر Config برای نمایش."""
    mapping = {
        "general": [
            "check_interval_seconds",
            "startup_delay_seconds",
            "critical_poll_seconds",
            "critical_probe_seconds",
        ],
        "policy": [
            "trigger_percent",
            "reset_percent",
            "cooldown_seconds",
            "max_purges_per_hour",
            "min_available_mb",
            "sustained_trigger_percent",
            "sustained_polls",
        ],
        "standby": ["purge_standby_list", "min_free_mb_after_trim", "flush_modified_list"],
        "targets": ["min_process_ws_mb", "max_processes", "exclude", "exclude_patterns"],
        "safety": ["skip_when_fullscreen", "skip_on_battery", "quiet_hours"],
        "logging": ["log_level"],
    }
    return {
        section: {key: data[key] for key in keys if key in data}
        for section, keys in mapping.items()
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ramopt",
        description="RAM Optimizer Service — آزادسازی حافظه فقط وقتی واقعاً لازم است.",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="مسیر فایل پیکربندی جایگزین (پیش‌فرض: <ProgramData>\\RamOptimizer\\config.ini)",
    )
    parser.add_argument("--version", action="version", version=_version_text())
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version", help="نمایش نسخه و اطلاعات محیط").set_defaults(
        func=cmd_version
    )

    status_parser = subparsers.add_parser("status", help="نمایش وضعیت فعلی")
    status_parser.add_argument("--json", action="store_true", help="خروجی JSON")
    status_parser.set_defaults(func=cmd_status)

    config_parser = subparsers.add_parser("config", help="مدیریت فایل پیکربندی")
    group = config_parser.add_mutually_exclusive_group()
    group.add_argument("--init", action="store_true", help="ساخت config.ini نمونه")
    group.add_argument("--show", action="store_true", help="نمایش پیکربندی مؤثر (پیش‌فرض)")
    group.add_argument("--validate", action="store_true", help="بررسی اعتبار فایل")
    config_parser.add_argument("--force", action="store_true", help="بازنویسی فایل موجود")
    config_parser.set_defaults(func=cmd_config)

    test_parser = subparsers.add_parser("test", help="یک چرخه‌ی آزمایشی")
    test_parser.add_argument("--dry-run", action="store_true", help="بدون تغییر سیستم")
    test_parser.add_argument("--force", action="store_true", help="صرف‌نظر از آستانه و cooldown")
    test_parser.add_argument(
        "--include-fullscreen", action="store_true", help="حتی در حالت تمام‌صفحه هم اجرا کن"
    )
    test_parser.add_argument("--json", action="store_true", help="خروجی JSON")
    test_parser.set_defaults(func=cmd_test)

    subparsers.add_parser("console", help="اجرای دائمی در پیش‌زمینه").set_defaults(func=cmd_console)
    subparsers.add_parser("once", help="یک چرخه (برای Task Scheduler)").set_defaults(func=cmd_once)

    service_parser = subparsers.add_parser("service", help="مدیریت سرویس ویندوز")
    service_parser.add_argument(
        "action",
        choices=[
            "install",
            "remove",
            "start",
            "stop",
            "restart",
            "pause",
            "continue",
            "query",
            "repair",
        ],
    )
    service_parser.add_argument(
        "--wait", type=int, default=15, help="حداکثر ثانیه انتظار برای تغییر وضعیت"
    )
    service_parser.set_defaults(func=cmd_service)

    subparsers.add_parser("pause", help="توقف موقت پاک‌سازی در سرویس در حال اجرا").set_defaults(
        func=cmd_pause
    )
    subparsers.add_parser("resume", help="ادامه‌ی پاک‌سازی پس از pause").set_defaults(func=cmd_resume)
    subparsers.add_parser(
        "reload", help="خواندن دوباره‌ی config.ini بدون ری‌استارت سرویس"
    ).set_defaults(func=cmd_reload)

    verify_parser = subparsers.add_parser(
        "verify", help="بررسی عملی سناریوی «هر یک دقیقه / بحرانی = فوری»"
    )
    verify_parser.add_argument(
        "--simulate-critical", action="store_true", help="شبیه‌سازی مسیر بحرانی (بدون تغییر سیستم)"
    )
    verify_parser.add_argument(
        "--watch", type=int, default=0, metavar="SECONDS", help="پایش زنده به مدت N ثانیه"
    )
    verify_parser.set_defaults(func=cmd_verify)

    log_parser = subparsers.add_parser("log", help="نمایش انتهای لاگ")
    log_parser.add_argument("--lines", type=int, default=40)
    log_parser.set_defaults(func=cmd_log)

    return parser


def _version_text() -> str:
    from ramopt.version import __version__

    return f"RAM Optimizer Service {__version__}"


def main(argv: list[str] | None = None) -> int:
    _force_utf8_console()
    parser = build_parser()
    args = parser.parse_args(normalize_argv(list(sys.argv[1:] if argv is None else argv)))
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # pragma: no cover - بالاترین سطح
        from ramopt.logging_setup import write_crash

        write_crash(type(exc), exc, exc.__traceback__, note="cli")
        _print(f"خطای غیرمنتظره: {exc}")
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
