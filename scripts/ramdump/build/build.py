#!/usr/bin/env python3
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

# __pycache__ 统一写到仓库 out/pycache：仓库根由本文件位置直接推出（parents[3]），不做搜索
import sys as _sys
from pathlib import Path as _Path

_sys.pycache_prefix = str(_Path(__file__).resolve().parents[3] / "out" / "pycache")

import argparse  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

_SCRIPTS = Path(__file__).resolve().parents[2]  # scripts/
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import os as _os  # noqa: E402

sys.path.insert(
    0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), *([".."] * 2), "src")
)  # rtros 包（P2）：唯一的包导入根
from rtros.firmware import pipeline, pyocd, scons  # noqa: E402


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
        return scons.clean()
    if a.menuconfig:
        return scons.menuconfig()
    if a.flash_only:
        return pyocd.flash()
    if a.flash:
        return 0 if pipeline.build_and_flash() else 1
    return scons.build()


if __name__ == "__main__":
    sys.exit(main())
