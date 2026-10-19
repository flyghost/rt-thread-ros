"""跑外部工具：打印命令行、转发退出码。

只做一件事：把「要跑什么」和「怎么跑」分开——调用方给 argv/cwd/env，
这里负责回显、调用、把退出码翻成整数返回（不抛、不重试）。
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from rtros.runtime import proc
from rtros.runtime.errors import ToolMissingError


def run(argv: Sequence[str | Path], cwd: str | Path, env: dict[str, str]) -> int:
    """回显并执行；命令不存在时返回 127（与 shell 习惯一致）。"""
    print("  $ " + " ".join(str(a) for a in argv), flush=True)
    try:
        return proc.run([str(a) for a in argv], cwd=cwd, env=env, capture=False).returncode
    except ToolMissingError as exc:
        print(f"  [ERROR] {exc.message}")
        return 127
