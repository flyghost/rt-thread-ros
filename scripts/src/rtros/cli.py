"""`rtros` 命令行入口：子命令总表 + 公共开关。

P1 阶段只有 `version` 与 `paths` 两条自带命令；其余子命令在 P2 把旧模块搬进
`src/rtros/` 后逐个接管。迁移期间旧入口（`scripts/cli.py`、`scripts/firmware/build.py`
等）继续可用。
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from rtros import __version__
from rtros.paths import ENV_REPO, ProjectRootError, out_dir, project_root, tool_root

COMMANDS = {
    "version": "打印版本",
    "paths": "打印工具仓库根 / 工程根 / 产物与字节码目录（--json 机器可读）",
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
    """入口函数（console_scripts 与 `python -m rtros` 都走这里）。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version or args.command == "version":
        return _cmd_version()
    if args.command == "paths":
        return _cmd_paths(args.json)

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
