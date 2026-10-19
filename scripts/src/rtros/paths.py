"""路径解析：区分「工具仓库根」与「使用者工程根」，是整个工具集唯一的路径来源。

两类根必须分清，否则包无法独立成仓：

- **工具仓库根**（`tool_root()`）：这个包自己所在仓库的根，由 `__file__` 直接推出，
  用来找包里自带的数据文件（`tasks.toml` 等）。
- **使用者工程根**（`project_root()`）：被操作的固件工程根，由环境变量
  `RTROS_REPO` 或向上查找 `.git` / `.rtros-root` 决定；`out/` 产物都落在它下面。

除这两个函数，其它模块不应自己推算路径。
"""

from __future__ import annotations

import os
from pathlib import Path

ENV_REPO = "RTROS_REPO"
"""指定使用者工程根的环境变量名（优先级最高）。"""

MARKER = ".rtros-root"
"""工程根的显式标记文件；与 `.git` 等价，给“工程不在 git 下”的场景用。"""


class ProjectRootError(RuntimeError):
    """找不到或无法使用使用者工程根。"""


def tool_root() -> Path:
    """工具仓库根（`src/rtros/paths.py` → 上溯两级）。"""
    return Path(__file__).resolve().parents[2]


def project_root(start: Path | None = None) -> Path:
    """使用者工程根。

    优先级：`RTROS_REPO` 环境变量 → 从 `start`（默认当前目录）向上找 `.git` 或
    `.rtros-root`。都不满足就抛 `ProjectRootError`，不做任何猜测。
    """
    env = os.environ.get(ENV_REPO, "").strip()
    if env:
        root = Path(env).expanduser().resolve()
        if not root.is_dir():
            raise ProjectRootError(f"{ENV_REPO} 指向的目录不存在：{root}")
        return root

    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists() or (candidate / MARKER).exists():
            return candidate
    raise ProjectRootError(
        f"找不到工程根（向上查到 {current}）：请设置环境变量 {ENV_REPO}，或在工程根放一个 {MARKER} 标记文件"
    )


def out_dir(name: str, *, root: Path | None = None) -> Path:
    """工程根下的 `out/<name>`（用于 build / bin / pycache / log / guard 等）。"""
    return (root or project_root()) / "out" / name


def pycache_prefix(root: Path | None = None) -> Path:
    """字节码统一落点：`<工程根>/out/pycache`。

    找不到工程根时退回工具仓库的 `out/pycache`——`rtros --version` 这类
    不需要工程的命令因此也能在任何目录运行。
    """
    try:
        return out_dir("pycache", root=root)
    except ProjectRootError:
        return tool_root() / "out" / "pycache"
