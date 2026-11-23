# -*- coding: utf-8 -*-
"""تست پیکربندی: پیش‌فرض‌ها، اعتبارسنجی و مقاومت در برابر فایل خراب."""

from __future__ import annotations

import configparser
import os

from ramopt.config import (
    Config,
    config_from_parser,
    default_config_text,
    load_config,
    write_default_config,
)


def parser_from(text: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None)
    parser.read_string(text)
    return parser


def test_defaults_are_the_documented_ones():
    """آستانه‌ی پیش‌فرض باید همان ۷۵٪ مستندشده باشد (باگ B1 نسخه‌ی قبل)."""
    config = Config()
    assert config.trigger_percent == 75
    assert config.reset_percent < config.trigger_percent
    assert config.check_interval_seconds == 60
    assert config.purge_standby_list is True


def test_missing_file_returns_defaults():
    config, issues = load_config("/nonexistent/path/config.ini")
    assert config.trigger_percent == 75
    assert issues == []


def test_exclude_matching_is_case_insensitive_and_supports_patterns():
    config = Config()
    assert config.is_excluded("DWM.EXE")
    assert config.is_excluded("dwm.exe")
    assert config.is_excluded("MsMpEng.exe")  # از طریق الگوی msmpeng*
    assert config.is_excluded("chrome.exe") is False
    assert config.is_excluded("") is False


def test_invalid_values_fall_back_with_issue():
    parser = parser_from(
        """
        [policy]
        trigger_percent = banana
        reset_percent = 900
        """
    )
    issues = []
    config = config_from_parser(parser, issues)
    assert config.trigger_percent == 75
    assert config.reset_percent == 65
    assert len(issues) == 2
    assert {issue.key for issue in issues} == {"trigger_percent", "reset_percent"}


def test_reset_must_be_below_trigger():
    parser = parser_from(
        """
        [policy]
        trigger_percent = 80
        reset_percent = 85
        """
    )
    issues = []
    config = config_from_parser(parser, issues)
    assert config.reset_percent < config.trigger_percent
    assert config.reset_percent == 70
    assert any(issue.key == "reset_percent" for issue in issues)


def test_bool_parsing_accepts_common_spellings():
    parser = parser_from(
        """
        [standby]
        purge = no
        [safety]
        skip_on_battery = YES
        """
    )
    config = config_from_parser(parser)
    assert config.purge_standby_list is False
    assert config.skip_on_battery is True


def test_quiet_hours_normalization_and_invalid_input():
    config = config_from_parser(parser_from("[safety]\nquiet_hours = 23:00-06:30\n"))
    assert config.quiet_hours == "23:00-06:30"

    issues = []
    bad = config_from_parser(parser_from("[safety]\nquiet_hours = 25:99-xx\n"), issues)
    assert bad.quiet_hours == ""
    assert issues


def test_custom_exclude_list_replaces_defaults():
    config = config_from_parser(parser_from("[targets]\nexclude = foo.exe, bar.exe\n"))
    assert config.exclude == ("foo.exe", "bar.exe")
    assert "dwm.exe" not in config.exclude


def test_generated_ini_round_trips():
    """فایل نمونه‌ای که خودمان تولید می‌کنیم باید بدون هیچ ایرادی خوانده شود."""
    text = default_config_text()
    issues: list = []
    config = config_from_parser(parser_from(text), issues)
    assert issues == [], [f"{i.key}: {i.message}" for i in issues]
    assert config.trigger_percent == 75
    assert config.is_excluded("dwm.exe")


def test_write_default_config_respects_existing(tmp_path, isolated_data_dir):
    path = os.path.join(str(isolated_data_dir), "config.ini")
    first = write_default_config(path)
    assert os.path.isfile(first)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("[policy]\ntrigger_percent = 88\n")

    write_default_config(path)  # بدون overwrite نباید تغییر کند
    with open(path, encoding="utf-8") as handle:
        assert "88" in handle.read()

    write_default_config(path, overwrite=True)
    with open(path, encoding="utf-8") as handle:
        assert "88" not in handle.read()


def test_corrupt_ini_does_not_crash():
    parser_text = "this is not an ini file at all"
    try:
        parser = parser_from(parser_text)
    except configparser.Error:
        return  # رفتار مورد انتظار: خطای قابل گرفتن
    config_from_parser(parser)  # یا با موفقیت پیش‌فرض‌ها
