"""rtros —— 本仓的 Python 工具集（编译/烧录、守卫、串口服务器、ramdump 采集与解析）。

这个包按「可独立成仓」的方式组织：`src/rtros/` 是包本体，`scripts/pyproject.toml`
是唯一项目定义。包里**不允许**出现具体工程的路径、板名、芯片型号、串口号——
这些由使用者工程根的 `rtros.toml` 提供（见 `rtros.paths`）。
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
