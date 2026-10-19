"""工程清单 `rtros.toml`：把「本仓事实」从代码里搬出去。

工具仓库只认契约，不认板子：哪块板、工具链在哪、烧录用哪个芯片、默认串口是哪个，
全部由**工程根**下的 `rtros.toml` 提供。这样同一份 `scripts/` 可以原样用到别的工程。

设计约定：

* 文件缺失 → 抛 `ManifestError`（不猜、不回退到内置默认值）；
* 必填键缺失 / 路径不存在 → 抛 `ManifestError`，消息里写清是哪个键；
* 环境变量仍然可以覆盖（方便 CI / 临时换工具链），优先级：环境变量 > `rtros.toml`。
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rtros.paths import ProjectRootError, project_root

MANIFEST_NAME = "rtros.toml"


class ManifestError(RuntimeError):
    """`rtros.toml` 缺失或内容不合法。"""


@dataclass(frozen=True)
class Workspace:
    """代码布局：板级 BSP 与项目层各在哪。"""

    bsp_dir: Path
    projects_dir: Path


@dataclass(frozen=True)
class Build:
    """构建工具链。"""

    toolchain_root: Path
    scons_jobs: int

    @property
    def rtt_exec_path(self) -> Path:
        """arm-none-eabi-gcc 所在目录（由 toolchain_root 推导，可用 RTT_EXEC_PATH 覆盖）。"""
        return Path(
            os.environ.get(
                "RTT_EXEC_PATH", self.toolchain_root / "tools" / "gnu_gcc" / "arm_gcc" / "mingw" / "bin"
            )
        )

    @property
    def venv_dir(self) -> Path:
        """装了 SCons 的虚拟环境目录（可用 VENV 覆盖）。"""
        return Path(os.environ.get("VENV", self.toolchain_root / ".venv"))

    @property
    def venv_python(self) -> Path:
        """虚拟环境里的解释器（Windows 与 POSIX 各一种布局）。"""
        candidate = self.venv_dir / "Scripts" / "python.exe"
        return candidate if candidate.exists() else self.venv_dir / "bin" / "python"


@dataclass(frozen=True)
class Flash:
    """烧录参数。"""

    target: str
    pack: Path
    python: Path
    opts: tuple[str, ...]


@dataclass(frozen=True)
class Serial:
    """串口默认值（供 serial_hub / services 菜单使用）。"""

    port: str
    baud: int


@dataclass(frozen=True)
class Manifest:
    """一份校验过的工程清单。"""

    root: Path
    path: Path
    default_project: str
    workspace: Workspace
    build: Build
    flash: Flash
    serial: Serial

    def entry_dir(self, project: str | None = None) -> tuple[Path, str]:
        """返回（构建入口目录，类型）。项目存在用项目，否则回落到板级 BSP。"""
        name = (project if project is not None else os.environ.get("PROJECT", self.default_project)).strip()
        if name and name not in {"none", "board"}:
            candidate = self.workspace.projects_dir / name
            if (candidate / "SConstruct").is_file():
                return candidate, "project"
            raise ManifestError(
                f"projects/{name} 下没有 SConstruct：请检查 PROJECT 环境变量或 {MANIFEST_NAME} 的 [project].name"
            )
        return self.workspace.bsp_dir, "board"


def _require(table: dict[str, Any], key: str, where: str) -> Any:
    if key not in table:
        raise ManifestError(f"{MANIFEST_NAME} 缺少必填键 {where}{key}")
    return table[key]


def _path(root: Path, raw: Any, where: str, *, must_exist: bool = True) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ManifestError(f"{MANIFEST_NAME} 的 {where} 必须是非空字符串，当前是 {raw!r}")
    p = Path(os.path.expandvars(os.path.expanduser(raw)))
    resolved = p if p.is_absolute() else (root / p)
    resolved = resolved.resolve()
    if must_exist and not resolved.exists():
        raise ManifestError(f"{MANIFEST_NAME} 的 {where} 指向不存在的路径：{resolved}")
    return resolved


def load(root: Path | None = None) -> Manifest:
    """读取并校验工程清单；`root` 省略时按 `rtros.paths.project_root()` 定位。"""
    if root is None:
        try:
            root = project_root()
        except ProjectRootError as exc:  # 工程根都没有，清单自然找不到
            raise ManifestError(str(exc)) from exc
    path = root / MANIFEST_NAME
    if not path.is_file():
        raise ManifestError(
            f"找不到 {path}：工具仓库不含本仓事实，请在工程根放一份 {MANIFEST_NAME}"
            f"（模板见 scripts/README.md 的「工程清单」一节）"
        )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ManifestError(f"{path} 不是合法 TOML：{exc}") from exc

    workspace_t = data.get("workspace")
    build_t = data.get("build")
    flash_t = data.get("flash")
    serial_t = data.get("serial", {})
    project_t = data.get("project", {})
    if not isinstance(workspace_t, dict) or not isinstance(build_t, dict) or not isinstance(flash_t, dict):
        raise ManifestError(f"{MANIFEST_NAME} 必须包含 [workspace] / [build] / [flash] 三张表")

    workspace = Workspace(
        bsp_dir=_path(root, _require(workspace_t, "bsp_dir", "[workspace]."), "[workspace].bsp_dir"),
        projects_dir=_path(
            root,
            _require(workspace_t, "projects_dir", "[workspace]."),
            "[workspace].projects_dir",
            must_exist=False,
        ),
    )
    build = Build(
        toolchain_root=_path(root, _require(build_t, "toolchain_root", "[build]."), "[build].toolchain_root"),
        scons_jobs=int(build_t.get("scons_jobs", 20)),
    )
    opts_raw = flash_t.get("opts", "--erase=auto --frequency=1000000")
    flash = Flash(
        target=os.environ.get("PYOCD_TARGET", str(_require(flash_t, "target", "[flash]."))),
        pack=_path(root, _require(flash_t, "pack", "[flash]."), "[flash].pack"),
        python=_path(root, _require(flash_t, "python", "[flash]."), "[flash].python"),
        opts=tuple(os.environ.get("PYOCD_FLASH_OPTS", opts_raw).split()),
    )
    serial = Serial(
        port=os.environ.get("RTROS_SERIAL_PORT", str(serial_t.get("port", ""))),
        baud=int(os.environ.get("RTROS_SERIAL_BAUD", serial_t.get("baud", 115200))),
    )
    return Manifest(
        root=root,
        path=path,
        default_project=str(project_t.get("name", "base")),
        workspace=workspace,
        build=build,
        flash=flash,
        serial=serial,
    )


_CACHE: dict[Path, Manifest] = {}


def cached(root: Path | None = None) -> Manifest:
    """按工程根缓存一份清单（进程内只读一次文件）。"""
    key = root or project_root()
    if key not in _CACHE:
        _CACHE[key] = load(key)
    return _CACHE[key]


def clear_cache() -> None:
    """清缓存（测试用）。"""
    _CACHE.clear()
