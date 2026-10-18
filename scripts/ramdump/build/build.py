#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建入口：编译 / 下载 / 清理 / menuconfig（BSP = stm32f407-atk-explorer）。

    python scripts/ramdump/build/build.py                 # 只编译
    python scripts/ramdump/build/build.py --flash         # 编译 + 下载
    python scripts/ramdump/build/build.py --flash-only    # 只下载（不编译）
    python scripts/ramdump/build/build.py --clean         # 清理产物
    python scripts/ramdump/build/build.py --menuconfig    # 进 menuconfig
    python scripts/ramdump/build/build.py --new-console   # 弹独立 cmd 窗口看编译输出

实现都在 lib/builder.py（scons 与 pyocd 的封装）与 BSP 自带的 build_and_flash.bat；
本文件只做参数解析与分发，不重复实现编译逻辑。

注意：build_and_flash.bat 失败分支里有 `pause`，所以失败时在交互终端里跑最直观。
"""
# __pycache__ 统一写到仓库的 out/pycache（sys.pycache_prefix 只影响设置之后的 import，
# 所以要在所有本地 import 之前，但又必须在 from __future__ 之后）。
import os as _os, sys as _sys
_d = _os.path.abspath(__file__)
while _d != _os.path.dirname(_d) and not _os.path.exists(_os.path.join(_d, '.git')):
    _d = _os.path.dirname(_d)
_sys.pycache_prefix = _os.path.join(_d, 'out', 'pycache')

import argparse
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # scripts/ramdump
sys.path.insert(0, _ROOT)

from lib import builder                                                # noqa: E402
from lib.config import BSP_DIR, PYOCD_DIR, PYOCD_TARGET, TARGET_BIN    # noqa: E402

BAT = BSP_DIR / "build_and_flash.bat"


def _flags(new_console):
    if new_console and sys.platform == "win32":
        return subprocess.CREATE_NEW_CONSOLE
    return 0


def run_bat(mode, new_console=False):
    if not BAT.exists():
        print("[ERROR] 找不到 %s" % BAT)
        return 1
    print("[BAT] %s %s" % (BAT.name, mode))
    return subprocess.run([str(BAT), mode], cwd=str(BSP_DIR), shell=True,
                          creationflags=_flags(new_console)).returncode


def do_flash(new_console=False):
    """直接调 pyocd 下载当前 rtthread.bin（不重新编译）。"""
    exe = PYOCD_DIR / "pyocd.exe"
    if not exe.exists():
        print("[ERROR] 找不到 pyocd：%s" % exe)
        return 1
    if not TARGET_BIN.exists():
        print("[ERROR] 还没有 %s，先编译一次" % TARGET_BIN)
        return 1
    print("[FLASH] %s -> %s（%d B）" % (PYOCD_TARGET, TARGET_BIN, TARGET_BIN.stat().st_size))
    return subprocess.run([str(exe), "flash", "--target", PYOCD_TARGET,
                           "--erase=auto", "--frequency=1000000", str(TARGET_BIN)],
                          cwd=str(exe.parent), creationflags=_flags(new_console)).returncode


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="build.py", description="编译 / 下载 / 清理 STM32F407 ATK Explorer 固件",
        epilog="不带参数 = 只编译；--flash = 编译后下载；--flash-only = 只下载")
    p.add_argument("--flash", action="store_true", help="编译成功后接着下载")
    p.add_argument("--flash-only", action="store_true", help="不编译，只下载现有的 rtthread.bin")
    p.add_argument("--clean", action="store_true", help="清理 build/ 与 rt-thread.elf / rtthread.bin / rt-thread.map")
    p.add_argument("--menuconfig", action="store_true", help="打开 menuconfig（交互式）")
    p.add_argument("--new-console", action="store_true", help="弹独立 cmd 窗口显示编译/下载输出")
    a = p.parse_args(argv)

    if a.clean:
        return run_bat("clean", a.new_console)
    if a.menuconfig:
        return run_bat("menuconfig", a.new_console)
    if a.flash_only:
        return do_flash(a.new_console)

    rc = run_bat("build", a.new_console)
    if rc != 0:
        print("[BUILD] 失败（退出码 %d）" % rc)
        return rc
    if not TARGET_BIN.exists():
        print("[BUILD] 没产出 %s" % TARGET_BIN)
        return 1
    print("[BUILD] OK：%s（%d B）" % (TARGET_BIN, TARGET_BIN.stat().st_size))

    if a.flash:
        return do_flash(a.new_console)
    return 0


if __name__ == "__main__":
    sys.exit(main())
