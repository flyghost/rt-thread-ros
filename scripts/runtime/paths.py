"""路径事实：仓库根、仓内相对路径、目录创建。

为什么集中：`os.path.dirname(os.path.abspath(__file__))` 这类写法在全仓出现上百次，
层级一旦变化就全部错位；而且 `os.path` 的字符串拼接在 Windows 上容易混用分隔符。

这里只回答三个问题：
1. 仓库根在哪（`repo_root()`）：以本文件位置为锚点，不依赖 cwd、不读环境变量；
2. 某个路径相对仓库根怎么写（`rel()`）：日志与文档里统一用 POSIX 分隔符；
3. 目录不存在就建（`ensure_dir()`）。
"""

from __future__ import annotations

from pathlib import Path

# scripts/runtime/paths.py → parents[0]=runtime, [1]=scripts, [2]=仓库根
_REPO_ROOT = Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    """仓库根目录（绝对路径）。"""
    return _REPO_ROOT


def rel(path: str | Path, *, base: str | Path | None = None) -> str:
    """把路径写成相对仓库根的 POSIX 串；已在仓外时原样返回绝对路径。"""
    target = Path(path).resolve()
    root = Path(base).resolve() if base is not None else _REPO_ROOT
    try:
        return target.relative_to(root).as_posix()
    except ValueError:
        return target.as_posix()


def ensure_dir(path: str | Path) -> Path:
    """确保目录存在（含父目录），返回同一路径。"""
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


def display(path: str | Path) -> str:
    """给人看的路径：仓内显示相对路径，仓外显示绝对路径。"""
    return rel(path)
