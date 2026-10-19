"""
Build (scons) + flash (pyocd) —— 兼容层。

真正的实现搬到了 scripts/firmware/tools.py（与 BSP 解耦、不再调 build_and_flash.bat）。
这里保留 `build_and_flash()` 这个老接口，ramdump 的 dump 桶还在用它。

Usage:
    from builder import build_and_flash
    build_and_flash()
"""

# __pycache__ 统一写到仓库 out/pycache：仓库根由本文件位置直接推出（parents[3]），不做搜索
import sys as _sys
from pathlib import Path as _Path

_sys.pycache_prefix = str(_Path(__file__).resolve().parents[3] / "out" / "pycache")

import sys as _s  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_SCRIPTS = _Path(__file__).resolve().parents[2]  # scripts/
if str(_SCRIPTS) not in _s.path:
    _s.path.insert(0, str(_SCRIPTS))

from rtros.firmware import pipeline as _pipeline  # noqa: E402


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
    return _pipeline.build_and_flash()


if __name__ == "__main__":
    ok = build_and_flash(new_console=("--new-console" in _s.argv))
    _s.exit(0 if ok else 1)
