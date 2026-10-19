#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""兼容入口：老的 ramdump/build/build.py 参数形式。

实现已经统一到 scripts/firmware/build.py（不再经过 build_and_flash.bat）。
新代码请直接用：

    python scripts\\firmware\\build.py build|flash|build-flash|clean|menuconfig|status
    ai_services.bat                      # 人手动用，菜单转调上面那条

这里只为不破坏既有命令与文档：
    python scripts\\ramdump\\build\\build.py                 # 只编译
    python scripts\\ramdump\\build\\build.py --flash         # 编译 + 下载
    python scripts\\ramdump\\build\\build.py --flash-only    # 只下载
    python scripts\\ramdump\\build\\build.py --clean
    python scripts\\ramdump\\build\\build.py --menuconfig
"""

# __pycache__ 统一写到仓库的 out/pycache
import os as _os
import sys as _sys

_d = _os.path.abspath(__file__)
while _d != _os.path.dirname(_d) and not _os.path.exists(_os.path.join(_d, ".git")):
    _d = _os.path.dirname(_d)
_sys.pycache_prefix = _os.path.join(_d, "out", "pycache")

import argparse  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

_SCRIPTS = Path(__file__).resolve().parents[2]  # scripts/
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from firmware import tools  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="build.py", description="[兼容] 固件编译/下载 —— 实际实现见 scripts/firmware/build.py"
    )
    ap.add_argument("--flash", action="store_true", help="编译成功后接着下载")
    ap.add_argument("--flash-only", action="store_true", help="不编译，只下载现有 rtthread.bin")
    ap.add_argument("--clean", action="store_true", help="清理产物")
    ap.add_argument("--menuconfig", action="store_true", help="打开 menuconfig")
    ap.add_argument("--new-console", action="store_true", help="已废弃（不再经过 bat）")
    a = ap.parse_args(argv)

    if a.clean:
        return tools.clean()
    if a.menuconfig:
        return tools.menuconfig()
    if a.flash_only:
        return tools.flash()
    if a.flash:
        return 0 if tools.build_and_flash() else 1
    return tools.build()


if __name__ == "__main__":
    sys.exit(main())
