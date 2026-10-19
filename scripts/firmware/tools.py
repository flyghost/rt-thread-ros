#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""编译（SCons）与烧录（pyocd）的实现。

给两个入口共用：
    scripts/firmware/build.py   —— 人/AI 的 CLI
    scripts/guard/guard.py —— 沙箱外守卫（同样调这里的函数）
所以这里只做"干活"，不解析命令行参数。
"""

import os
import shutil
import subprocess
import sys

from firmware.config import (
    ARTIFACT_DIR, BSP_DIR, BUILD_DIR, ENTRY_DIR, ENTRY_KIND, ENV_ROOT, OUT_BIN_DIR, PYOCD_FLASH_OPTS,
    PYOCD_PACK, PYOCD_PKG_DIR, PYOCD_PY, PYOCD_TARGET, REPO_ROOT, RT_BUILD_DIR, RTT_EXEC_PATH,
    SCONS_JOBS, TARGET_BIN, TARGET_ELF, TARGET_MAP, VENV_PY,
)


def _scons_env() -> dict:
    env = dict(os.environ)
    env["ENV_ROOT"] = str(ENV_ROOT)
    env["RTT_CC"] = "gcc"
    env["RTT_EXEC_PATH"] = str(RTT_EXEC_PATH)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # 中间文件统一放 out/build/<board>/（SCons 从 BSP 目录出发的相对路径）
    env["RT_BUILD_DIR"] = RT_BUILD_DIR
    # arm-none-eabi-gcc 放进 PATH 前置，SCons 的 toolchain 探测依赖它
    env["PATH"] = str(RTT_EXEC_PATH) + os.pathsep + env.get("PATH", "")
    return env


def _pyocd_env() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PYOCD_PKG_DIR)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run(argv, cwd, env) -> int:
    print("  $ " + " ".join(str(a) for a in argv), flush=True)
    try:
        return subprocess.run([str(a) for a in argv], cwd=str(cwd), env=env).returncode
    except FileNotFoundError as exc:
        print(f"  [ERROR] 找不到可执行文件：{exc}")
        return 127


# ---- 编译 --------------------------------------------------------------

def build(jobs: int | None = None) -> int:
    jobs = jobs or SCONS_JOBS
    if not VENV_PY.exists():
        print(f"[build] 找不到装了 SCons 的解释器：{VENV_PY}")
        return 1
    print(f"[build] SCons -j{jobs}  ({ENTRY_KIND}: {ENTRY_DIR})")
    return _run([VENV_PY, "-m", "SCons", f"-j{jobs}"], ENTRY_DIR, _scons_env())


def clean() -> int:
    print(f"[clean] SCons -c  ({ENTRY_KIND}: {ENTRY_DIR})")
    rc = _run([VENV_PY, "-m", "SCons", "-c"], ENTRY_DIR, _scons_env())
    # SCons -c 只删它这次认知的目标；换过 variant_dir、或历史遗留的 build 目录
    # 不会自动消失，这里兜底清掉，避免“清了还有残留”。
    stale_dirs = [BUILD_DIR, ARTIFACT_DIR, ENTRY_DIR / "build"]
    if ENTRY_DIR != BSP_DIR:
        stale_dirs.append(BSP_DIR / "build")
    for stale in stale_dirs:
        if stale.exists():
            shutil.rmtree(stale, ignore_errors=True)
            print(f"[clean] 已删除 {stale}")
    return rc


def menuconfig() -> int:
    # 配置仍归属板级：板级 Kconfig 的 RTT_DIR 是相对板目录的常量。
    print(f"[menuconfig] SCons --menuconfig  (cwd={BSP_DIR})")
    return _run([VENV_PY, "-m", "SCons", "--menuconfig"], BSP_DIR, _scons_env())


# ---- 烧录 --------------------------------------------------------------

def pyocd_argv(*args) -> list:
    return [PYOCD_PY, "-m", "pyocd", *args]


def check_pyocd() -> str:
    """返回 pyocd 版本号；不可用时抛 RuntimeError。"""
    if not PYOCD_PKG_DIR.is_dir():
        raise RuntimeError(
            f"pyocd 未安装：{PYOCD_PKG_DIR}\n"
            f"         先运行：python {PYOCD_PKG_DIR.parent / 'install.py'}"
        )
    if not PYOCD_PACK.exists():
        raise RuntimeError(f"芯片 pack 缺失：{PYOCD_PACK}")
    proc = subprocess.run(
        [str(a) for a in pyocd_argv("--version")],
        env=_pyocd_env(), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"pyocd 跑不起来：{(proc.stderr or proc.stdout).strip()}")
    return (proc.stdout or proc.stderr).strip().splitlines()[0]


def flash(bin_path=None) -> int:
    target = TARGET_BIN if bin_path is None else bin_path
    try:
        version = check_pyocd()
    except RuntimeError as exc:
        print(f"[flash] {exc}")
        return 1
    if not target.exists():
        print(f"[flash] 固件不存在：{target}（先编译）")
        return 1
    print(f"[flash] pyocd {version} | {PYOCD_TARGET} | {target} ({target.stat().st_size:,} B)")
    rc = _run(
        pyocd_argv(
            "flash", "--target", PYOCD_TARGET, *PYOCD_FLASH_OPTS,
            "--pack", PYOCD_PACK, target,
        ),
        REPO_ROOT, _pyocd_env(),
    )
    if rc == 0:
        copy_artifacts()
    return rc


def copy_artifacts() -> None:
    """产物本来就落在 out/bin/<入口名>/（SConstruct 指定），这里只对旧布局做一次搬迁。"""
    OUT_BIN_DIR.mkdir(parents=True, exist_ok=True)
    for src in (TARGET_BIN, TARGET_ELF, TARGET_MAP):
        if src.exists() and src.parent != OUT_BIN_DIR:
            shutil.copy2(src, OUT_BIN_DIR / src.name)


# ---- 组合 --------------------------------------------------------------

def build_and_flash(jobs: int | None = None) -> bool:
    if build(jobs) != 0:
        print("[build+flash] 编译失败，未烧录")
        return False
    if not TARGET_BIN.exists():
        print(f"[build+flash] 编译完成但没产出 {TARGET_BIN}")
        return False
    return flash() == 0


def status() -> int:
    print(f"构建入口   : {ENTRY_DIR}  ({ENTRY_KIND})")
    print(f"板级 BSP   : {BSP_DIR}")
    print(f"中间文件   : {BUILD_DIR}  ({'存在' if BUILD_DIR.exists() else '未编译'})")
    print(f"产物目录   : {ARTIFACT_DIR}  ({'存在' if ARTIFACT_DIR.exists() else '未编译'})")
    print(f"固件       : {TARGET_BIN}  "
          f"({'%.0f KB' % (TARGET_BIN.stat().st_size / 1024) if TARGET_BIN.exists() else '缺失'})")
    if TARGET_BIN.exists():
        import datetime
        ts = datetime.datetime.fromtimestamp(TARGET_BIN.stat().st_mtime)
        print(f"编译时间   : {ts:%Y-%m-%d %H:%M:%S}")
    try:
        print(f"pyocd      : {check_pyocd()}")
    except RuntimeError as exc:
        print(f"pyocd      : 不可用 —— {exc}")
    print(f"芯片 pack  : {PYOCD_PACK.name}（{'存在' if PYOCD_PACK.exists() else '缺失'}）")
    print(f"目标芯片   : {PYOCD_TARGET}")
    ok = TARGET_BIN.exists() and PYOCD_PKG_DIR.is_dir() and PYOCD_PACK.exists()
    return 0 if ok else 1
