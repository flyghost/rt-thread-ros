#!/usr/bin/env python3
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

# __pycache__ 统一写到仓库 out/pycache：仓库根由本文件位置直接推出（parents[2]），不做搜索
import sys as _sys
from pathlib import Path as _Path

_sys.pycache_prefix = str(_Path(__file__).resolve().parents[2] / "out" / "pycache")

import argparse  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

_SCRIPTS = Path(__file__).resolve().parents[1]  # scripts/
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

COMMANDS = ("build", "flash", "build-flash", "clean", "menuconfig", "status")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="build.py",
        description="STM32F407 固件构建/烧录统一入口（默认项目 projects/base）",
        epilog="命令：" + " | ".join(COMMANDS),
    )
    ap.add_argument("command", nargs="?", default="build", choices=COMMANDS, help="要做的事（默认 build）")
    ap.add_argument("-j", "--jobs", type=int, default=None, help="并行编译任务数")
    ap.add_argument("--bin", default=None, help="烧录用别的 bin 文件")
    ap.add_argument(
        "--project",
        default=None,
        metavar="NAME",
        help="构建 projects/<NAME>（默认取环境变量 PROJECT，未设则 base）",
    )
    ap.add_argument("--board", action="store_true", help="直接编译板级 BSP（等价 PROJECT=none）")
    a = ap.parse_args(argv)

    # config 在 import 时读取 PROJECT，所以必须先定好环境再导入业务模块
    if a.board:
        os.environ["PROJECT"] = "none"
    elif a.project:
        os.environ["PROJECT"] = a.project

    from firmware import pipeline, pyocd, scons, status

    if a.command == "build":
        return scons.build(a.jobs)
    if a.command == "clean":
        return scons.clean()
    if a.command == "menuconfig":
        return scons.menuconfig()
    if a.command == "status":
        return status.report()
    if a.command == "flash":
        return pyocd.flash(Path(a.bin) if a.bin else None)
    if a.command == "build-flash":
        return 0 if pipeline.build_and_flash(a.jobs) else 1
    ap.print_usage(sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
