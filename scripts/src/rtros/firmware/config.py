#!/usr/bin/env python3
"""固件构建/烧录的路径与工具链配置。

**本仓事实不在代码里**：板子在哪、工具链在哪、烧哪个芯片、默认串口——全部来自
工程根的 `rtros.toml`（见 `rtros.manifest`）。环境变量仍然可以覆盖。

其他模块一律从这里取常量，不要各自再写一份路径。
"""

from __future__ import annotations

import os
from pathlib import Path

from rtros import manifest
from rtros.paths import tool_root

# ---- 工程清单（唯一事实来源）-------------------------------------------
MANIFEST = manifest.cached()
SCRIPTS_DIR = tool_root()  # scripts/（包化后位置由 rtros.paths 统一给出，别再数父级层数）
REPO_ROOT = MANIFEST.root
TOOLS_DIR = REPO_ROOT / "tools"
BSP_DIR = MANIFEST.workspace.bsp_dir
PROJECTS_DIR = MANIFEST.workspace.projects_dir

# ---- 构建入口：项目优先，缺省回落到板级 ---------------------------------
# PROJECT 环境变量：'base' 之类 = projects/<名字>； 空 / 'none' / 'board' = 直接编译板级 BSP。
PROJECT_NAME = os.environ.get("PROJECT", MANIFEST.default_project).strip()
ENTRY_DIR, ENTRY_KIND = MANIFEST.entry_dir(PROJECT_NAME)

# ---- RT-Thread 工具链（SCons + arm-none-eabi-gcc）----------------------
ENV_ROOT = MANIFEST.build.toolchain_root
RTT_EXEC_PATH = MANIFEST.build.rtt_exec_path
VENV_DIR = MANIFEST.build.venv_dir
VENV_PY = MANIFEST.build.venv_python  # 装了 SCons 的解释器
SCONS_JOBS = int(os.environ.get("SCONS_JOBS", str(MANIFEST.build.scons_jobs)))

# ---- pyocd（唯一来源：tools/pyocd，见 tools/pyocd/README.md）-----------
PYOCD_DIR = TOOLS_DIR / "pyocd"
PYOCD_PKG_DIR = PYOCD_DIR / "pkg"  # pip 装出来的 pyocd（gitignore）
PYOCD_PACK = MANIFEST.flash.pack
PYOCD_TARGET = MANIFEST.flash.target
PYOCD_FLASH_OPTS = list(MANIFEST.flash.opts)
# 跑 pyocd 的解释器：pkg/ 里的 cffi、hidapi 是 CPython 3.13 的二进制 wheel，
# 必须用同一 ABI 的解释器；需要别的环境时用 PYOCD_PY 覆盖。
PYOCD_PY = Path(os.environ.get("PYOCD_PY", MANIFEST.flash.python))

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
