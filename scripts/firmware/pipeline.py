"""组合动作：编译 + 烧录。

放在单独模块里，是因为它跨越两个工具（SCons 与 pyocd），
而 `scons.py` / `pyocd.py` 都只知道自己那一段。
"""

from __future__ import annotations

from firmware import pyocd, scons
from firmware.config import TARGET_BIN


def build_and_flash(jobs: int | None = None) -> bool:
    """先编译再烧录；任何一步失败都返回 False（并说明卡在哪）。"""
    if scons.build(jobs) != 0:
        print("[build+flash] 编译失败，未烧录")
        return False
    if not TARGET_BIN.exists():
        print(f"[build+flash] 编译完成但没产出 {TARGET_BIN}")
        return False
    return pyocd.flash() == 0
