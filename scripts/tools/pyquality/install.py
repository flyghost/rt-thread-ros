#!/usr/bin/env python3
"""安装 ruff + mypy 到 scripts/tools/pyquality/pkg（仓库里唯一的 Python 质量工具来源）。

用法（在仓库根目录）：
    python scripts/tools/pyquality/install.py            # 安装固定版本
    python scripts/tools/pyquality/install.py --check    # 只检查
    python scripts/tools/pyquality/install.py --force    # 删掉 pkg/ 重装

为什么装到仓内目录而不是系统 Python：
    1) 不污染全局环境；pkg/ 被 .gitignore 忽略，删掉即还原；
    2) 版本钉死，换机器可复现；
    3) 本机沙箱必须走本脚本 —— pip 内部用 tempfile.mkdtemp 做解包暂存，
       而沙箱给 mkdtemp 建出的目录挂了本进程不可写的 ACL，导致
       `pip install` 必然报 PermissionError: ... pip-unpack-* ... whl。
       这里在调用 pip 前把 mkdtemp 换成 os.makedirs 实现（与 scripts/tools/pyocd/install.py 同一手法）。

安装完成后由 scripts/quality.py 调用（它会自动把 pkg/ 放进 PYTHONPATH）。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

RUFF_VERSION = "0.14.3"
MYPY_VERSION = "1.18.2"
PYTEST_VERSION = "8.4.2"
PRECOMMIT_VERSION = "4.3.0"

HERE = Path(__file__).resolve().parent
PKG_DIR = HERE / "pkg"
PACKAGES = (
    f"ruff=={RUFF_VERSION}",
    f"mypy=={MYPY_VERSION}",
    f"pytest=={PYTEST_VERSION}",
    f"pre-commit=={PRECOMMIT_VERSION}",
)


def _patch_tempfile() -> None:
    """把 tempfile.mkdtemp 换成 os.makedirs 实现（沙箱 ACL 规避，见模块 docstring）。"""

    def _mkdtemp(suffix: str = "", prefix: str = "tmp", dir: str | None = None) -> str:
        base = Path(dir) if dir else Path(tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        for _ in range(100):
            path = base / f"{prefix}{uuid.uuid4().hex[:8]}{suffix}"
            try:
                path.mkdir()
            except FileExistsError:
                continue
            return str(path)
        raise FileExistsError(f"cannot create temp dir under {base}")

    tempfile.mkdtemp = _mkdtemp  # type: ignore[assignment]


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PKG_DIR)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _first_line(argv: list[str]) -> str | None:
    try:
        out = subprocess.run(argv, env=_env(), capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError):
        return None
    text = (out.stdout or out.stderr or "").strip().splitlines()
    return text[0].strip() if out.returncode == 0 and text else None


def versions() -> dict[str, str | None]:
    """返回各工具版本；未安装或跑不起来为 None。"""
    if not PKG_DIR.is_dir():
        return {"ruff": None, "mypy": None, "pytest": None, "pre-commit": None}
    return {
        "ruff": _first_line([sys.executable, "-m", "ruff", "--version"]),
        "mypy": _first_line([sys.executable, "-m", "mypy", "--version"]),
        "pytest": _first_line([sys.executable, "-m", "pytest", "--version"]),
        "pre-commit": _first_line([sys.executable, "-m", "pre_commit", "--version"]),
    }


def install(force: bool, quiet: bool = False) -> int:
    if force and PKG_DIR.exists():
        print(f"[pyquality] 删除旧目录 {PKG_DIR}")
        shutil.rmtree(PKG_DIR)
    PKG_DIR.mkdir(parents=True, exist_ok=True)

    _patch_tempfile()
    # pip 必须在同一进程里调用：子进程会重新 import tempfile，绕行失效。
    from pip._internal.cli.main import main as pip_main

    argv = [
        "install",
        "--no-cache-dir",
        "--no-warn-script-location",
        "--target",
        str(PKG_DIR),
        *PACKAGES,
    ]
    if quiet:
        argv.append("--quiet")
    print(f"[pyquality] pip {' '.join(argv)}")
    rc = pip_main(argv)
    if rc != 0:
        print(f"[pyquality] pip 失败（退出码 {rc}）")
        return rc or 1
    return 0


def check() -> int:
    got = versions()
    ok = True
    for name, want in (
        ("ruff", RUFF_VERSION),
        ("mypy", MYPY_VERSION),
        ("pytest", PYTEST_VERSION),
        ("pre-commit", PRECOMMIT_VERSION),
    ):
        ver = got[name]
        if ver is None:
            print(f"[pyquality] {name}: 未安装")
            ok = False
        else:
            print(f"[pyquality] {name}: {ver}")
            if want not in ver:
                print(f"[pyquality] {name}: 期望 {want}，实际不同")
                ok = False
    if not ok:
        print(f"[pyquality] 安装：{sys.executable} {Path(__file__)}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="install.py", description="安装/检查 ruff 与 mypy（唯一来源：scripts/tools/pyquality/pkg）"
    )
    ap.add_argument("--force", action="store_true", help="先删除 pkg/ 再安装")
    ap.add_argument("--check", action="store_true", help="只检查，不安装")
    ap.add_argument("--quiet", action="store_true", help="pip 静默")
    args = ap.parse_args(argv)

    if args.check:
        return check()
    rc = install(args.force, args.quiet)
    if rc != 0:
        return rc
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
