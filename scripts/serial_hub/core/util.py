#!/usr/bin/env python3
"""通用小工具：时间戳、字节数人话、仓库根定位。"""

from __future__ import annotations

import os
from datetime import datetime


def ts() -> str:
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def human(n: int) -> str:
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KB" % (n / 1024.0)
    return "%.2f MB" % (n / 1024.0 / 1024.0)


def repo_root() -> str:
    """本文件在 scripts/serial_hub/core/util.py —— 往上四级才是仓库根。"""
    here = os.path.dirname(os.path.abspath(__file__))  # .../scripts/serial_hub/core
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))
