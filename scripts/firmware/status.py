"""`status` 命令：把当前构建入口、产物、工具状态打出来。

只读不写，用于「为什么编译/烧录不动了」的第一轮排查。
"""

from __future__ import annotations

import datetime

from firmware import pyocd
from firmware.config import (
    ARTIFACT_DIR,
    BSP_DIR,
    BUILD_DIR,
    ENTRY_DIR,
    ENTRY_KIND,
    PYOCD_PACK,
    PYOCD_PKG_DIR,
    PYOCD_TARGET,
    TARGET_BIN,
)


def report() -> int:
    """打印环境摘要；缺固件或缺 pyocd 时返回 1。"""
    print(f"构建入口   : {ENTRY_DIR}  ({ENTRY_KIND})")
    print(f"板级 BSP   : {BSP_DIR}")
    print(f"中间文件   : {BUILD_DIR}  ({'存在' if BUILD_DIR.exists() else '未编译'})")
    print(f"产物目录   : {ARTIFACT_DIR}  ({'存在' if ARTIFACT_DIR.exists() else '未编译'})")
    if TARGET_BIN.exists():
        size_kb = TARGET_BIN.stat().st_size / 1024
        print(f"固件       : {TARGET_BIN}  ({size_kb:.0f} KB)")
        ts = datetime.datetime.fromtimestamp(TARGET_BIN.stat().st_mtime)
        print(f"编译时间   : {ts:%Y-%m-%d %H:%M:%S}")
    else:
        print(f"固件       : {TARGET_BIN}  (缺失)")
    try:
        print(f"pyocd      : {pyocd.check()}")
    except pyocd.PyocdUnavailable as exc:
        print(f"pyocd      : 不可用 —— {exc}")
    print(f"芯片 pack  : {PYOCD_PACK.name}（{'存在' if PYOCD_PACK.exists() else '缺失'}）")
    print(f"目标芯片   : {PYOCD_TARGET}")
    ok = TARGET_BIN.exists() and PYOCD_PKG_DIR.is_dir() and PYOCD_PACK.exists()
    return 0 if ok else 1
