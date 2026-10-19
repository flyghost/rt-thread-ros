#!/usr/bin/env python3
"""仓库内 Python 质量的统一入口（检查 / 格式化 / 类型 / 测试）。

用法（仓库根目录或任意目录都可以）：
    python scripts/quality.py doctor        # 看工具装没装、版本对不对
    python scripts/quality.py check         # ruff check（只看不改）
    python scripts/quality.py check --fix   # ruff check --fix
    python scripts/quality.py format        # ruff format（真改文件）
    python scripts/quality.py format-check  # ruff format --check（只看不改）
    python scripts/quality.py types         # mypy（覆盖 pyproject 里 files=）
    python scripts/quality.py tests         # pytest
    python scripts/quality.py all           # check + format-check + types + tests

工具来源只有一个：`tools/pyquality/pkg`（gitignore），用 `python tools/pyquality/install.py` 安装。
所有命令都 `cwd=scripts/` 运行，让 ruff/mypy/pytest 自动读到 `scripts/pyproject.toml`。

退出码：0 全过；1 有失败；2 工具没装（先跑 install.py）。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PKG = REPO / "tools" / "pyquality" / "pkg"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PKG)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _tool(name: str) -> list[str]:
    """返回调用某个工具的 argv 前缀（python -m <name>）。"""
    return [sys.executable, "-m", name]


def _have(name: str) -> bool:
    try:
        out = subprocess.run(
            [*_tool(name), "--version"],
            env=_env(),
            capture_output=True,
            text=True,
            timeout=120,
            cwd=HERE,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return out.returncode == 0


def _run(label: str, argv: list[str], quiet: bool = False) -> int:
    started = time.time()
    if not quiet:
        print(f"$ {' '.join(argv)}")
    rc = subprocess.run(argv, env=_env(), cwd=HERE).returncode
    print(f"[{label}] 退出码 {rc}，耗时 {time.time() - started:.1f}s")
    return rc


def doctor() -> int:
    print(f"解释器 : {sys.executable}")
    print(f"工具目录: {PKG}（{'存在' if PKG.is_dir() else '缺失'}）")
    ok = True
    for name in ("ruff", "mypy", "pytest"):
        argv = [*_tool(name), "--version"]
        try:
            out = subprocess.run(argv, env=_env(), capture_output=True, text=True, timeout=120, cwd=HERE)
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"{name:<7}: 调用失败 {exc}")
            ok = False
            continue
        line = (out.stdout or out.stderr or "").strip().splitlines()
        if out.returncode == 0:
            print(f"{name:<7}: {line[0] if line else '(无输出)'}")
        else:
            print(f"{name:<7}: 未安装")
            ok = False
    if not ok:
        print(f"\n安装：{sys.executable} {REPO / 'tools' / 'pyquality' / 'install.py'}")
        return 2
    return 0


def require_tools() -> int:
    missing = [n for n in ("ruff", "mypy") if not _have(n)]
    if missing:
        print(f"缺少工具：{', '.join(missing)}")
        print(f"安装：{sys.executable} {REPO / 'tools' / 'pyquality' / 'install.py'}")
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="quality.py",
        description="Python 质量统一入口（ruff / mypy / pytest）",
    )
    sub = ap.add_subparsers(dest="cmd")

    p_check = sub.add_parser("check", help="ruff check")
    p_check.add_argument("--fix", action="store_true", help="自动修复可修的")

    sub.add_parser("format", help="ruff format（会改文件）")
    sub.add_parser("format-check", help="ruff format --check（不改文件）")
    sub.add_parser("types", help="mypy 类型检查")
    p_tests = sub.add_parser("tests", help="pytest")
    p_tests.add_argument("args", nargs=argparse.REMAINDER, help="透传给 pytest 的参数")
    sub.add_parser("doctor", help="检查工具是否安装")
    sub.add_parser("all", help="全套：check + format-check + types + tests")

    ns = ap.parse_args(argv)
    cmd = ns.cmd or "all"

    if cmd == "doctor":
        return doctor()

    if cmd != "all":
        rc = require_tools()
        if rc != 0:
            return rc

    if cmd == "check":
        argv_check = [*_tool("ruff"), "check", "."]
        if getattr(ns, "fix", False):
            argv_check.append("--fix")
        return _run("ruff check", argv_check)

    if cmd == "format":
        return _run("ruff format", [*_tool("ruff"), "format", "."])

    if cmd == "format-check":
        return _run("ruff format --check", [*_tool("ruff"), "format", "--check", "."])

    if cmd == "types":
        return _run("mypy", [*_tool("mypy")])

    if cmd == "tests":
        extra = [a for a in getattr(ns, "args", []) if a != "--"]
        return _run("pytest", [*_tool("pytest"), *extra])

    # all
    rc = require_tools()
    if rc != 0:
        return rc
    results: list[tuple[str, int]] = []
    results.append(("ruff check", _run("ruff check", [*_tool("ruff"), "check", "."])))
    results.append(
        ("ruff format --check", _run("ruff format --check", [*_tool("ruff"), "format", "--check", "."]))
    )
    results.append(("mypy", _run("mypy", [*_tool("mypy")])))
    results.append(("pytest", _run("pytest", [*_tool("pytest")])))

    print("\n== 汇总 ==")
    for label, code in results:
        print(f"  {label:<22} {'PASS' if code == 0 else f'FAIL({code})'}")
    return 0 if all(code == 0 for _, code in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
