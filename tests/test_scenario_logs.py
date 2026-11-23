# -*- coding: utf-8 -*-
"""سناریوی کامل، از دید «لاگ»: هر یک دقیقه + واکنش فوری.

تست‌های ``test_critical_mode.py`` تصمیم و فاصله را جدا می‌سنجند؛ اینجا کل
حلقه اجرا می‌شود و لاگ واقعی ثبت‌شده بررسی می‌شود — همان چیزی که کاربر در
``build\\Manage-RamOptimizer.bat`` → گزینه‌ی ۴ (لاگ‌ها) می‌بیند.

اگر این فایل پاس شود یعنی:

* در حالت عادی، بررسی بعدی ۶۰ ثانیه بعد است (شمارش با ساعت جعلی، بدون sleep)؛
* به‌محض عبور از آستانه‌ی بحرانی، در همان بررسی پاس آزادسازی اجرا می‌شود و
  فاصله‌ی بعدی ۵ ثانیه می‌شود (یعنی سرویس خواب یک‌دقیقه‌ای نمی‌رود).
"""

from __future__ import annotations

import datetime as dt
import logging

from conftest import FakeApi, FakeClock, FakeProvider
from ramopt.config import Config
from ramopt.engine import Action, OptimizerEngine
from ramopt.runner import OptimizerRunner
from ramopt.status import StatusWriter

GB = 1024**3


def _runner(api: FakeApi, provider: FakeProvider, clock: FakeClock, config) -> OptimizerRunner:
    engine = OptimizerEngine(config, api, provider, clock=clock.now)
    return OptimizerRunner(config=config, api=api, status=StatusWriter(), engine=engine)


from test_critical_mode import make_config  # noqa: E402  (همان پیکربندی تست)


def test_minute_cycle_then_immediate_critical_pass(caplog):
    caplog.set_level(logging.INFO)
    api, provider, clock = FakeApi(), FakeProvider(), FakeClock()
    config = make_config()

    # --- ۱) شروع آرام: ۶۰٪ مصرف، پایین‌تر از آستانه‌ی ۷۵٪ --------------------
    api.used_bytes = int(9.6 * GB)
    runner = _runner(api, provider, clock, config)
    runner.run_once()
    assert runner.engine.mode.value in {"idle", "armed"}
    assert runner.next_interval() == 60

    # --- ۲) چند چرخه‌ی عادی: فاصله همیشه ۶۰ ثانیه -------------------------
    for _ in range(3):
        clock.advance(59)  # هنوز دقیقه‌ی بعد نشده
        assert runner.next_interval() == 60
        clock.advance(1)
        runner.run_once()
    assert runner.status.counters["cycles"] == 4
    assert runner.next_interval() == 60

    # --- ۳) رم بحرانی می‌شود (۹۳.۵٪) --------------------------------------
    caplog.clear()
    api.used_bytes = int(14.96 * GB)
    provider.working_sets = {pid: size for pid, size in provider.working_sets.items()}
    before = runner.status.counters.get("purges", 0)

    runner.run_once()

    # بلافاصله (در همان بررسی، بدون صبر کردن برای دقیقه‌ی بعد) پاک‌سازی شد
    assert runner.status.counters.get("purges", 0) == before + 1
    assert runner.status.extra["critical"] is True
    assert runner.status.last_action == Action.OPTIMIZED.value

    # و بررسی بعدی ۵ ثانیه بعد است، نه ۶۰ ثانیه
    assert runner.next_interval() == config.critical_poll_seconds == 5

    # --- ۴) شواهد در لاگ --------------------------------------------------
    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "CRITICAL" in text, text
    assert "acting immediately" in text, text
    assert "pass complete" in text, text

    # --- ۵) بازگشت به حالت عادی: دوباره ۶۰ ثانیه --------------------------
    api.used_bytes = int(4 * GB)
    runner.run_once()
    assert runner.status.extra["critical"] is False
    assert runner.next_interval() == 60


def test_loop_wakes_up_immediately_when_memory_turns_critical(caplog):
    """اگر در میانه‌ی خواب یک‌دقیقه‌ای رم بحرانی شود، حلقه همان لحظه بیدار می‌شود.

    ``Event.wait`` را جایگزین می‌کنیم تا بدون sleep واقعی، ترتیب بیدار شدن‌ها را
    ببینیم. سناریو:

    * چرخه ۱ آرام (۶۰٪) → تصمیم بعدی: ۶۰ ثانیه خواب؛
    * در همان خواب، در ثانیه‌ی ۲ رم به ۹۴٪ می‌رسد → باید بیدار شود (نه ثانیه‌ی ۶۰)؛
    * چرخه ۲ پاک‌سازی فوری، سپس بررسی‌ها هر ۵ ثانیه؛
    * رم پایین می‌آید → برگشت به ۶۰ ثانیه.
    """
    caplog.set_level(logging.INFO)
    api, provider, clock = FakeApi(), FakeProvider(), FakeClock()
    config = make_config()
    runner = _runner(api, provider, clock, config)

    sleeps: list[float] = []
    RUN_START = clock.current
    fired = {"critical": False, "calm": False}

    def fake_wait(seconds: float) -> bool:
        sleeps.append(seconds)
        clock.advance(seconds)
        # رویدادها بر اساس «پیشرفت ساعت» تعریف می‌شوند تا به تعداد probeها
        # وابسته نباشیم. چرخه ۱ در t=0 تمام شد (نه ۶۰٪).
        if clock.current >= RUN_START + dt.timedelta(seconds=2) and not fired["critical"]:
            fired["critical"] = True
            api.used_bytes = int(15 * GB)  # ۹۳.۷٪ — وسط خواب یک‌دقیقه‌ای
        elif clock.current >= RUN_START + dt.timedelta(seconds=12) and not fired["calm"]:
            fired["calm"] = True
            api.used_bytes = int(4 * GB)
        elif clock.current >= RUN_START + dt.timedelta(seconds=22):
            runner.stop()
        return False

    runner._stop_event.wait = fake_wait  # type: ignore[method-assign]

    api.used_bytes = int(9 * GB)  # ۶۰٪
    runner.run_forever()

    # خواب اول به قطعه‌های ۲ ثانیه‌ای (probe) شکسته شد و خیلی زودتر از ۶۰
    # ثانیه بیدار شدیم — یعنی «فوراً» واقعاً فوری است.
    assert sleeps[0] == config.critical_probe_seconds == 2
    assert 2 in sleeps and sleeps.index(2) == 0
    # هیچ خوابی طولانی نیست: همه در حد probe یا فاصله‌ی بحرانی
    assert all(s <= config.critical_probe_seconds for s in sleeps), sleeps
    # وقتی بحرانی شد، فوراً چرخه اجرا شد و یک پاس آزادسازی انجام شد
    assert runner.status.counters["cycles"] >= 2
    assert runner.status.counters.get("purges", 0) >= 1

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "went critical" in text or "critical became" in text or "turned critical" in text, text
    assert runner.status.state == "stopped"


def test_wait_next_honours_stop_and_can_disable_probing():
    api, provider, clock = FakeApi(), FakeProvider(), FakeClock()
    config = make_config()
    runner = _runner(api, provider, clock, config)

    # با probe خاموش، یک wait معمولی (بدون شکستن به قطعه‌ها)
    runner.config = Config(**{**config.__dict__, "critical_probe_seconds": 0})
    sleeps: list[float] = []
    runner._stop_event.wait = lambda seconds: sleeps.append(seconds) or True
    assert runner.wait_next(60) is True
    assert sleeps == [60]

    # درخواست توقف، حتی قبل از پایان خواب، حلقه را خارج می‌کند
    runner.config = make_config()
    runner._stop_event.wait = lambda seconds: runner.stop() or True
    assert runner.wait_next(60) is True


def test_verify_command_reports_the_interval_and_critical_path(capsys, monkeypatch):
    """``ramopt verify`` باید همان دو عدد کلیدی را نشان دهد و مسیر بحرانی را
    بدون تغییر سیستم تأیید کند."""
    from ramopt import cli

    monkeypatch.setenv("RAMOPT_DATA_DIR", "/tmp/ramopt-verify-test")
    code = cli.main(["verify", "--simulate-critical"])
    assert code == 0
    out = capsys.readouterr().out
    # خروجی انگلیسی است (پنل و ابزار خط فرمان برای بین‌المللی بودن انگلیسی‌اند)
    assert "every 60 s" in out
    assert "92%" in out
    assert "T+0s" in out
    assert "critical=True" in out
    assert "T+5s" in out
