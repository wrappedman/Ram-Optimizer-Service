# -*- coding: utf-8 -*-
"""تولید ``build/build_info.json`` و ``build/SHA256SUMS.txt``.

این فایل‌ها بعد از بیلد ساخته می‌شوند تا کاربر بداند کدام نسخه از چه کدی و
با چه هشی ساخته شده است.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _console import force_utf8_console, say

from ramopt.version import __version__, build_info

EXE_RELATIVE = os.path.join("build", "RamOptimizerService", "RamOptimizerService.exe")


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=20
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    force_utf8_console()
    exe_path = os.path.join(ROOT, EXE_RELATIVE)
    if not os.path.isfile(exe_path):
        say(f"[خطا] exe پیدا نشد: {exe_path}")
        return 1

    info = build_info()
    payload = {
        "version": __version__,
        "built_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git("rev-parse", "HEAD"),
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "python": info["python"],
        "platform": info["platform"],
        "exe": EXE_RELATIVE.replace("\\", "/"),
        "exe_sha256": sha256(exe_path),
        "exe_size_bytes": os.path.getsize(exe_path),
        "build_mode": "onedir",
    }

    os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)
    with open(os.path.join(ROOT, "build", "build_info.json"), "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    with open(os.path.join(ROOT, "build", "SHA256SUMS.txt"), "w", encoding="utf-8") as handle:
        handle.write(f"{payload['exe_sha256']}  {payload['exe']}\n")

    say(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
