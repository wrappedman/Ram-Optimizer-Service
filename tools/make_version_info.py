# -*- coding: utf-8 -*-
"""تولید ``version_info.txt`` برای exe (نسخه‌ای که در Properties ویندوز دیده می‌شود).

بدون این فایل، exe در Explorer هیچ نسخه‌ای ندارد و پشتیبانی از کاربر سخت می‌شود.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _console import force_utf8_console, say  # noqa: E402

from ramopt.version import SERVICE_DESCRIPTION, __version__

TEMPLATE = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={tuple_version},
    prodvers={tuple_version},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'Ram Optimizer Service'),
         StringStruct('FileDescription', '{description}'),
         StringStruct('FileVersion', '{version}'),
         StringStruct('InternalName', 'RamOptimizerService'),
         StringStruct('LegalCopyright', 'GNU GPL v3'),
         StringStruct('OriginalFilename', 'RamOptimizerService.exe'),
         StringStruct('ProductName', 'RAM Optimizer Service'),
         StringStruct('ProductVersion', '{version}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def version_tuple(version: str) -> tuple[int, int, int, int]:
    parts = [int(part) for part in version.split(".") if part.isdigit()]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])  # type: ignore[return-value]


def main() -> int:
    force_utf8_console()
    target = os.path.join(ROOT, "version_info.txt")
    content = TEMPLATE.format(
        tuple_version=version_tuple(__version__),
        version=__version__,
        description=SERVICE_DESCRIPTION.split(" | ")[0],
    )
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
    say(f"version_info.txt نوشته شد ({__version__}) -> {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
