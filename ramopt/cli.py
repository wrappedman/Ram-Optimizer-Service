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
        _print("error: this command only works on Windows.")
        return False
    return True


def _load(args):
    config, issues = load_config(getattr(args, "config", None) or None)
    return config, issues


def _report_issues(issues, verbose: bool = True) -> None:
    for issue in issues:
        if verbose:
            _print(f"warning: [{issue.section}] {issue.key} = {issue.value!r}: {issue.message}")


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


def _num(value, suffix: str = "") -> str:
    """Format an optional number for humans ("?" instead of "None")."""
    if value is None:
        return "?"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = f"{number:.1f}".rstrip("0").rstrip(".") if number % 1 else f"{number:.0f}"
    return f"{text}{suffix}"


def cmd_status(args) -> int:
    """Current state, from status.json (--json for machine use)."""
    from ramopt.status import read_status

    data = read_status()
    if data is None:
        _print("status.json not found - the service has never run, or uses another data folder.")
        _print(f"expected path: {paths.status_file()}")
        return EXIT_ERROR
    if args.json:
        _json_print(data)
        return EXIT_OK

    memory: dict = data.get("memory") or {}
    counters: dict = data.get("counters") or {}
    critical = (data.get("extra") or {}).get("critical")

    def row(label: str, value: str) -> None:
        _print(f"  {label:<14}{value}")

    _print(f"RAM Optimizer Service {data.get('version')}")
    row("state", f"{data.get('state')}  (pid {data.get('pid')})")
    row("started", str(data.get("started_at")))
    row("last cycle", str(data.get("last_cycle_at")))
    row("last action", str(data.get("last_action")))
    # reason/last_action may be Persian in older status files; keep them as-is.
    if data.get("last_reason"):
        _print(f"                 {data.get('last_reason')}")
    row(
        "memory",
        f"{memory.get('used_percent', '?')}% used | "
        f"{memory.get('available_mb', '?')} MB free | "
        f"commit {memory.get('commit_percent', '?')}% | "
        f"standby {memory.get('standby_mb', '?')} MB",
    )
    row(
        "counters",
        f"{counters.get('purges', 0)} passes | "
        f"{counters.get('freed_mb', 0)} MB freed | "
        f"{counters.get('errors', 0)} errors | "
        f"{counters.get('cycles', 0)} cycles",
    )
    if data.get("next_allowed_at"):
        row("next pass", f"allowed from {data.get('next_allowed_at')}")
    if critical is not None:
        row("critical", "yes - acts immediately" if critical else "no")
    for err in data.get("recent_errors") or []:
        _print(f"  error: {err.get('at')} - {err.get('message')}")
    return EXIT_OK


def cmd_config(args) -> int:
    if args.init:
        path = write_default_config(args.config or None, overwrite=args.force)
        action = "rewritten" if args.force else "ready"
        _print(f"config file {action}: {path}")
        return EXIT_OK

    config, issues = _load(args)
    effective_path = args.config or paths.config_file()
    if args.validate:
        if issues:
            _print(f"{len(issues)} problem(s) in the config file:")
            _report_issues(issues)
            return EXIT_ERROR
        if not os.path.isfile(effective_path):
            _print(f"no config file at {effective_path} (built-in defaults are used)")
            return EXIT_OK
        _print("config file is valid.")
        _print(f"path: {effective_path}")
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
    _print(f"config file: {effective_path}")
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
        _print(f"error: {api.load_error}")
        return EXIT_ERROR

    from ramopt.logging_setup import log_startup_banner

    log_startup_banner(config)
    for privilege in ("SeProfileSingleProcessPrivilege", "SeIncreaseQuotaPrivilege"):
        if not api.enable_privilege(privilege):
            _print(
                f"warning: could not enable {privilege} - start the command prompt as administrator."
            )

    provider = memory_mod.PsutilProcessProvider()
    reading = memory_mod.measure(api, provider)

    if args.dry_run:
        engine = OptimizerEngine(config, api, provider)
        decision = engine.decide(reading)
        _print("--- dry run: nothing on this system will be changed ---")
        _print(
            f"memory: {reading.used_percent:.1f}% used | {reading.available_mb:.0f} MB free | "
            f"commit {reading.commit_percent:.0f}% | standby "
            f"{'?' if reading.standby_mb is None else f'{reading.standby_mb:.0f} MB'} | "
            f"{reading.process_count} processes"
        )
        _print(f"decision: {decision.action.value} | mode: {decision.mode.value}")
        _print(f"reason:   {decision.reason}")
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
        _print(f"\nprocesses that would be trimmed ({len(candidates)}):")
        for proc in candidates[:20]:
            _print(
                f"  {proc.working_set_bytes / memory_mod.MB:9.1f}MB  {proc.name}  (PID {proc.pid})"
            )
        if len(candidates) > 20:
            _print(f"  ... and {len(candidates) - 20} more processes")
        return EXIT_OK

    engine = OptimizerEngine(config, api, provider)
    result = engine.run_cycle(force=args.force)
    payload: dict = result.as_dict()
    if args.json:
        _json_print(payload)
    else:
        _print(f"action:  {payload['action']} - {payload['reason']}")
        before_pct = payload.get("used_percent_before")
        after_pct = payload.get("used_percent_after")
        before_mb = payload.get("available_mb_before")
        after_mb = payload.get("available_mb_after")
        pct = f"{_num(before_pct)}% -> {_num(after_pct)}%"
        free = f"{_num(before_mb)} MB -> {_num(after_mb)} MB"
        _print(f"memory:  {pct} | free {free}")
        if payload.get("trim"):
            trim: dict = payload["trim"]
            _print(
                f"trim:    {trim['trimmed']}/{trim['considered']} processes | "
                f"{trim['freed_mb']} MB working set | access denied: {trim['denied']} | "
                f"failed: {trim['failed']}"
            )
            for item in trim.get("biggest", []):
                _print(f"         {item['mb']:8.1f}MB  {item['name']}")
        if payload.get("purge"):
            purge: dict = payload["purge"]
            status_text = (
                "purged" if purge["purged"] else (purge["error"] or purge["skipped_reason"])
            )
            _print(
                f"standby: {status_text} | "
                f"{_num(purge['standby_before_mb'], ' MB')} -> "
                f"{_num(purge['standby_after_mb'], ' MB')}"
            )
        _print(f"time:    {payload['duration_ms']} ms")
        if payload["action"] == "skipped":
            _print("result:  nothing was changed (see the reason above).")
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
        _print("stopped.")
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
        _print(f"error: could not write {target}: {exc}")
        _print("this needs to run with administrator rights.")
        return EXIT_ERROR
    _print(f'command "{command}" queued; the service applies it on its next check.')
    _print(f"file: {target}")
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
    """Read-only proof of the requested behaviour.

    Prints the effective cadence (60 s normal, immediate at the critical
    threshold, 5 s while critical) and, with ``--simulate-critical``, shows the
    decision the engine takes when memory is critical. Nothing is trimmed or
    purged, so it is safe to run on a production machine.
    """
    import time

    from ramopt import memory as memory_mod
    from ramopt import paths
    from ramopt.config import Config, load_config

    config, issues = load_config(getattr(args, "config", None) or None)
    for issue in issues:
        _print(f"[!] [{issue.section}] {issue.key}: {issue.message}")

    interval = config.check_interval_seconds
    critical_poll = config.critical_poll_seconds
    probe = config.critical_probe_seconds
    threshold = config.sustained_trigger_percent

    _print("Requested behaviour")
    _print(f"  1) normal:       release pass every {interval} s")
    _print(f"  2) critical:     at {threshold}% used -> act in that same cycle")
    _print(f"     mid-wait:     lightweight probe every {probe} s, so a spike")
    _print("                   between cycles is not missed")
    _print(f"     while high:   re-check every {critical_poll} s until it drops")
    _print("")
    _print("Effective configuration")
    _print(f"  check_interval_seconds    = {interval}")
    _print(f"  critical_poll_seconds     = {critical_poll}")
    _print(f"  critical_probe_seconds    = {probe}")
    _print(f"  trigger_percent           = {config.trigger_percent}")
    _print(f"  sustained_trigger_percent = {threshold}")
    _print(f"  sustained_polls           = {config.sustained_polls}")
    _print(f"  cooldown_seconds          = {config.cooldown_seconds}")
    _print("")

    reading = memory_mod.measure(_api_for_verify())
    if reading.snapshot is None:
        _print("ERROR: cannot read memory state on this machine.")
        return EXIT_ERROR

    used = reading.used_percent
    total_mb = reading.snapshot.total_bytes / (1024 * 1024)
    standby = "n/a" if reading.standby_mb is None else f"{reading.standby_mb:.0f}"
    _print("Current memory")
    _print(f"  used            : {used:.1f}%")
    _print(f"  available       : {reading.available_mb:.0f} MB of {total_mb:.0f} MB")
    _print(f"  standby (cache) : {standby} MB")
    _print("")

    over_normal = used >= config.trigger_percent
    over_critical = used >= threshold
    _print("Assessment")
    _print(
        f"  over trigger_percent ({config.trigger_percent}%)      : "
        f"{'yes' if over_normal else 'no'}"
    )
    if over_critical:
        _print(f"  over critical threshold ({threshold}%)  : yes -> next cycle acts at once")
        _print(f"  next poll in    : {critical_poll} s")
    else:
        _print(f"  over critical threshold ({threshold}%)  : no")
        _print(f"  next poll in    : {interval} s")
        _print(f"  if usage reaches {threshold}%, the loop does not wait those {interval} s")

    if args.simulate_critical:
        _print("")
        _print("Critical path (simulated, nothing on the system is changed)")
        from ramopt.engine import Action as _Action
        from ramopt.engine import OptimizerEngine

        simulated = Config(**{**config.__dict__, "sustained_trigger_percent": 1})
        engine = OptimizerEngine(simulated, _api_for_verify())
        decision = engine.decide(reading)
        if not decision.critical:
            _print(f"  [x] critical path did not fire: {decision.reason}")
            _print("      (blocked by pause / fullscreen / battery / threshold disabled)")
            return EXIT_ERROR
        _print(f"  usage above threshold -> decision: {decision.action.value} (immediate)")
        _print("  timeline the service follows:")
        _print("    T+0s        read memory, threshold crossed -> release pass now")
        _print("    T+0s        decision carries critical=True (cooldown and hourly cap skipped)")
        _print(f"    T+{critical_poll}s        poll again (not {interval}s)")
        _print(
            f"    T+{2 * critical_poll}s        poll again ... until usage drops below {threshold}%"
        )
        _print(f"    then        back to the normal {interval}s cadence")
        assert decision.action is _Action.OPTIMIZED

    if args.watch > 0:
        _print("")
        _print(f"Live watch for {args.watch} s (state changes only)")
        _print(f"  (the installed service decides once every {interval} s)")
        last = None
        deadline = time.monotonic() + args.watch
        while time.monotonic() < deadline:
            current = memory_mod.measure(_api_for_verify())
            if current.snapshot is not None:
                state = current.used_percent >= threshold
                if state != last:
                    stamp = time.strftime("%H:%M:%S")
                    label = "CRITICAL" if state else "normal"
                    _print(f"  [{stamp}] {current.used_percent:5.1f}% -> {label}")
                    last = state
            time.sleep(min(2.0, max(0.5, critical_poll)))

    _print("")
    _print(f"Log file: {paths.log_file()}")
    _print("Real evidence: run the service, then 'RamOptimizerService.exe log --lines 50'")
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
        _print(f"no log file yet: {log_path}")
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
        description="RAM Optimizer Service - releases memory only when it is really needed.",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="alternative config file (default: <ProgramData>\\RamOptimizer\\config.ini)",
    )
    parser.add_argument("--version", action="version", version=_version_text())
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version", help="show the version and the environment").set_defaults(
        func=cmd_version
    )

    status_parser = subparsers.add_parser("status", help="show the current state")
    status_parser.add_argument("--json", action="store_true", help="machine-readable JSON output")
    status_parser.set_defaults(func=cmd_status)

    config_parser = subparsers.add_parser("config", help="manage the config file")
    group = config_parser.add_mutually_exclusive_group()
    group.add_argument("--init", action="store_true", help="write a default config.ini")
    group.add_argument(
        "--show", action="store_true", help="show the effective configuration (default)"
    )
    group.add_argument("--validate", action="store_true", help="validate the file")
    config_parser.add_argument("--force", action="store_true", help="overwrite an existing file")
    config_parser.set_defaults(func=cmd_config)

    test_parser = subparsers.add_parser("test", help="run one trial cycle")
    test_parser.add_argument("--dry-run", action="store_true", help="change nothing on the system")
    test_parser.add_argument(
        "--force", action="store_true", help="ignore the threshold and the cooldown"
    )
    test_parser.add_argument(
        "--include-fullscreen",
        action="store_true",
        help="also run while a fullscreen app is active",
    )
    test_parser.add_argument("--json", action="store_true", help="machine-readable JSON output")
    test_parser.set_defaults(func=cmd_test)

    subparsers.add_parser("console", help="run continuously in the foreground").set_defaults(
        func=cmd_console
    )
    subparsers.add_parser("once", help="run a single cycle (for Task Scheduler)").set_defaults(
        func=cmd_once
    )

    service_parser = subparsers.add_parser("service", help="manage the Windows service")
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
        "--wait", type=int, default=15, help="seconds to wait for a state change"
    )
    service_parser.set_defaults(func=cmd_service)

    subparsers.add_parser("pause", help="pause trimming in the running service").set_defaults(
        func=cmd_pause
    )
    subparsers.add_parser("resume", help="resume trimming after a pause").set_defaults(
        func=cmd_resume
    )
    subparsers.add_parser(
        "reload", help="reload config.ini without restarting the service"
    ).set_defaults(func=cmd_reload)

    verify_parser = subparsers.add_parser(
        "verify", help="prove the scenario: every 60 s, and immediately when critical"
    )
    verify_parser.add_argument(
        "--simulate-critical",
        action="store_true",
        help="simulate the critical path (changes nothing)",
    )
    verify_parser.add_argument(
        "--watch", type=int, default=0, metavar="SECONDS", help="watch live for N seconds"
    )
    verify_parser.set_defaults(func=cmd_verify)

    log_parser = subparsers.add_parser("log", help="show the end of the log file")
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
        _print(f"unexpected error: {exc}")
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
