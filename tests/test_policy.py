# -*- coding: utf-8 -*-
"""تست سیاست تصمیم‌گیری — همان باگ‌هایی که در نسخه‌ی ۱ وجود داشت."""

from __future__ import annotations

from ramopt import win32
from ramopt.config import Config
from ramopt.engine import Action, Mode, OptimizerEngine
from ramopt.memory import Reading

GB = 1024**3


def reading(used_percent: float, available_gb: float = 4.0, standby_gb: float = 1.0) -> Reading:
    total = 16 * GB
    return Reading(
        snapshot=win32.MemorySnapshot(
            total_bytes=total,
            available_bytes=int(available_gb * GB),
            used_percent=used_percent,
            commit_used_bytes=int(total * 0.4),
            commit_limit_bytes=total,
            commit_percent=40.0,
        ),
        standby_total_bytes=int(standby_gb * GB),
        process_count=120,
    )


def make_engine(config: Config, fake_api, fake_provider, clock) -> OptimizerEngine:
    return OptimizerEngine(config, fake_api, fake_provider, clock=clock.now)


# ---------------------------------------------------------------------------
# هیسترزیس
# ---------------------------------------------------------------------------


def test_no_action_below_trigger(base_config, fake_api, fake_provider, clock):
    engine = make_engine(base_config, fake_api, fake_provider, clock)
    decision = engine.decide(reading(60.0))
    assert decision.action is Action.NOOP
    assert engine.mode is Mode.IDLE
    assert decision.should_optimize is False


def test_action_at_or_above_trigger(base_config, fake_api, fake_provider, clock):
    engine = make_engine(base_config, fake_api, fake_provider, clock)
    decision = engine.decide(reading(80.0))
    assert decision.should_optimize is True
    assert engine.mode is Mode.ARMED


def test_hysteresis_keeps_working_between_reset_and_trigger(
    base_config, fake_api, fake_provider, clock
):
    """بین ۶۵٪ و ۷۵٪ نباید دوباره خاموش/روشن شود (لرزش)."""
    engine = make_engine(base_config, fake_api, fake_provider, clock)
    engine.decide(reading(80.0))  # فعال شد
    engine.mode = Mode.ACTIVE
    decision = engine.decide(reading(70.0))  # بالای reset، زیر trigger
    assert decision.should_optimize is True
    assert engine.mode is Mode.ACTIVE


def test_hysteresis_resets_below_reset_percent(base_config, fake_api, fake_provider, clock):
    engine = make_engine(base_config, fake_api, fake_provider, clock)
    engine.mode = Mode.ACTIVE
    decision = engine.decide(reading(60.0))
    assert decision.action is Action.NOOP
    assert engine.mode is Mode.IDLE


# ---------------------------------------------------------------------------
# cooldown و سقف ساعتی  (باگ B4)
# ---------------------------------------------------------------------------


def test_cooldown_blocks_second_run(base_config, fake_api, fake_provider, clock):
    engine = make_engine(base_config, fake_api, fake_provider, clock)
    engine.last_purge_at = clock.now()

    decision = engine.decide(reading(85.0))
    assert decision.action is Action.SKIPPED
    assert "cooling down" in decision.reason

    clock.advance(base_config.cooldown_seconds + 1)
    engine.mode = Mode.ACTIVE
    decision = engine.decide(reading(85.0))
    assert decision.should_optimize is True


def test_cooldown_backs_off_after_useless_runs(base_config, fake_api, fake_provider, clock):
    engine = make_engine(base_config, fake_api, fake_provider, clock)
    engine.mode = Mode.ACTIVE
    engine.last_purge_at = clock.now()
    engine.consecutive_useless = 2  # دو بار بی‌اثر → cooldown چهار برابر

    clock.advance(base_config.cooldown_seconds + 1)  # فقط یک برابر گذشته
    decision = engine.decide(reading(85.0))
    assert decision.action is Action.SKIPPED

    clock.advance(base_config.cooldown_seconds * 3)
    decision = engine.decide(reading(85.0))
    assert decision.should_optimize is True


def test_hourly_cap(base_config, fake_api, fake_provider, clock):
    engine = make_engine(base_config, fake_api, fake_provider, clock)
    engine.mode = Mode.ACTIVE
    engine.purge_history = [clock.now() for _ in range(base_config.max_purges_per_hour)]
    engine.last_purge_at = None

    decision = engine.decide(reading(90.0))
    assert decision.action is Action.SKIPPED
    assert "hourly cap" in decision.reason

    clock.advance(3601)  # پنجره‌ی یک‌ساعته می‌گذرد
    decision = engine.decide(reading(90.0))
    assert decision.should_optimize is True


# ---------------------------------------------------------------------------
# محدودیت‌های محیطی
# ---------------------------------------------------------------------------


def test_skips_in_fullscreen(base_config, fake_api, fake_provider, clock):
    fake_api.user_state = win32.QUNS_RUNNING_D3D_FULL_SCREEN
    engine = make_engine(base_config, fake_api, fake_provider, clock)
    decision = engine.decide(reading(90.0))
    assert decision.action is Action.SKIPPED
    assert "fullscreen" in decision.reason


def test_fullscreen_check_can_be_disabled(base_config, fake_api, fake_provider, clock):
    fake_api.user_state = win32.QUNS_RUNNING_D3D_FULL_SCREEN
    config = Config(**{**base_config.__dict__, "skip_when_fullscreen": False})
    engine = make_engine(config, fake_api, fake_provider, clock)
    assert engine.decide(reading(90.0)).should_optimize is True


def test_skips_on_battery_only_when_configured(base_config, fake_api, fake_provider, clock):
    fake_api.on_battery = True
    engine = make_engine(base_config, fake_api, fake_provider, clock)
    assert engine.decide(reading(90.0)).should_optimize is True  # پیش‌فرض: مجاز

    config = Config(**{**base_config.__dict__, "skip_on_battery": True})
    engine = make_engine(config, fake_api, fake_provider, clock)
    decision = engine.decide(reading(90.0))
    assert decision.action is Action.SKIPPED
    assert "battery" in decision.reason


def test_startup_delay(base_config, fake_api, fake_provider, clock):
    config = Config(**{**base_config.__dict__, "startup_delay_seconds": 120})
    engine = make_engine(config, fake_api, fake_provider, clock)
    decision = engine.decide(reading(90.0))
    assert decision.action is Action.SKIPPED
    assert "startup delay" in decision.reason

    clock.advance(121)
    assert engine.decide(reading(90.0)).should_optimize is True


def test_quiet_hours_overnight(base_config, fake_api, fake_provider, clock):
    import datetime as dt

    from conftest import FakeClock

    config = Config(**{**base_config.__dict__, "quiet_hours": "23:00-06:00"})

    night = FakeClock(dt.datetime(2026, 1, 1, 23, 30))
    engine = OptimizerEngine(config, fake_api, fake_provider, clock=night.now)
    assert engine.decide(reading(90.0)).action is Action.SKIPPED

    noon = FakeClock(dt.datetime(2026, 1, 2, 12, 0))
    engine = OptimizerEngine(config, fake_api, fake_provider, clock=noon.now)
    assert engine.decide(reading(90.0)).should_optimize is True


def test_pause_and_resume(base_config, fake_api, fake_provider, clock):
    engine = make_engine(base_config, fake_api, fake_provider, clock)
    engine.pause("تست")
    assert engine.decide(reading(95.0)).action is Action.SKIPPED
    engine.resume()
    assert engine.decide(reading(95.0)).should_optimize is True


def test_min_available_mb_goal(base_config, fake_api, fake_provider, clock):
    """روی سیستم ۶۴ گیگی، ۵۰ گیگ آزاد حتی با ۸۰٪ «مصرف» یعنی نیازی نیست."""
    config = Config(**{**base_config.__dict__, "min_available_mb": 4096})
    engine = make_engine(config, fake_api, fake_provider, clock)
    decision = engine.decide(reading(80.0, available_gb=8.0))
    assert decision.action is Action.NOOP
    assert "already free" in decision.reason

    decision = engine.decide(reading(80.0, available_gb=2.0))
    assert decision.should_optimize is True


# ---------------------------------------------------------------------------
# پاس سبک دوره‌ای (درخواست: هر یک دقیقه، حتی زیر آستانه، سبک و کم‌اثر)
# ---------------------------------------------------------------------------


def test_periodic_lightweight_pass_runs_below_trigger(fake_api, fake_provider, clock):
    config = Config(
        startup_delay_seconds=0,
        trigger_percent=75,
        reset_percent=65,
        cooldown_seconds=300,
        max_purges_per_hour=6,
        min_available_mb=0,
        purge_standby_list=True,
        min_free_mb_after_trim=0,
        min_process_ws_mb=20,
        max_processes=0,
        periodic_trim_enabled=True,
        periodic_trim_max_processes=4,
        periodic_trim_min_process_ws_mb=64,
    )
    engine = make_engine(config, fake_api, fake_provider, clock)
    decision = engine.decide(reading(40.0))
    assert decision.should_optimize is True
    assert decision.lightweight is True
    assert decision.action is Action.OPTIMIZED


def test_periodic_lightweight_pass_respects_pause(fake_api, fake_provider, clock):
    config = Config(
        startup_delay_seconds=0,
        trigger_percent=75,
        reset_percent=65,
        periodic_trim_enabled=True,
    )
    engine = make_engine(config, fake_api, fake_provider, clock)
    engine.pause("test")
    decision = engine.decide(reading(40.0))
    assert decision.action is Action.SKIPPED


def test_periodic_lightweight_pass_does_not_consume_heavy_cooldown(fake_api, fake_provider, clock):
    from conftest import set_process_sizes

    config = Config(
        startup_delay_seconds=0,
        trigger_percent=75,
        reset_percent=65,
        cooldown_seconds=300,
        max_purges_per_hour=6,
        min_available_mb=0,
        purge_standby_list=True,
        min_free_mb_after_trim=0,
        min_process_ws_mb=20,
        max_processes=0,
        periodic_trim_enabled=True,
        periodic_trim_max_processes=4,
        periodic_trim_min_process_ws_mb=20,
    )
    fake_api.used_bytes = int(4 * GB)  # زیر آستانه
    set_process_sizes(fake_api, fake_provider, {400: 200})
    engine = make_engine(config, fake_api, fake_provider, clock)
    result = engine.run_cycle()
    assert result.action is Action.OPTIMIZED
    assert result.purge is not None and result.purge.purged is False
    assert "lightweight" in (result.purge.skipped_reason or "")
    assert engine.last_purge_at is None
    assert engine.total_purges == 0
