"""rtros 的安装器：把 `scripts/` 以 editable 方式装进当前解释器，得到 `rtros` 命令。

为什么需要它（而不是直接 `pip install -e scripts`）：

1. 受限环境里 `tempfile.mkdtemp()` 建出的目录本进程不可写，pip 的构建隔离会在
   创建临时目录后立刻失败；这里在 import pip 之前把 `mkdtemp` 换成 `os.makedirs`。
2. 统一加 `--no-build-isolation --no-deps`：本机已装 setuptools 与运行期依赖，
   不需要联网拉构建依赖。

用法：
    python tools/pyenv/install.py            # 安装/刷新 editable
    python tools/pyenv/install.py --check    # 只看是否已装、版本多少
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
TARGET = REPO / "scripts"


def _patch_tempfile() -> None:
    """把 mkdtemp 换成「用 os.makedirs 建的目录」，绕开受限环境的 ACL 问题。"""

    def mkdtemp(suffix: str = "", prefix: str = "tmp", dir: str | None = None) -> str:
        base = Path(dir) if dir else Path(tempfile.gettempdir())
        path = base / f"{prefix}{uuid.uuid4().hex[:8]}{suffix}"
        path.mkdir(parents=True, exist_ok=False)
        return str(path)

    tempfile.mkdtemp = mkdtemp  # type: ignore[assignment]
    tempfile.TemporaryDirectory._mkdtemp = staticmethod(mkdtemp)  # type: ignore[attr-defined]


def _run(argv: list[str], *, quiet: bool = False) -> int:
    if not quiet:
        print("$ " + " ".join(argv), flush=True)
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.call(argv, env=env, cwd=str(REPO))


def installed_version() -> str | None:
    """已安装的 rtros 版本；没装返回 None。"""
    try:
        import rtros
    except ImportError:
        return None
    return rtros.__version__


def install(quiet: bool = False) -> int:
    """以 editable 方式安装 `scripts/`（重复执行等于刷新）。

    走**进程内** pip（`pip._internal.cli.main`）而不是子进程：受限环境里子进程
    的 stdio 管道会被拦（表现为 pip 卡死），而进程内调用只碰文件系统。
    """
    _patch_tempfile()
    from pip._internal.cli.main import main as pip_main

    argv = [
        "install",
        "--no-build-isolation",
        "--no-deps",
        "--no-warn-script-location",
        "-e",
        str(TARGET),
    ]
    if not quiet:
        print("$ pip " + " ".join(argv), flush=True)
    return int(pip_main(argv) or 0)


def main(argv: list[str] | None = None) -> int:
    """入口：默认执行安装，`--check` 只查询。"""
    parser = argparse.ArgumentParser(prog="pyenv-install.py", description="安装/检查 rtros（editable）")
    parser.add_argument("--check", action="store_true", help="只检查是否已装")
    parser.add_argument("--quiet", action="store_true", help="不打印执行中的命令")
    args = parser.parse_args(argv)

    version = installed_version()
    if args.check:
        if version is None:
            print("[pyenv] 未安装 rtros")
            return 1
        print(f"[pyenv] 已安装：rtros {version}")
        return 0

    code = install(quiet=args.quiet)
    if code != 0:
        print(f"[pyenv] 安装失败（pip 退出码 {code}）")
        return code
    version = installed_version()
    if version is None:
        print("[pyenv] 安装命令成功，但当前解释器仍 import 不到 rtros")
        return 1
    print(f"[pyenv] 安装完成：rtros {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
