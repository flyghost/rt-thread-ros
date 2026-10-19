#!/usr/bin/env python3
"""固件构建/烧录的路径与工具链配置（唯一事实来源）。

其他脚本一律从这里取常量，不要再各自写一份路径。
"""

import os
import sys
from pathlib import Path

# ---- 仓库布局 ----------------------------------------------------------
SCRIPTS_DIR = Path(__file__).resolve().parents[1]  # scripts/
REPO_ROOT = SCRIPTS_DIR.parent  # 仓库根
TOOLS_DIR = REPO_ROOT / "tools"
BSP_DIR = REPO_ROOT / "bsp" / "stm32" / "stm32f407-atk-explorer"
PROJECTS_DIR = REPO_ROOT / "projects"

# ---- 构建入口：项目优先，缺省回落到板级 ---------------------------------
# PROJECT 环境变量：'base' 之类 = projects/<名字>； 空 / 'none' / 'board' = 直接编译板级 BSP。
# 目前只在 projects/base 上验证（多项目并行构建留给后续批次）。
PROJECT_NAME = os.environ.get("PROJECT", "base").strip()
PROJECT_DIR = PROJECTS_DIR / PROJECT_NAME if PROJECT_NAME else None
if PROJECT_DIR is not None and (PROJECT_DIR / "SConstruct").is_file():
    ENTRY_DIR, ENTRY_KIND = PROJECT_DIR, "project"
else:
    ENTRY_DIR, ENTRY_KIND = BSP_DIR, "board"

# ---- RT-Thread 工具链（SCons + arm-none-eabi-gcc）----------------------
ENV_ROOT = Path(os.environ.get("ENV_ROOT", r"E:\software\EnvEdition\rt-thread-env\env-windows"))
RTT_EXEC_PATH = Path(
    os.environ.get("RTT_EXEC_PATH", ENV_ROOT / "tools" / "gnu_gcc" / "arm_gcc" / "mingw" / "bin")
)
VENV_DIR = Path(os.environ.get("VENV", ENV_ROOT / ".venv"))
VENV_PY = VENV_DIR / "Scripts" / "python.exe"  # 装了 SCons 的解释器
if not VENV_PY.exists():  # 非 Windows 或自定义环境
    VENV_PY = VENV_DIR / "bin" / "python"

SCONS_JOBS = int(os.environ.get("SCONS_JOBS", "20"))

# ---- pyocd（唯一来源：tools/pyocd，见 tools/pyocd/README.md）-----------
PYOCD_DIR = TOOLS_DIR / "pyocd"
PYOCD_PKG_DIR = PYOCD_DIR / "pkg"  # pip 装出来的 pyocd（gitignore）
PYOCD_PACK = PYOCD_DIR / "packs" / "Keil.STM32F4xx_DFP.2.14.0-small.pack"
PYOCD_TARGET = os.environ.get("PYOCD_TARGET", "STM32F407VE")
PYOCD_FLASH_OPTS = os.environ.get("PYOCD_FLASH_OPTS", "--erase=auto --frequency=1000000").split()
# 跑 pyocd 的解释器：pkg/ 里的 cffi、hidapi 是 CPython 3.13 的二进制 wheel，
# 必须用同一 ABI 的解释器；需要别的环境时用 PYOOCD_PY 覆盖。
PYOCD_PY = Path(os.environ.get("PYOCD_PY", sys.executable))

# ---- 产物 --------------------------------------------------------------
# 产物统一在 out/bin/<入口目录名>/（elf/map/bin），构建入口目录只留源码。
ARTIFACT_DIR = REPO_ROOT / "out" / "bin" / ENTRY_DIR.name
TARGET_BIN = ARTIFACT_DIR / "rtthread.bin"
TARGET_ELF = ARTIFACT_DIR / "rt-thread.elf"
TARGET_MAP = ARTIFACT_DIR / "rt-thread.map"
OUT_BIN_DIR = ARTIFACT_DIR

# ---- 中间文件（.o/.d）目录 ---------------------------------------------
# 统一收到仓内 out/build/<入口目录名>/（项目=项目名，板级=板名），不再散落源码树。
# SCons 的 variant_dir 只能写「相对顶层 SConstruct 目录」的路径，所以这里换算成
# 从入口目录出发的相对路径，通过 RT_BUILD_DIR 传给 SConstruct/building.py。
# 不设该变量时构建系统仍退回上游默认的 build/。
BUILD_DIR = REPO_ROOT / "out" / "build" / ENTRY_DIR.name
RT_BUILD_DIR = os.path.relpath(BUILD_DIR, ENTRY_DIR).replace("\\", "/")
