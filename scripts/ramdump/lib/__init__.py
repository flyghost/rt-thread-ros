# -*- coding: utf-8 -*-
"""ramdump 工具的共享库（build / dump / test 三个桶都从这里取）。

依赖方向只有一条：**桶 → lib**，桶与桶之间不互相 import
（dump 想编译就调 `lib.builder.build_and_flash()`，而不是 import build 桶）。

这里不做花哨的 re-export，只把 `lib/` 挂到 sys.path 上，让库内部保持
`from config import ...` 这种扁平导入 —— 与合并前的脚本逐字一致，便于对账：

    from lib import config, serial_utils, console, ymodem_receiver, builder
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))  # scripts/ramdump/lib
_ROOT = os.path.dirname(_HERE)  # scripts/ramdump

for _p in (_HERE, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

__all__ = ["config", "serial_utils", "console", "ymodem_receiver", "builder"]
