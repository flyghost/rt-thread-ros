"""
Paths for the STM32F407 ATK Explorer BSP.

真正的常量住在 scripts/src/rtros/firmware/config.py（构建与烧录的唯一事实来源），
这里只做转发，免得 ramdump 的各个脚本各自写一份路径。
"""

from pathlib import Path

from rtros.firmware import config as _fc

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = _fc.REPO_ROOT

BSP_DIR = _fc.BSP_DIR

# ---- 工具链 ----
ENV_ROOT = _fc.ENV_ROOT
RTT_EXEC_PATH = _fc.RTT_EXEC_PATH
VENV_DIR = _fc.VENV_DIR

# ---- pyocd（唯一来源：tools/pyocd）----
PYOCD_DIR = _fc.PYOCD_DIR
PYOCD_PKG_DIR = _fc.PYOCD_PKG_DIR
PYOCD_PACK = _fc.PYOCD_PACK
PYOCD_TARGET = _fc.PYOCD_TARGET
PYOCD_FLASH_OPTS = _fc.PYOCD_FLASH_OPTS

# ---- 构建产物 ----
SCONS_JOBS = _fc.SCONS_JOBS
TARGET_BIN = _fc.TARGET_BIN
TARGET_ELF = _fc.TARGET_ELF
TARGET_MAP = _fc.TARGET_MAP
OUT_BIN_DIR = _fc.OUT_BIN_DIR
OUT_DUMP_DIR = PROJECT_ROOT / "out" / "dump"
