"""
Build (scons) + flash (pyocd) —— 兼容层。

真正的实现搬到了 scripts/firmware/tools.py（与 BSP 解耦、不再调 build_and_flash.bat）。
这里保留 `build_and_flash()` 这个老接口，ramdump 的 dump 桶还在用它。

Usage:
    from builder import build_and_flash
    build_and_flash()
"""

# __pycache__ 统一写到仓库的 out/pycache（sys.pycache_prefix 只影响设置之后的 import，
# 所以要在所有本地 import 之前，但又必须在 from __future__ 之后）。
import os as _os
import sys as _sys

_d = _os.path.abspath(__file__)
while _d != _os.path.dirname(_d) and not _os.path.exists(_os.path.join(_d, ".git")):
    _d = _os.path.dirname(_d)
_sys.pycache_prefix = _os.path.join(_d, "out", "pycache")

import sys as _s
from pathlib import Path as _Path

_SCRIPTS = _Path(__file__).resolve().parents[2]  # scripts/
if str(_SCRIPTS) not in _s.path:
    _s.path.insert(0, str(_SCRIPTS))

from firmware import tools as _tools  # noqa: E402


def build_and_flash(new_console: bool = False) -> bool:
    """编译并烧录。

    Args:
        new_console: 已废弃 —— 实现改成同窗口输出（原来弹独立 cmd 是为了跑 bat）。
                     保留参数只为不破坏既有调用点。

    Returns:
        True 成功，False 失败。
    """
    if new_console:
        print("[builder] new_console 已废弃（不再经过 bat），本次仍在当前窗口输出")
    return _tools.build_and_flash()


if __name__ == "__main__":
    ok = build_and_flash(new_console=("--new-console" in _s.argv))
    _s.exit(0 if ok else 1)
