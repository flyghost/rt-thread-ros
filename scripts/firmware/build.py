#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""固件构建/烧录的统一入口（唯一的 CLI，脚本与 bat 都调它）。

    python scripts\\firmware\\build.py build          # 只编译（默认 projects/base）
    python scripts\\firmware\\build.py flash          # 只烧录现有 rtthread.bin
    python scripts\\firmware\\build.py build-flash    # 编译 + 烧录
    python scripts\\firmware\\build.py clean          # 清理产物
    python scripts\\firmware\\build.py menuconfig     # 交互式配置（始终在板目录）
    python scripts\\firmware\\build.py status         # 固件/pyocd/pack 状态

选项：
    -j N              并行编译任务数（默认 20）
    --bin PATH        烧录用别的 bin（默认构建入口目录的 rtthread.bin）
    --project NAME    构建 projects/<NAME>（默认取环境变量 PROJECT，未设则 base）
    --board           直接编译板级 BSP（等价 PROJECT=none）

退出码：0 成功，1 失败，2 用法错误。
"""

# __pycache__ 统一写到仓库的 out/pycache（必须在本地 import 之前设置）
import os as _os
import sys as _sys

_d = _os.path.abspath(__file__)
while _d != _os.path.dirname(_d) and not _os.path.exists(_os.path.join(_d, ".git")):
    _d = _os.path.dirname(_d)
_sys.pycache_prefix = _os.path.join(_d, "out", "pycache")

import argparse                                          # noqa: E402
import sys                                               # noqa: E402
from pathlib import Path                                 # noqa: E402

_SCRIPTS = Path(__file__).resolve().parents[1]           # scripts/
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

COMMANDS = ("build", "flash", "build-flash", "clean", "menuconfig", "status")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="build.py",
        description="STM32F407 固件构建/烧录统一入口（默认项目 projects/base）",
        epilog="命令：" + " | ".join(COMMANDS),
    )
    ap.add_argument("command", nargs="?", default="build", choices=COMMANDS,
                    help="要做的事（默认 build）")
    ap.add_argument("-j", "--jobs", type=int, default=None, help="并行编译任务数")
    ap.add_argument("--bin", default=None, help="烧录用别的 bin 文件")
    ap.add_argument("--project", default=None, metavar="NAME",
                    help="构建 projects/<NAME>（默认取环境变量 PROJECT，未设则 base）")
    ap.add_argument("--board", action="store_true",
                    help="直接编译板级 BSP（等价 PROJECT=none）")
    a = ap.parse_args(argv)

    # config 在 import 时读取 PROJECT，所以必须先定好环境再导入 tools
    if a.board:
        _os.environ["PROJECT"] = "none"
    elif a.project:
        _os.environ["PROJECT"] = a.project

    from firmware import tools                            # noqa: E402

    if a.command == "build":
        return tools.build(a.jobs)
    if a.command == "clean":
        return tools.clean()
    if a.command == "menuconfig":
        return tools.menuconfig()
    if a.command == "status":
        return tools.status()
    if a.command == "flash":
        return tools.flash(Path(a.bin) if a.bin else None)
    if a.command == "build-flash":
        ok = tools.build_and_flash(a.jobs)
        return 0 if ok else 1
    ap.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
