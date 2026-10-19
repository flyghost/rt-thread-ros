"""SCons 相关动作：编译、清理、menuconfig。

SCons 必须**在入口目录里**运行（RT-Thread 的 `building.py` 有 6 处按 cwd 解析的路径），
所以这里所有动作都固定传 `cwd=ENTRY_DIR` 或板目录，不提供「在别处编译」的选项。
"""

from __future__ import annotations

import os
import shutil

from rtros.firmware.config import (
    ARTIFACT_DIR,
    BSP_DIR,
    BUILD_DIR,
    ENTRY_DIR,
    ENTRY_KIND,
    ENV_ROOT,
    RT_BUILD_DIR,
    RTT_EXEC_PATH,
    SCONS_JOBS,
    VENV_PY,
)
from rtros.firmware.exec import run


def scons_env() -> dict[str, str]:
    """SCons 需要的环境：工具链变量 + arm-gcc 进 PATH + 中间文件目录。"""
    env = dict(os.environ)
    env["ENV_ROOT"] = str(ENV_ROOT)
    env["RTT_CC"] = "gcc"
    env["RTT_EXEC_PATH"] = str(RTT_EXEC_PATH)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["RT_BUILD_DIR"] = RT_BUILD_DIR
    env["PATH"] = str(RTT_EXEC_PATH) + os.pathsep + env.get("PATH", "")
    return env


def build(jobs: int | None = None) -> int:
    """在入口目录里跑 `scons -jN`。"""
    jobs = jobs or SCONS_JOBS
    if not VENV_PY.exists():
        print(f"[build] 找不到装了 SCons 的解释器：{VENV_PY}")
        return 1
    print(f"[build] SCons -j{jobs}  ({ENTRY_KIND}: {ENTRY_DIR})")
    return run([VENV_PY, "-m", "SCons", f"-j{jobs}"], ENTRY_DIR, scons_env())


def clean() -> int:
    """`scons -c` 之后再兜底删除变体目录（换过 variant_dir 时 SCons 自己不认知）。"""
    print(f"[clean] SCons -c  ({ENTRY_KIND}: {ENTRY_DIR})")
    rc = run([VENV_PY, "-m", "SCons", "-c"], ENTRY_DIR, scons_env())
    stale_dirs = [BUILD_DIR, ARTIFACT_DIR, ENTRY_DIR / "build"]
    if ENTRY_DIR != BSP_DIR:
        stale_dirs.append(BSP_DIR / "build")
    for stale in stale_dirs:
        if stale.exists():
            shutil.rmtree(stale, ignore_errors=True)
            print(f"[clean] 已删除 {stale}")
    return rc


def menuconfig() -> int:
    """配置归属板级：板级 Kconfig 的 `RTT_DIR` 是相对板目录的常量。"""
    print(f"[menuconfig] SCons --menuconfig  (cwd={BSP_DIR})")
    return run([VENV_PY, "-m", "SCons", "--menuconfig"], BSP_DIR, scons_env())
