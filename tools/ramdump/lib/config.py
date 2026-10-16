"""
Paths and toolchain configuration for STM32F407 ATK Explorer.

All paths in one place — import from any script that needs them.
"""

import os
from pathlib import Path

SCRIPT_DIR   = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent.parent  # lib/ → ramdump/ → tools/ → 仓库根
BSP_DIR      = PROJECT_ROOT / "bsp" / "stm32" / "stm32f407-atk-explorer"

# ---- Toolchain (from build_and_flash.bat defaults) ----
ENV_ROOT      = Path(os.environ.get("ENV_ROOT", r"E:\software\EnvEdition\rt-thread-env\env-windows"))
RTT_EXEC_PATH = Path(os.environ.get("RTT_EXEC_PATH", ENV_ROOT / "tools" / "gnu_gcc" / "arm_gcc" / "mingw" / "bin"))
VENV_DIR      = Path(os.environ.get("VENV", ENV_ROOT / ".venv"))

# ---- PyOCD ----
PYOCD_DIR    = PROJECT_ROOT / "bsp" / "PyOCD" / "0.1.3"
PYOCD_TARGET = os.environ.get("PYOCD_TARGET", "STM32F407VE")
PYOCD_FLASH_OPTS = os.environ.get("PYOCD_FLASH_OPTS", "--erase=auto --frequency=1000000").split()

# ---- Build outputs ----
SCONS_JOBS = int(os.environ.get("SCONS_JOBS", "20"))
TARGET_BIN = BSP_DIR / "rtthread.bin"
TARGET_ELF = BSP_DIR / "rt-thread.elf"
TARGET_MAP = BSP_DIR / "rt-thread.map"
OUT_BIN_DIR  = PROJECT_ROOT / "out" / "bin"
OUT_DUMP_DIR = PROJECT_ROOT / "out" / "dump"
