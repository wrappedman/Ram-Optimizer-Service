# -*- coding: utf-8 -*-
"""تست حلقه‌ی اجرا، status.json و لاگ‌ها."""

from __future__ import annotations

import logging
import os

from ramopt import paths
from ramopt.config import Config
from ramopt.engine import OptimizerEngine
from ramopt.logging_setup import write_crash
from ramopt.runner import OptimizerRunner
from ramopt.status import StatusWriter, read_status

GB = 1024**3


def make_runner(config: Config, fake_api, fake_provider, clock) -> OptimizerRunner:
    status = StatusWriter()
    engine = OptimizerEngine(config, fake_api, fake_provider, clock=clock.now)
    return OptimizerRunner(config=config, api=fake_api, status=status, engine=engine)


def test_first_cycle_writes_status_file(base_config, fake_api, fake_provider, clock):
    fake_api.used_bytes = int(4 * GB)
    runner = make_runner(base_config, fake_api, fake_provider, clock)
    runner.prepare()
    runner.run_once()

    data = read_status()
    assert data is not None
    assert data["state"] == "running"
    assert data["last_action"] == "noop"
    assert data["counters"]["cycles"] == 1
    assert data["memory"]["used_percent"] > 0
    # فایل به‌صورت معتبر JSON نوشته شده و فایل موقت باقی نمانده است
    leftovers = [n for n in os.listdir(paths.data_dir()) if n.startswith(".status-")]
    assert leftovers == []


def test_optimized_cycle_updates_counters(base_config, fake_api, fake_provider, clock):
    from conftest import set_process_sizes

    fake_api.used_bytes = int(14 * GB)
    set_process_sizes(fake_api, fake_provider, {400: 1500})
    runner = make_runner(base_config, fake_api, fake_provider, clock)
    runner.prepare()
    runner.run_once()

    data = read_status()
    assert data["last_action"] == "optimized"
    assert data["counters"]["purges"] == 1
    assert data["counters"]["freed_mb"] > 0
    assert data["next_allowed_at"] is not None


def test_cycle_exception_is_recorded_not_raised(base_config, fake_api, fake_provider, clock):
    fake_api.used_bytes = int(14 * GB)
    runner = make_runner(base_config, fake_api, fake_provider, clock)

    def boom(*args, **kwargs):
        raise RuntimeError("شبیه‌سازی خرابی")

    runner.engine.run_cycle = boom  # type: ignore[assignment]
    runner.prepare()
    runner.run_once()

    data = read_status()
    assert data["last_action"] == "error"
    assert data["counters"]["errors"] == 1
    assert "شبیه‌سازی خرابی" in data["recent_errors"][0]["message"]


def test_stop_interrupts_the_sleep_immediately(base_config, fake_api, fake_provider, clock):
    """توقف سرویس نباید تا پایان sleep (۶۰ ثانیه) منتظر بماند."""
    config = Config(**{**base_config.__dict__, "check_interval_seconds": 60})
    runner = make_runner(config, fake_api, fake_provider, clock)
    fake_api.used_bytes = int(4 * GB)

    import threading
    import time

    thread = threading.Thread(target=runner.run_forever, daemon=True)
    started = time.monotonic()
    thread.start()
    time.sleep(0.2)
    runner.stop()
    thread.join(timeout=5)
    assert not thread.is_alive(), "حلقه بعد از stop متوقف نشد"
    assert time.monotonic() - started < 5


def test_pause_and_resume_writes_state(base_config, fake_api, fake_provider, clock):
    runner = make_runner(base_config, fake_api, fake_provider, clock)
    runner.prepare()
    runner.pause("تست")
    assert read_status()["state"] == "paused"
    runner.resume()
    assert read_status()["state"] == "running"


def test_status_writer_is_resilient_to_bad_path(tmp_path):
    writer = StatusWriter(path=str(tmp_path / "missing-dir" / "status.json"))
    assert writer.write() is True  # پوشه ساخته می‌شود


def test_logging_respects_configured_level(isolated_data_dir):
    """باگ B11: قبلاً همیشه INFO بود و debug هرگز ثبت نمی‌شد."""
    import importlib

    import ramopt.logging_setup as ls

    importlib.reload(ls)
    config = Config(log_level="debug")
    assert ls.setup_logging(config) is True
    logging.getLogger("RamOptimizer").debug("پیام دیباگ")
    logging.getLogger("RamOptimizer").info("پیام اطلاع")

    with open(paths.log_file(), encoding="utf-8") as handle:
        content = handle.read()
    assert "پیام دیباگ" in content
    assert "پیام اطلاع" in content


def test_crash_log_is_rotated_not_unbounded(isolated_data_dir):
    """باگ B10: crash.log چرخشی است، پس هرگز بی‌نهایت رشد نمی‌کند."""
    from ramopt.logging_setup import CRASH_LOG_MAX_BYTES

    big = "x" * (CRASH_LOG_MAX_BYTES // 2)
    for _ in range(6):
        write_crash(ValueError, ValueError(big), None, note=big)
    data_dir = os.environ["RAMOPT_DATA_DIR"]
    files = [name for name in os.listdir(data_dir) if name.startswith("crash.log")]
    # حداکثر یک فایل جاری + backupCount نسخه‌ی چرخشی، هر کدام کوچک‌تر از سقف
    assert len(files) <= 1 + 2
    for name in files:
        assert os.path.getsize(os.path.join(data_dir, name)) <= CRASH_LOG_MAX_BYTES * 1.1
    assert any(name != "crash.log" for name in files)  # چرخش واقعاً اتفاق افتاده


def test_setup_logging_is_idempotent(isolated_data_dir):
    import importlib

    import ramopt.logging_setup as ls

    importlib.reload(ls)
    logger = logging.getLogger("RamOptimizer")
    before = len(logger.handlers)
    ls.setup_logging(Config())
    middle = len(logger.handlers)
    ls.setup_logging(Config())
    assert len(logger.handlers) == middle
    assert middle >= before
