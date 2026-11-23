# -*- coding: utf-8 -*-
"""تست اجرای کامل چرخه: نتایج صادقانه، ثبت لاگ/وضعیت، خطاها."""

from __future__ import annotations

import json

from ramopt.config import Config
from ramopt.engine import Action, CycleResult, OptimizerEngine
from ramopt.memory import MB, PurgeReport, TrimReport

GB = 1024**3


def make_engine(config, fake_api, fake_provider, clock):
    return OptimizerEngine(config, fake_api, fake_provider, clock=clock.now)


def stressed_api(fake_api):
    fake_api.used_bytes = int(14 * GB)  # ~۸۸٪ مصرف
    return fake_api


def sizes(fake_api, fake_provider, mapping):
    from conftest import set_process_sizes

    set_process_sizes(fake_api, fake_provider, mapping)


def test_successful_cycle_reports_real_numbers(base_config, fake_api, fake_provider, clock):
    stressed_api(fake_api)
    sizes(fake_api, fake_provider, {100: 500, 400: 1200})
    engine = make_engine(base_config, fake_api, fake_provider, clock)

    result = engine.run_cycle()

    assert result.action is Action.OPTIMIZED
    # 500MB از chrome + 1200MB از بازی؛ پروسه‌ای که با اندازه‌ی صفر دیده
    # می‌شود زیر آستانه است، پس دست نمی‌خورد.
    assert result.trim is not None and result.trim.trimmed == 2
    assert result.trim.freed_mb == 1700
    assert result.purge is not None and result.purge.purged is True
    assert result.available_mb_after > result.available_mb_before
    # «آزادشده» بر مبنای available واقعی است، نه استفاده‌ی خام
    assert result.freed_mb > 0
    assert engine.total_purges == 1
    assert engine.last_purge_at == clock.now()


def test_useless_cycle_is_not_reported_as_success(base_config, fake_api, fake_provider, clock):
    """باگ B5 نسخه‌ی قبل: تابع همیشه True برمی‌گرداند و لاگ «انجام شد» می‌نوشت."""
    stressed_api(fake_api)
    fake_api.open_denied = True
    config = Config(**{**base_config.__dict__, "purge_standby_list": False})
    engine = make_engine(config, fake_api, fake_provider, clock)

    result = engine.run_cycle()

    assert result.action is Action.SKIPPED
    assert "access denied" in result.reason
    assert engine.total_purges == 0
    assert engine.last_purge_at is None
    assert engine.consecutive_useless == 1


def test_noop_cycle_has_no_side_effects(base_config, fake_api, fake_provider, clock):
    fake_api.used_bytes = int(4 * GB)  # ۲۵٪
    engine = make_engine(base_config, fake_api, fake_provider, clock)
    result = engine.run_cycle()
    assert result.action is Action.NOOP
    assert fake_api.opened == []
    assert fake_api.commands == []


def test_force_cycle_bypasses_threshold(base_config, fake_api, fake_provider, clock):
    fake_api.used_bytes = int(4 * GB)
    engine = make_engine(base_config, fake_api, fake_provider, clock)
    result = engine.run_cycle(force=True)
    assert result.action is Action.OPTIMIZED
    assert "manual run" in result.reason


def test_snapshot_failure_is_handled(base_config, fake_api, fake_provider, clock):
    fake_api.snapshot_failures = 1
    engine = make_engine(base_config, fake_api, fake_provider, clock)
    result = engine.run_cycle()
    assert result.action is Action.SKIPPED
    assert "GlobalMemoryStatusEx" in result.reason


def test_engine_with_api_unavailable(base_config, fake_api, fake_provider, clock):
    fake_api.available = False
    fake_api.load_error = "ویندوز نیست"
    fake_api.memory_snapshot = lambda: None  # type: ignore[method-assign]
    engine = make_engine(base_config, fake_api, fake_provider, clock)
    result = engine.run_cycle()
    assert result.action is Action.SKIPPED
    assert result.reason == "ویندوز نیست"


def test_cycle_result_dict_is_complete():
    result = CycleResult(
        timestamp="2026-01-01T00:00:00",
        action=Action.OPTIMIZED,
        reason="t",
        mode="active",
        used_percent_before=80.0,
        used_percent_after=70.0,
        available_mb_before=2000.0,
        available_mb_after=3500.0,
        trim=TrimReport(considered=3, trimmed=2, freed_bytes=500 * MB),
        purge=PurgeReport(
            attempted=True, purged=True, standby_before_bytes=100 * MB, standby_after_bytes=0
        ),
    )
    data = result.as_dict()
    assert data["freed_mb"] == 1500.0
    assert data["trim"]["freed_mb"] == 500.0
    assert data["purge"]["standby_freed_mb"] == 100.0
    json.dumps(data)  # باید قابل سریالایز باشد


def test_after_optimize_mode_becomes_active_and_cooldown_applies(
    base_config, fake_api, fake_provider, clock
):
    stressed_api(fake_api)
    sizes(fake_api, fake_provider, {400: 900})
    engine = make_engine(base_config, fake_api, fake_provider, clock)

    engine.run_cycle()
    assert engine.mode.value == "active"

    fake_api.used_bytes = int(14 * GB)  # هنوز پرفشار
    second = engine.run_cycle()
    assert second.action is Action.SKIPPED
    assert "cooling down" in second.reason


def test_backoff_increases_after_low_yield(base_config, fake_api, fake_provider, clock):
    stressed_api(fake_api)
    sizes(fake_api, fake_provider, {400: 10})  # آزادسازی ناچیز
    engine = make_engine(base_config, fake_api, fake_provider, clock)
    engine.run_cycle()
    assert engine.consecutive_useless == 1


def test_standby_skip_reason_is_recorded(base_config, fake_api, fake_provider, clock):
    stressed_api(fake_api)
    sizes(fake_api, fake_provider, {400: 2000})  # trim کلی RAM آزاد می‌کند
    config = Config(**{**base_config.__dict__, "min_free_mb_after_trim": 512})
    engine = make_engine(config, fake_api, fake_provider, clock)
    result = engine.run_cycle()
    assert result.action is Action.OPTIMIZED
    assert result.purge is not None
    assert result.purge.purged is False
    assert "already free" in result.purge.skipped_reason
