# -*- coding: utf-8 -*-
"""پیکربندی برنامه — مقادیر پیش‌فرض + فایل ``config.ini``.

فلسفه: برنامه بدون هیچ پیکربندی هم درست کار می‌کند (همه‌ی مقادیر پیش‌فرض
محافظه‌کارانه‌اند)، اما کاربر می‌تواند بدون بیلد دوباره، فایل ini را در
``%ProgramData%\\RamOptimizer\\config.ini`` ویرایش کند.

نمونه‌ی فایل::

    [general]
    check_interval_seconds = 60

    [policy]
    trigger_percent = 75
    reset_percent   = 65
    cooldown_seconds = 300
    max_purges_per_hour = 6

    [standby]
    purge = true
    min_free_mb_after_trim = 512

    [targets]
    min_process_ws_mb = 20
    max_processes = 64
    exclude = dwm.exe, csrss.exe, lsass.exe

    [safety]
    skip_when_fullscreen = true
    skip_on_battery = false
    quiet_hours = 23:00-06:00
    startup_delay_seconds = 60

    [logging]
    level = info

هر کلید ناشناخته یا مقدار نامعتبر، نادیده گرفته می‌شود و در لاگ ثبت می‌شود تا
یک فایل خراب برنامه را از کار نیندازد.
"""

from __future__ import annotations

import configparser
import dataclasses
import fnmatch
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("RamOptimizer")

# ----------------------------------------------------------------------------
# پیش‌فرض‌ها
# ----------------------------------------------------------------------------

#: پروسه‌هایی که هرگز نباید working setشان خالی شود.
#: این لیست محافظه‌کارانه است: فرآیندهای حیاتی ویندوز + آنتی‌ویروس‌های رایج.
DEFAULT_EXCLUDES: tuple[str, ...] = (
    "system",
    "system idle process",
    "registry",
    "memory compression",
    "secure system",
    "idle",
    "smss.exe",
    "csrss.exe",
    "wininit.exe",
    "winlogon.exe",
    "services.exe",
    "lsass.exe",
    "lsm.exe",
    "svchost.exe",
    "fontdrvhost.exe",
    "dwm.exe",
    "explorer.exe",
    "sihost.exe",
    "ctfmon.exe",
    "audiodg.exe",
    "msmpeng.exe",
    "nissrv.exe",
    "mpdefendercoreservice.exe",
    "securityhealthservice.exe",
    "avp.exe",
    "avgsvc.exe",
    "ekrn.exe",
    "bdservicehost.exe",
)

#: پسوند/الگوهایی که همیشه کنار گذاشته می‌شوند (آنتی‌ویروس‌های دیگر).
DEFAULT_EXCLUDE_PATTERNS: tuple[str, ...] = (
    "msmpeng*",
    "mpcmdrun*",
    "*defender*",
)


@dataclass
class Config:
    """همه‌ی تنظیمات به‌صورت یک دیتاکلاس تغییرناپذیر (تا جای ممکن)."""

    # --- general ---
    check_interval_seconds: int = 60
    startup_delay_seconds: int = 60

    # --- policy ---
    #: رسیدن به این درصد، پاک‌سازی را فعال می‌کند.
    trigger_percent: int = 75
    #: تا وقتی درصد به این مقدار نرسیده، حالت فعال باقی می‌ماند (هیسترزیس).
    reset_percent: int = 65
    #: حداقل فاصله بین دو پاک‌سازی.
    cooldown_seconds: int = 300
    #: سقف تعداد پاک‌سازی در هر ساعت (۰ = بی‌نهایت).
    max_purges_per_hour: int = 6
    #: حداقل حافظه‌ی آزاد مطلق؛ اگر حتی در حالت پرفشار هم این مقدار آزاد
    #: باشد، پاک‌سازی لازم نیست. (۰ = غیرفعال)
    min_available_mb: int = 0

    # --- standby ---
    purge_standby_list: bool = True
    #: بعد از trim، فقط اگر حافظه‌ی آزاد کمتر از این مقدار باشد Standby List
    #: هم خالی می‌شود. (۰ = همیشه خالی کن، مثل قبل)
    min_free_mb_after_trim: int = 512
    flush_modified_list: bool = False

    # --- targets ---
    #: پروسه‌های کوچک‌تر از این مقدار دست نمی‌خورند.
    min_process_ws_mb: int = 20
    #: حداکثر تعداد پروسه در هر دور (۰ = بی‌نهایت).
    max_processes: int = 64
    exclude: tuple[str, ...] = DEFAULT_EXCLUDES
    exclude_patterns: tuple[str, ...] = DEFAULT_EXCLUDE_PATTERNS

    # --- safety ---
    skip_when_fullscreen: bool = True
    skip_on_battery: bool = False
    #: بازه‌ی سکوت به شکل "HH:MM-HH:MM" یا خالی.
    quiet_hours: str = ""

    # --- logging ---
    log_level: str = "info"

    def normalized_excludes(self) -> tuple[str, ...]:
        return tuple(name.strip().lower() for name in self.exclude if name.strip())

    def normalized_patterns(self) -> tuple[str, ...]:
        return tuple(p.strip().lower() for p in self.exclude_patterns if p.strip())

    def is_excluded(self, process_name: str) -> bool:
        """آیا این پروسه در لیست استثنا است؟ (case-insensitive)"""
        name = (process_name or "").strip().lower()
        if not name:
            return False
        if name in self.normalized_excludes():
            return True
        return any(fnmatch.fnmatch(name, pattern) for pattern in self.normalized_patterns())


# ----------------------------------------------------------------------------
# اعتبارسنجی
# ----------------------------------------------------------------------------


@dataclass
class ValidationIssue:
    section: str
    key: str
    value: str
    message: str


def _get_int(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    default: int,
    issues: list[ValidationIssue],
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if not parser.has_option(section, key):
        return default
    raw = parser.get(section, key, fallback="")
    try:
        value = int(float(raw.strip()))
    except (TypeError, ValueError):
        issues.append(
            ValidationIssue(section, key, raw, "عدد صحیح نامعتبر — مقدار پیش‌فرض استفاده شد")
        )
        return default
    if value < minimum:
        issues.append(
            ValidationIssue(
                section, key, raw, f"کمتر از حد مجاز ({minimum}) — مقدار پیش‌فرض استفاده شد"
            )
        )
        return default
    if maximum is not None and value > maximum:
        issues.append(
            ValidationIssue(
                section, key, raw, f"بیشتر از حد مجاز ({maximum}) — مقدار پیش‌فرض استفاده شد"
            )
        )
        return default
    return value


def _get_bool(
    parser: configparser.ConfigParser,
    section: str,
    key: str,
    default: bool,
    issues: list[ValidationIssue],
) -> bool:
    if not parser.has_option(section, key):
        return default
    raw = parser.get(section, key, fallback="")
    stripped = raw.strip().lower()
    if stripped in {"1", "true", "yes", "on", "enabled", "بله"}:
        return True
    if stripped in {"0", "false", "no", "off", "disabled", "خیر"}:
        return False
    issues.append(
        ValidationIssue(section, key, raw, "مقدار بولی نامعتبر — مقدار پیش‌فرض استفاده شد")
    )
    return default


def _parse_time_range(raw: str) -> str:
    """``"23:00-06:00"`` را نرمال می‌کند؛ ورودی نامعتبر را خالی برمی‌گرداند."""
    text = (raw or "").strip()
    if not text:
        return ""
    try:
        start, end = text.split("-", 1)
        sh, sm = (int(part) for part in start.strip().split(":", 1))
        eh, em = (int(part) for part in end.strip().split(":", 1))
    except (ValueError, TypeError):
        return ""
    if not (0 <= sh <= 23 and 0 <= eh <= 23 and 0 <= sm <= 59 and 0 <= em <= 59):
        return ""
    return f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d}"


def config_from_parser(
    parser: configparser.ConfigParser, issues: list[ValidationIssue] | None = None
) -> Config:
    """ساخت ``Config`` از یک ``ConfigParser`` با اعتبارسنجی کامل."""
    issues = issues if issues is not None else []
    defaults = Config()

    config = Config(
        check_interval_seconds=_get_int(
            parser,
            "general",
            "check_interval_seconds",
            defaults.check_interval_seconds,
            issues,
            minimum=10,
            maximum=3600,
        ),
        startup_delay_seconds=_get_int(
            parser,
            "general",
            "startup_delay_seconds",
            defaults.startup_delay_seconds,
            issues,
            minimum=0,
            maximum=3600,
        ),
        trigger_percent=_get_int(
            parser,
            "policy",
            "trigger_percent",
            defaults.trigger_percent,
            issues,
            minimum=30,
            maximum=99,
        ),
        reset_percent=_get_int(
            parser,
            "policy",
            "reset_percent",
            defaults.reset_percent,
            issues,
            minimum=5,
            maximum=98,
        ),
        cooldown_seconds=_get_int(
            parser,
            "policy",
            "cooldown_seconds",
            defaults.cooldown_seconds,
            issues,
            minimum=0,
            maximum=86400,
        ),
        max_purges_per_hour=_get_int(
            parser,
            "policy",
            "max_purges_per_hour",
            defaults.max_purges_per_hour,
            issues,
            minimum=0,
            maximum=120,
        ),
        min_available_mb=_get_int(
            parser,
            "policy",
            "min_available_mb",
            defaults.min_available_mb,
            issues,
            minimum=0,
            maximum=1_048_576,
        ),
        purge_standby_list=_get_bool(
            parser, "standby", "purge", defaults.purge_standby_list, issues
        ),
        min_free_mb_after_trim=_get_int(
            parser,
            "standby",
            "min_free_mb_after_trim",
            defaults.min_free_mb_after_trim,
            issues,
            minimum=0,
            maximum=1_048_576,
        ),
        flush_modified_list=_get_bool(
            parser, "standby", "flush_modified_list", defaults.flush_modified_list, issues
        ),
        min_process_ws_mb=_get_int(
            parser,
            "targets",
            "min_process_ws_mb",
            defaults.min_process_ws_mb,
            issues,
            minimum=0,
            maximum=1_048_576,
        ),
        max_processes=_get_int(
            parser,
            "targets",
            "max_processes",
            defaults.max_processes,
            issues,
            minimum=0,
            maximum=4096,
        ),
        skip_when_fullscreen=_get_bool(
            parser, "safety", "skip_when_fullscreen", defaults.skip_when_fullscreen, issues
        ),
        skip_on_battery=_get_bool(
            parser, "safety", "skip_on_battery", defaults.skip_on_battery, issues
        ),
    )

    # لیست استثناها
    if parser.has_option("targets", "exclude"):
        raw = parser.get("targets", "exclude", fallback="")
        entries = tuple(item.strip() for item in raw.split(",") if item.strip())
        # اگر کاربر لیست را خالی گذاشت، یعنی «هیچ استثنایی» (خطرناک اما خواسته‌ی او)
        config.exclude = entries
    if parser.has_option("targets", "exclude_patterns"):
        raw_patterns = parser.get("targets", "exclude_patterns", fallback="")
        config.exclude_patterns = tuple(
            item.strip() for item in raw_patterns.split(",") if item.strip()
        )

    # ساعات سکوت
    if parser.has_option("safety", "quiet_hours"):
        raw = parser.get("safety", "quiet_hours", fallback="")
        normalized = _parse_time_range(raw)
        if raw.strip() and not normalized:
            issues.append(
                ValidationIssue(
                    "safety", "quiet_hours", raw, "قالب نامعتبر (نمونه‌ی درست: 23:00-06:00)"
                )
            )
        config.quiet_hours = normalized

    # سطح لاگ
    if parser.has_option("logging", "level"):
        raw = parser.get("logging", "level", fallback="").strip().lower()
        if raw in {"debug", "info", "warning", "error", "critical"}:
            config.log_level = raw
        elif raw:
            issues.append(
                ValidationIssue("logging", "level", raw, "سطح لاگ نامعتبر — مقدار info استفاده شد")
            )

    # سازگاری سیاست
    if config.reset_percent >= config.trigger_percent:
        issues.append(
            ValidationIssue(
                "policy",
                "reset_percent",
                str(config.reset_percent),
                "باید کمتر از trigger_percent باشد — مقدار trigger_percent-10 استفاده شد",
            )
        )
        config.reset_percent = max(0, config.trigger_percent - 10)

    return config


def load_config(path: str | None = None) -> tuple[Config, list[ValidationIssue]]:
    """خواندن پیکربندی از فایل. اگر فایل نبود، پیش‌فرض‌ها برمی‌گردند."""
    from ramopt import paths

    config_path = path or paths.config_file()
    issues: list[ValidationIssue] = []

    if not os.path.isfile(config_path):
        return Config(), issues

    parser = configparser.ConfigParser(interpolation=None)
    try:
        with open(config_path, encoding="utf-8-sig") as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error) as exc:
        issues.append(ValidationIssue("file", config_path, "", f"خواندن فایل ناموفق بود: {exc}"))
        return Config(), issues

    return config_from_parser(parser, issues), issues


def default_config_text(config: Config | None = None) -> str:
    """متن ``config.ini`` نمونه (همان چیزی که با ``ramopt config --init`` ساخته می‌شود)."""
    cfg = config or Config()
    lines = [
        "; Ram Optimizer Service — فایل پیکربندی",
        "; هر تغییری بعد از ری‌استارت سرویس اعمال می‌شود:  sc stop RamOptimizerService && sc start RamOptimizerService",
        "; مقادیر با «;» کامنت می‌شوند. حذف یک کلید یعنی استفاده از مقدار پیش‌فرض.",
        "",
        "[general]",
        "; هر چند ثانیه بررسی شود (۱۰ تا ۳۶۰۰)",
        f"check_interval_seconds = {cfg.check_interval_seconds}",
        "; تأخیر بعد از بوت تا سرویس‌های دیگر بالا بیایند",
        f"startup_delay_seconds = {cfg.startup_delay_seconds}",
        "",
        "[policy]",
        "; آستانه‌ی شروع پاک‌سازی (درصد)",
        f"trigger_percent = {cfg.trigger_percent}",
        "; پاک‌سازی تا وقتی مصرف به این درصد نرسد تکرار نمی‌شود (هیسترزیس)",
        f"reset_percent = {cfg.reset_percent}",
        "; حداقل فاصله بین دو پاک‌سازی (ثانیه)",
        f"cooldown_seconds = {cfg.cooldown_seconds}",
        "; سقف پاک‌سازی در هر ساعت (۰ = بی‌نهایت)",
        f"max_purges_per_hour = {cfg.max_purges_per_hour}",
        "; اگر این مقدار حافظه آزاد باشد هرگز پاک‌سازی نمی‌شود (۰ = غیرفعال)",
        f"min_available_mb = {cfg.min_available_mb}",
        "",
        "[standby]",
        "; خالی کردن Standby List (کش حافظه)",
        f"purge = {'true' if cfg.purge_standby_list else 'false'}",
        "; خالی کردن کش فقط اگر بعد از trim هنوز کمتر از این مقدار آزاد است",
        f"min_free_mb_after_trim = {cfg.min_free_mb_after_trim}",
        "; نوشتن صفحات تغییرکرده روی دیسک (به‌طور پیش‌فرض خاموش)",
        f"flush_modified_list = {'true' if cfg.flush_modified_list else 'false'}",
        "",
        "[targets]",
        "; پروسه‌های کوچک‌تر از این مقدار (مگابایت) دست نمی‌خورند",
        f"min_process_ws_mb = {cfg.min_process_ws_mb}",
        "; حداکثر تعداد پروسه در هر دور (۰ = بی‌نهایت)",
        f"max_processes = {cfg.max_processes}",
        "; پروسه‌های مستثنا (نام دقیق، جدا با کاما)",
        f"exclude = {', '.join(cfg.exclude)}",
        "; الگوهای wildcard برای استثنا",
        f"exclude_patterns = {', '.join(cfg.exclude_patterns)}",
        "",
        "[safety]",
        "; وقتی کاربر بازی/برنامه‌ی تمام‌صفحه اجرا می‌کند پاک‌سازی نکن",
        f"skip_when_fullscreen = {'true' if cfg.skip_when_fullscreen else 'false'}",
        "; روی باتری پاک‌سازی نکن",
        f"skip_on_battery = {'true' if cfg.skip_on_battery else 'false'}",
        "; بازه‌ی سکوت (خالی = غیرفعال)",
        f"quiet_hours = {cfg.quiet_hours}",
        "",
        "[logging]",
        "; debug | info | warning | error",
        f"level = {cfg.log_level}",
        "",
    ]
    return "\r\n".join(lines)


def write_default_config(path: str | None = None, overwrite: bool = False) -> str:
    """نوشتن فایل پیکربندی نمونه. مسیر فایل را برمی‌گرداند."""
    from ramopt import paths

    config_path = path or paths.config_file()
    os.makedirs(os.path.dirname(config_path) or ".", exist_ok=True)
    if os.path.exists(config_path) and not overwrite:
        return config_path
    with open(config_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(default_config_text())
    return config_path


def as_dict(config: Config) -> dict[str, object]:
    """نمایش قابل سریالایز کردن (برای status.json و لاگ)."""
    data = dataclasses.asdict(config)
    data["exclude"] = list(config.exclude)
    data["exclude_patterns"] = list(config.exclude_patterns)
    return data


__all__ = [
    "DEFAULT_EXCLUDES",
    "DEFAULT_EXCLUDE_PATTERNS",
    "Config",
    "ValidationIssue",
    "as_dict",
    "config_from_parser",
    "default_config_text",
    "load_config",
    "write_default_config",
]
