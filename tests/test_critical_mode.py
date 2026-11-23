# -*- coding: utf-8 -*-
"""تست سناریوی عملیاتی درخواستی:

1. هر یک دقیقه آزادسازی حافظه‌ی بلااستفاده انجام شود.
2. وقتی حافظه به نقطه‌ی بحرانی رسید، دیگر منتظر بررسی یک‌دقیقه‌ای نمانیم و
   فرایند فوراً اجرا شود.
"""

from __future__ import annotations

import json
import os

from conftest import FakeApi, FakeClock, FakeProvider, set_process_sizes
from ramopt.cli import normalize_argv
from ramopt.config import Config, config_from_parser, normalize_number_text
from ramopt.engine import Action, Mode, OptimizerEngine
from ramopt.runner import OptimizerRunner
from ramopt.status import StatusWriter, read_status

GB = 1024**3


def make_config(**overrides) -> Config:
    base = Config(
        check_interval_seconds=60,
        critical_poll_seconds=5,
        startup_delay_seconds=0,
        trigger_percent=75,
        reset_percent=65,
        sustained_trigger_percent=92,
        sustained_polls=1,
        cooldown_seconds=300,
        max_purges_per_hour=0,
        min_available_mb=0,
        min_free_mb_after_trim=0,
        min_process_ws_mb=20,
        max_processes=0,
        skip_when_fullscreen=False,
        skip_on_battery=False,
        quiet_hours="",
    )
    return Config(**{**base.__dict__, **overrides})


# ---------------------------------------------------------------------------
# ۱) هر یک دقیقه
# ---------------------------------------------------------------------------


def test_default_interval_is_one_minute_and_critical_is_five_seconds():
    config = Config()
    assert config.check_interval_seconds == 60
    assert config.critical_poll_seconds == 5
    # آستانه‌ی بحرانی بالاتر از آستانه‌ی عادی است
    assert config.sustained_trigger_percent > config.trigger_percent


def test_runner_uses_sixty_seconds_when_idle():
    api, provider, clock = FakeApi(), FakeProvider(), FakeClock()
    api.used_bytes = int(4 * GB)  # ۲۵٪
    runner = OptimizerRunner(
        config=make_config(),
        api=api,
        status=StatusWriter(),
        engine=OptimizerEngine(make_config(), api, provider, clock=clock.now),
    )
    runner.run_once()
    assert runner.next_interval() == 60


def test_runner_switches_to_critical_interval():
    api, provider, clock = FakeApi(), FakeProvider(), FakeClock()
    config = make_config()
    api.used_bytes = int(15 * GB)  # ۹۳٪
    runner = OptimizerRunner(
        config=config,
        api=api,
        status=StatusWriter(),
        engine=OptimizerEngine(config, api, provider, clock=clock.now),
    )
    api.open_denied = True  # تا در حالت بحرانی هم هیچ trim موفقی نداشته باشیم
    runner.run_once()
    assert runner.next_interval() == 5


# ---------------------------------------------------------------------------
# ۲) نقطه‌ی بحرانی → اجرای فوری
# ---------------------------------------------------------------------------


def test_critical_runs_immediately_even_inside_cooldown():
    """قلب سناریو: cooldown فعال است، ولی RAM بحرانی شده → باید فوراً اجرا شود."""
    api, provider, clock = FakeApi(), FakeProvider(), FakeClock()
    config = make_config()
    engine = OptimizerEngine(config, api, provider, clock=clock.now)

    # یک پاک‌سازی موفق در همین لحظه انجام شده و cooldown فعال است
    engine.last_purge_at = clock.now()
    engine.mode = Mode.ACTIVE
    set_process_sizes(api, provider, {400: 1200})
    api.used_bytes = int(15 * GB)  # ۹۳٪ → بحرانی

    reading_used = 93.75
    from ramopt import win32

    reading = type(
        "R",
        (),
        {
            "used_percent": reading_used,
            "available_mb": api.total_bytes * (1 - reading_used / 100) / (1024 * 1024),
            "commit_percent": 40.0,
            "standby_mb": 1024.0,
            "snapshot": win32.MemorySnapshot(
                total_bytes=api.total_bytes,
                available_bytes=int(api.total_bytes * 0.0625),
                used_percent=reading_used,
                commit_used_bytes=0,
                commit_limit_bytes=api.total_bytes,
                commit_percent=40.0,
            ),
        },
    )()

    decision = engine.decide(reading)
    assert decision.should_optimize is True
    assert decision.critical is True
    assert "بحرانی" in decision.reason


def test_critical_requires_consecutive_polls_when_configured():
    api, provider, clock = FakeApi(), FakeProvider(), FakeClock()
    config = make_config(sustained_polls=2, sustained_trigger_percent=90)
    engine = OptimizerEngine(config, api, provider, clock=clock.now)

    from ramopt import win32
    from ramopt.memory import Reading

    def reading_at(percent: float) -> Reading:
        total = 16 * GB
        return Reading(
            snapshot=win32.MemorySnapshot(
                total_bytes=total,
                available_bytes=int(total * (1 - percent / 100)),
                used_percent=percent,
                commit_used_bytes=0,
                commit_limit_bytes=total,
                commit_percent=40.0,
            ),
            standby_total_bytes=1024 * GB,
            process_count=10,
        )

    # بررسی اول: بالای آستانه ولی هنوز یک بررسی کم است
    first = engine.decide(reading_at(95.0))
    assert first.critical is False  # اولین بررسی: هنوز «بحرانی» نیست
    assert engine.critical_streak == 1

    second = engine.decide(reading_at(95.0))
    assert second.critical is True
    assert second.should_optimize is True


def test_critical_state_clears_below_threshold():
    api, provider, clock = FakeApi(), FakeProvider(), FakeClock()
    engine = OptimizerEngine(make_config(), api, provider, clock=clock.now)
    from ramopt import win32
    from ramopt.memory import Reading

    def reading_at(percent: float) -> Reading:
        total = 16 * GB
        return Reading(
            snapshot=win32.MemorySnapshot(
                total_bytes=total,
                available_bytes=int(total * (1 - percent / 100)),
                used_percent=percent,
                commit_used_bytes=0,
                commit_limit_bytes=total,
                commit_percent=40.0,
            ),
            standby_total_bytes=0,
            process_count=10,
        )

    assert engine.decide(reading_at(95.0)).critical is True
    assert engine.decide(reading_at(50.0)).critical is False
    assert engine.critical_streak == 0


def test_critical_purges_even_with_min_available_mb_and_hourly_cap():
    """در وضعیت بحرانی، محدودیت‌های «هدف مطلق» و «سقف ساعتی» کنار می‌روند."""
    api, provider, clock = FakeApi(), FakeProvider(), FakeClock()
    config = make_config(min_available_mb=8192, max_purges_per_hour=1)
    engine = OptimizerEngine(config, api, provider, clock=clock.now)
    engine.purge_history = [clock.now()]
    api.used_bytes = int(15 * GB)

    from ramopt import win32
    from ramopt.memory import Reading

    total = 16 * GB
    reading = Reading(
        snapshot=win32.MemorySnapshot(
            total_bytes=total,
            available_bytes=1024 * GB,  # عمداً بزرگ: هدف مطلق نباید جلوی کار را بگیرد
            used_percent=95.0,
            commit_used_bytes=0,
            commit_limit_bytes=total,
            commit_percent=40.0,
        ),
        standby_total_bytes=0,
        process_count=10,
    )
    decision = engine.decide(reading)
    assert decision.should_optimize is True
    assert decision.critical is True


def test_critical_respects_manual_pause():
    api, provider, clock = FakeApi(), FakeProvider(), FakeClock()
    engine = OptimizerEngine(make_config(), api, provider, clock=clock.now)
    engine.pause("تست")
    from ramopt import win32
    from ramopt.memory import Reading

    total = 16 * GB
    reading = Reading(
        snapshot=win32.MemorySnapshot(total, 100, 99.0, 0, total, 40.0),
        standby_total_bytes=0,
        process_count=5,
    )
    decision = engine.decide(reading)
    assert decision.should_optimize is False  # کاربر گفته دست نزن
    assert decision.critical is True


def test_status_json_exposes_critical_flag():
    api, provider, clock = FakeApi(), FakeProvider(), FakeClock()
    config = make_config()
    api.used_bytes = int(15 * GB)
    api.open_denied = True  # هیچ trim موفقی نباشد → critical در status می‌ماند
    runner = OptimizerRunner(
        config=config,
        api=api,
        status=StatusWriter(),
        engine=OptimizerEngine(config, api, provider, clock=clock.now),
    )
    runner.prepare()
    runner.run_once()
    data = read_status()
    assert data is not None
    assert data["critical"] is True


# ---------------------------------------------------------------------------
# command.json: pause/resume/reload از بیرون
# ---------------------------------------------------------------------------


def test_pause_command_file_is_picked_up_and_removed():
    from ramopt import paths

    api, provider, clock = FakeApi(), FakeProvider(), FakeClock()
    config = make_config()
    runner = OptimizerRunner(
        config=config,
        api=api,
        status=StatusWriter(),
        engine=OptimizerEngine(config, api, provider, clock=clock.now),
    )
    runner.prepare()

    command_path = os.path.join(paths.data_dir(), "command.json")
    with open(command_path, "w", encoding="utf-8") as handle:
        json.dump({"command": "pause"}, handle)

    runner._poll_command()
    assert runner.engine.paused is True
    assert not os.path.exists(command_path), "فایل دستور باید پس از اجرا حذف شود"


def test_reload_command_applies_new_config():
    from ramopt import paths

    api, provider, clock = FakeApi(), FakeProvider(), FakeClock()
    config = make_config(trigger_percent=75)
    runner = OptimizerRunner(
        config=config,
        api=api,
        status=StatusWriter(),
        engine=OptimizerEngine(config, api, provider, clock=clock.now),
    )
    runner.prepare()

    from ramopt.config import write_default_config

    config_path = paths.config_file()
    write_default_config(config_path, overwrite=True)
    # مقدار را داخل همان بخش موجود عوض می‌کنیم (بخش تکراری در ini خطاست)
    with open(config_path, encoding="utf-8") as handle:
        text = handle.read()
    text = text.replace("trigger_percent = 75", "trigger_percent = 88")
    with open(config_path, "w", encoding="utf-8") as handle:
        handle.write(text)

    with open(os.path.join(paths.data_dir(), "command.json"), "w", encoding="utf-8") as handle:
        json.dump({"command": "reload"}, handle)

    runner._poll_command()
    assert runner.config.trigger_percent == 88


def test_resume_command_after_pause():
    from ramopt import paths

    api, provider, clock = FakeApi(), FakeProvider(), FakeClock()
    config = make_config()
    runner = OptimizerRunner(
        config=config,
        api=api,
        status=StatusWriter(),
        engine=OptimizerEngine(config, api, provider, clock=clock.now),
    )
    runner.prepare()
    runner.pause("تست")
    with open(os.path.join(paths.data_dir(), "command.json"), "w", encoding="utf-8") as handle:
        json.dump({"command": "resume"}, handle)
    runner._poll_command()
    assert runner.engine.paused is False


def test_garbage_command_file_is_ignored():
    from ramopt import paths

    api, provider, clock = FakeApi(), FakeProvider(), FakeClock()
    runner = OptimizerRunner(
        config=make_config(),
        api=api,
        status=StatusWriter(),
        engine=OptimizerEngine(make_config(), api, provider, clock=clock.now),
    )
    path = os.path.join(paths.data_dir(), "command.json")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("{ this is not json")
    runner._poll_command()  # نباید استثنا بدهد
    assert not os.path.exists(path)


# ---------------------------------------------------------------------------
# رفع باگ‌های جانبی که در بازبینی پیدا شد
# ---------------------------------------------------------------------------


def test_inline_comments_in_config_are_supported():
    """README قالب «trigger_percent = 75 ; آستانه» را نشان می‌دهد."""
    import configparser

    parser = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";", "#"))
    parser.read_string("[policy]\ntrigger_percent = 75 ; آستانه\nreset_percent = 60 # x\n")
    issues: list = []
    config = config_from_parser(parser, issues)
    assert config.trigger_percent == 75
    assert config.reset_percent == 60
    assert issues == []


def test_persian_digits_are_accepted_in_config():
    import configparser

    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string("[policy]\ntrigger_percent = ۸۰\nreset_percent = ۶۰\n")
    issues: list = []
    config = config_from_parser(parser, issues)
    assert config.trigger_percent == 80
    assert config.reset_percent == 60
    assert issues == []
    assert normalize_number_text("۹۵") == "95"


def test_legacy_service_arguments_still_work():
    assert normalize_argv(["install", "--startup", "auto"]) == ["service", "install"]
    assert normalize_argv(["start"]) == ["service", "start"]
    assert normalize_argv(["remove"]) == ["service", "remove"]
    assert normalize_argv(["--startup", "delayed", "install"]) == ["service", "install"]
    # دستور جدید «service ...» دست‌نخورده می‌ماند
    assert normalize_argv(["service", "install"]) == ["service", "install"]
    # pause دیگر فرمان سرویس نیست (فرمان pause یعنی توقف موقت پاک‌سازی)
    assert normalize_argv(["pause"]) == ["pause"]
    assert Action.SKIPPED.value == "skipped"
