# -*- coding: utf-8 -*-
"""اجرای بسته با ``python -m ramopt`` — معادل دستور نصب‌شده‌ی ``ramopt``."""

from __future__ import annotations

import sys

from ramopt.cli import main

if __name__ == "__main__":
    sys.exit(main())
