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
    if args.validate:
        if issues:
            _print(f"{len(issues)} مشکل در فایل پیکربندی:")
            _report_issues(issues)
            return EXIT_ERROR
        _print("فایل پیکربندی معتبر است. ✔")
        _print(f"مسیر: {paths.config_file()}")
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
    _print(f"مسیر فایل پیکربندی: {paths.config_file()}")
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
        "general": ["check_interval_seconds", "startup_delay_seconds"],
        "policy": [
            "trigger_percent",
            "reset_percent",
            "cooldown_seconds",
            "max_purges_per_hour",
            "min_available_mb",
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
    args = parser.parse_args(argv)
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
