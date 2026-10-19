#!/usr/bin/env python3
"""安装 pyocd 到 scripts/tools/pyocd/pkg（仓库里唯一的 pyocd 来源）。

用法（在仓库根目录）：
    python scripts/tools/pyocd/install.py              # 安装固定版本
    python scripts/tools/pyocd/install.py --force      # 先删 pkg/ 再装
    python scripts/tools/pyocd/install.py --check      # 只检查装没装、版本对不对
    python scripts/tools/pyocd/install.py --version 0.45.1

为什么不用 `pip install pyocd` 直接装到系统 Python：
    1) 不污染系统环境，pkg/ 被 .gitignore 忽略，删掉即还原；
    2) 版本钉死，换机器可复现；
    3) 沙箱里必须走本脚本 —— 见下面 _patch_tempfile() 的说明。

注意：pyocd 不是"纯 Python 无依赖"，它要 18 个第三方包（pyusb、libusb-package、
intelhex、cmsis-pack-manager ...），全部装进 pkg/，所以调用时必须带
PYTHONPATH=scripts/tools/pyocd/pkg。
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import tempfile as _tempfile
import uuid
from pathlib import Path

PYOCD_VERSION = "0.45.1"
HERE = Path(__file__).resolve().parent
PKG_DIR = HERE / "pkg"
PACK_DIR = HERE / "packs"
PACK_STM32F4 = PACK_DIR / "Keil.STM32F4xx_DFP.2.14.0-small.pack"


def _patch_tempfile() -> None:
    """让 tempfile.mkdtemp 用 os.makedirs 建目录。

    本机 DSH 沙箱会给 mkdtemp 建出来的目录设置一个本进程不可写的 ACL（实测：
    建完立刻往里写文件报 PermissionError，Get-Acl 直接 UnauthorizedAccessException），
    而 pip 内部全程用 mkdtemp 做解包暂存，所以在沙箱里 `pip install` 必然失败：
        PermissionError: [Errno 13] Permission denied: '...\\pip-unpack-*\\*.whl'
    os.makedirs 建出来的目录可正常读写，因此把 mkdtemp 换掉即可。
    """

    def _mkdtemp(suffix: str = "", prefix: str = "tmp", dir=None) -> str:
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
    _tempfile.mkdtemp = _mkdtemp  # type: ignore[assignment]


def _env() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PKG_DIR)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def current_version() -> str | None:
    """返回 pkg/ 里 pyocd 的版本号；没装或跑不起来返回 None。"""
    if not (PKG_DIR / "pyocd").is_dir():
        return None
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pyocd", "--version"],
            env=_env(),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = (out.stdout or out.stderr or "").strip().splitlines()
    return text[0].strip() if out.returncode == 0 and text else None


def install(version: str, force: bool, quiet: bool = False) -> int:
    if force and PKG_DIR.exists():
        print(f"[pyocd] 删除旧目录 {PKG_DIR}")
        shutil.rmtree(PKG_DIR)
    PKG_DIR.mkdir(parents=True, exist_ok=True)

    _patch_tempfile()
    # pip 必须在同一进程里调用：子进程会重新 import tempfile，绕行就失效了。
    from pip._internal.cli.main import main as pip_main

    argv = [
        "install",
        "--no-cache-dir",
        "--no-warn-script-location",
        "--target",
        str(PKG_DIR),
        f"pyocd=={version}",
    ]
    if quiet:
        argv.append("--quiet")
    print(f"[pyocd] pip {' '.join(argv)}")
    rc = pip_main(argv)
    if rc != 0:
        print(f"[pyocd] pip 失败（退出码 {rc}）")
        return rc or 1
    return 0


def check() -> int:
    ver = current_version()
    if ver is None:
        print(f"[pyocd] 未安装：{PKG_DIR} 不可用")
        print(f"[pyocd] 安装：{sys.executable} {Path(__file__)}")
        return 1
    print(f"[pyocd] 已安装：{ver}（{PKG_DIR}）")
    print(f"[pyocd] 芯片定义：{PACK_STM32F4.name}（{'存在' if PACK_STM32F4.exists() else '缺失'}）")
    return 0 if ver.startswith(PYOCD_VERSION[:4]) else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="install.py", description="安装/检查 pyocd（唯一来源：scripts/tools/pyocd/pkg）"
    )
    ap.add_argument("--version", default=PYOCD_VERSION, help=f"pyocd 版本（默认 {PYOCD_VERSION}）")
    ap.add_argument("--force", action="store_true", help="先删除 pkg/ 再安装")
    ap.add_argument("--check", action="store_true", help="只检查，不安装")
    ap.add_argument("--quiet", action="store_true", help="pip 静默")
    a = ap.parse_args(argv)

    if a.check:
        return check()

    rc = install(a.version, a.force, a.quiet)
    if rc != 0:
        return rc
    return check()


if __name__ == "__main__":
    sys.exit(main())
