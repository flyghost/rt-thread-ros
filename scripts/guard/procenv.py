"""子进程环境与自检小工具：跟"怎么起子进程"有关，跟守卫状态机无关。

拆自 executor.py：一是 `child_env()`（钉 UTF-8、arm-gcc PATH、临时目录），
二是命令标签（日志里显示 `python -m SCons` 而不是解释器名），
三是"脚本/配置是否比进程新"的 mtime 判据。
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

from guard.config import ARM_GCC_BIN, CHILD_TMP, ENV_ROOT


def cmd_label(argv: list[str]) -> str:
    """给人看的命令标签：`python.exe -m SCons`、`pyocd flash`，别只写解释器名。"""
    exe = Path(argv[0]).name
    if "-m" in argv:
        i = argv.index("-m")
        if i + 1 < len(argv):
            return f"{exe} -m {argv[i + 1]}"
    if "pyocd" in exe.lower():
        return "pyocd " + (argv[1] if len(argv) > 1 else "")
    return exe


def child_env() -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if ENV_ROOT.is_dir():
        env["ENV_ROOT"] = str(ENV_ROOT)
        env["RTT_CC"] = "gcc"
        if ARM_GCC_BIN.is_dir():
            env["RTT_EXEC_PATH"] = str(ARM_GCC_BIN)
            env["PATH"] = str(ARM_GCC_BIN) + os.pathsep + env.get("PATH", "")
    # PyInstaller 打包的 pyocd.exe 启动时要先把自己解包到临时目录。**不要相信继承来的
    # TEMP/TMP**：实测某个窗口带着已失效的 per-session 临时路径，pyocd 直接报
    # "[18336] INTERNAL ERROR: cannot create temporary directory!" 并退 -1。
    # 这里钉到仓库内的 out/tmp —— 谁能写仓库，谁就能写它。
    try:
        CHILD_TMP.mkdir(parents=True, exist_ok=True)
        env["TEMP"] = env["TMP"] = env["TMPDIR"] = str(CHILD_TMP)
    except OSError:
        pass
    return env


def max_mtime(paths: tuple[Path, ...]) -> float:
    """给定文件里最新的 mtime；文件缺失就跳过（用于发现"进程还在跑老代码"）。"""
    newest = 0.0
    for path in paths:
        with contextlib.suppress(OSError):
            newest = max(newest, path.stat().st_mtime)
    return newest
