"""هر چیزی که کاربر یا لاگ می‌بیند باید انگلیسی و ASCII باشد.

چرا؟ کنسول ویندوز با code page پیش‌فرض (cp1252/cp437) نمی‌تواند حروف فارسی را
نمایش دهد؛ نتیجه یا ``?`` است یا (بدتر) خروجی خراب. روزی که پنل مدیریت را
نوشتیم، همین موضوع باعث شد همه‌ی منو به شکل ``u{067E}u{0646}...`` دیده شود.

پس قرارداد پروژه: **رشته‌های خروجی** انگلیسی؛ توضیحات کد و پیام‌های فارسی
فقط در مستندات. این تست از بازگشتِ ناخواسته‌ی متن فارسی به خروجی جلوگیری
می‌کند.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from ramopt import config as config_mod

PACKAGE = pathlib.Path(__file__).resolve().parent.parent / "ramopt"

#: حروف فارسی/عربی + ارقام فارسی (نشانه‌ی متن فارسی در خروجی)
PERSIAN_RANGES = ((0x0600, 0x06FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF))

#: توابعی که خروجی‌شان مستقیم به کاربر/لاگ می‌رود
USER_FACING_CALLS = {"_print", "print", "say", "_log"}


def _has_persian(text: str) -> bool:
    for char in text:
        code = ord(char)
        if any(low <= code <= high for low, high in PERSIAN_RANGES):
            return True
    return False


def _string_literals(node: ast.AST) -> list[str]:
    values: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            values.append(child.value)
    return values


def _user_facing_strings(path: pathlib.Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute | ast.Name):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr
        is_logger = name in {"debug", "info", "warning", "error", "exception", "critical"}
        if name in USER_FACING_CALLS or (is_logger and isinstance(node.func, ast.Attribute)):
            for value in _string_literals(node):
                found.append((getattr(node, "lineno", 0), value))
    return found


@pytest.mark.parametrize("path", sorted(PACKAGE.glob("*.py")), ids=lambda p: p.name)
def test_user_facing_strings_are_english(path: pathlib.Path) -> None:
    offenders = [
        f"{path.name}:{line}: {text!r}"
        for line, text in _user_facing_strings(path)
        if _has_persian(text)
    ]
    assert not offenders, "user-facing text must be English (ASCII):\n" + "\n".join(offenders)


def test_generated_config_file_is_ascii_and_english() -> None:
    text = config_mod.default_config_text()
    assert _has_persian(text) is False
    text.encode("ascii")  # هر کاراکتر غیر ASCII اینجا خطا می‌دهد
    assert "RAM Optimizer Service" in text
    assert "trigger_percent = 75" in text


def test_service_description_is_english() -> None:
    from ramopt.version import SERVICE_DESCRIPTION

    assert not _has_persian(SERVICE_DESCRIPTION)
    SERVICE_DESCRIPTION.encode("ascii")
