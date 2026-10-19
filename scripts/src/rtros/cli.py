"""`rtros` 命令行入口：子命令总表 + 公共开关。

自带命令：`version`、`paths`；转发命令：`build`（固件编译/烧录）、`guard`（沙箱外执行器）。
转发只做 import + 调对方 `main()`，不复制业务逻辑。
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from typing import Any

from rtros import __version__
from rtros.paths import ENV_REPO, ProjectRootError, out_dir, project_root, tool_root

# 转发目标：子命令 -> 模块名（模块内固定有 `main(argv)`，`analyze` 例外）
DELEGATES = {
    "build": "rtros.firmware.build",
    "guard": "rtros.guard.cli",
    "hub": "rtros.serial_hub.serial_hub",
    "dump": "rtros.ramdump.dump.dump",
    "recv": "rtros.ramdump.dump.receive",
    "analyze": "rtros.ramdump.analyzer.ramdump_analyzer",
}

COMMANDS = {
    "version": "打印版本",
    "paths": "打印工具仓库根 / 工程根 / 产物与字节码目录（--json 机器可读）",
    "build": "固件编译/烧录（等价 `rtros build|flash|build-flash|clean|menuconfig|status`）",
    "guard": "沙箱外执行器（--status / --list / --request / --tasks）",
    "hub": "串口服务器（TCP 数据口 + 控制口 + telnet）",
    "dump": "完整采集流程：编译 → 烧录 → 触发 → YMODEM 接收",
    "recv": "只接收（设备已在跑）",
    "analyze": "离线解析 dump（参数与旧 analyzer 相同）",
}


def _paths_payload() -> dict[str, Any]:
    """收集 `paths` 命令要输出的信息；工程根缺失时用 null 表示而不是抛错。"""
    payload: dict[str, Any] = {"tool_root": str(tool_root()), "project_root": None, "env": ENV_REPO}
    try:
        root = project_root()
    except ProjectRootError as exc:
        payload["project_root_error"] = str(exc)
        return payload
    payload.update(
        {
            "project_root": str(root),
            "out_build": str(out_dir("build", root=root)),
            "out_bin": str(out_dir("bin", root=root)),
            "out_pycache": str(out_dir("pycache", root=root)),
        }
    )
    return payload


def _cmd_version() -> int:
    print(f"rtros {__version__}")
    return 0


def _cmd_paths(as_json: bool) -> int:
    payload = _paths_payload()
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload["project_root"] else 1
    for key, value in payload.items():
        print(f"{key:18} {value}")
    return 0 if payload["project_root"] else 1


def build_parser() -> argparse.ArgumentParser:
    """构造参数解析器（测试与文档共用同一份定义）。"""
    parser = argparse.ArgumentParser(
        prog="rtros",
        description="本仓 Python 工具集统一入口",
        epilog="子命令：" + " | ".join(COMMANDS),
    )
    parser.add_argument("-V", "--version", action="store_true", help="打印版本后退出")
    parser.add_argument("--json", action="store_true", help="机器可读输出（仅部分子命令支持）")
    parser.add_argument("command", nargs="?", choices=sorted(COMMANDS), help="要执行的子命令")
    return parser


def main(argv: list[str] | None = None) -> int:
    """入口函数（console_scripts、`python -m rtros`、`scripts/run_rtros.py` 都走这里）。"""
    args_in = list(sys.argv[1:] if argv is None else argv)

    # 子系统的入口仍是各自的 main()：这里只做转发，不复制业务逻辑
    if args_in and args_in[0] in DELEGATES:
        module_name = DELEGATES[args_in[0]]
        module = importlib.import_module(module_name)
        if args_in[0] == "analyze":
            # 唯一的例外：analyzer 的 main() 不接 argv，直接读 sys.argv
            saved = sys.argv
            sys.argv = ["rtros analyze", *args_in[1:]]
            try:
                return int(module.main() or 0)
            finally:
                sys.argv = saved
        return int(module.main(args_in[1:]))

    parser = build_parser()
    args = parser.parse_args(args_in)

    if args.version or args.command == "version":
        return _cmd_version()
    if args.command == "paths":
        return _cmd_paths(args.json)

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
