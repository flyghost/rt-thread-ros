"""脚本层运行时适配层：路径 / 子进程 / 文件 / 输出 / 错误。

为什么要这一层：`scripts/` 里原先各模块直接 `subprocess.run(...)`、`os.path.join(...)`、
`print(...)`、`sys.exit(1)`，结果是
- 同样的错误处理写 15 遍，退出码、提示格式各不相同；
- 输出无法分级（结果和诊断混在 stdout）；
- 想换成别的实现（比如把子进程换成库调用）要改遍全仓。

因此约定：**业务模块只依赖本层，不直接碰 `subprocess` / `os.path` / `print` / `sys.exit`。**
本层是唯一允许接触这些的地方（见 `scripts/AGENTS.md`）。
"""

from __future__ import annotations

from runtime.errors import CommandFailed, RtrosError, ToolMissingError, UserError

__all__ = [
    "CommandFailed",
    "RtrosError",
    "ToolMissingError",
    "UserError",
]
