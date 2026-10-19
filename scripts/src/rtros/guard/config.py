"""守卫的配置层：把 tasks.toml 读成 Task 列表与派生常量。

`tasks.toml` 是「允许执行哪些命令」的唯一事实来源；这里只负责解析、校验与取值，
不含任何执行逻辑，因此可以被 request/executor/cli 任一层安全导入。
"""

from __future__ import annotations

import os
from pathlib import Path

from rtros import manifest
from rtros.paths import tool_root

PROTOCOL = 1

REPO = tool_root().parent

TASKS_FILE = Path(__file__).resolve().with_name("tasks.toml")


class Task:
    """tasks.toml 里 [[tasks]] 的一条。"""

    __slots__ = ("allow", "builtin", "cwd", "id", "run", "timeout", "title")

    def __init__(self, raw: dict) -> None:
        self.id = str(raw["id"])
        self.title = str(raw.get("title", self.id))
        self.timeout = float(raw.get("timeout", 180))
        self.allow = tuple(str(x) for x in raw.get("allow", ()))
        self.run = [[str(x) for x in argv] for argv in raw.get("run", ())]
        self.builtin = raw.get("builtin")
        self.cwd = str(raw.get("cwd", "."))


def _load_config() -> tuple[dict, dict, dict]:
    """读 tasks.toml → (guard 设置, paths, 任务表)。配置坏了直接退出，别静默半残。"""
    try:
        import tomllib
    except ImportError:
        raise SystemExit("守卫需要 Python 3.11+（tasks.toml 用 tomllib 读）") from None
    if not TASKS_FILE.is_file():
        raise SystemExit(f"找不到任务表：{TASKS_FILE}")
    with TASKS_FILE.open("rb") as fh:
        doc = tomllib.load(fh)
    settings = dict(doc.get("guard", {}))
    paths = {str(k): str(v) for k, v in doc.get("paths", {}).items()}
    tasks: dict[str, Task] = {}
    for raw in doc.get("tasks", ()):
        task = Task(raw)
        if task.id in tasks:
            raise SystemExit(f"tasks.toml 任务 id 重复：{task.id}")
        if not task.builtin and not task.run:
            raise SystemExit(f"tasks.toml 任务 {task.id} 既没有 run 也没有 builtin")
        tasks[task.id] = task
    if not tasks:
        raise SystemExit("tasks.toml 里一条任务都没有")
    return settings, paths, tasks


SETTINGS, PATHS, TASKS = _load_config()


def _path(name: str, default: str = "") -> Path:
    """[paths] 里的值：绝对路径原样用，相对路径相对仓库根。"""
    raw = PATHS.get(name) or default
    path = Path(raw)
    return path if path.is_absolute() else (REPO / raw)


# 机器相关路径的默认值来自工程根的 rtros.toml（tasks.toml 里留空即取这里），
# 想临时改就设 tasks.toml 的 [paths] 或对应环境变量。
_MANIFEST = manifest.cached()
_DEFAULT_PROJECT = os.environ.get("PROJECT", _MANIFEST.default_project).strip()
_ENTRY_DIR, _ = _MANIFEST.entry_dir(_DEFAULT_PROJECT)

PYOCD_PKG_DIR = _path("pyocd_pkg", "tools/pyocd/pkg")

PY_PKG_PY = _path("pyocd_python", str(_MANIFEST.flash.python))

PYOCD_PACK = _path("pyocd_pack", str(_MANIFEST.flash.pack))

BUILD_ENTRY = _path("build_entry", "scripts/run_rtros.py")

VENV_PY = _path("venv_python", str(_MANIFEST.build.venv_python))

ENV_ROOT = _path("env_root", str(_MANIFEST.build.toolchain_root))

ARM_GCC_BIN = _path("arm_gcc_bin", str(_MANIFEST.build.rtt_exec_path))

DEFAULT_BIN = _path("default_bin", str(_MANIFEST.root / "out" / "bin" / _ENTRY_DIR.name / "rtthread.bin"))

DEFAULT_TARGET = PATHS.get("default_target") or _MANIFEST.flash.target


POLL_SECONDS = float(SETTINGS.get("poll_seconds", 2.0))


HEARTBEAT_SECONDS = float(SETTINGS.get("heartbeat_seconds", 2.0))


RUNNING_SECONDS = 1.0


STALL_SECONDS = float(SETTINGS.get("stall_seconds", 180.0))


DEFAULT_EXPIRES = int(SETTINGS.get("default_expires", 900))


DEFAULT_WAIT = float(SETTINGS.get("default_wait", 300.0))


TAIL_LINES = 40


MAILBOX_DEFAULT = str(SETTINGS.get("mailbox", "out/guard"))


CHILD_TMP = REPO / "out" / "tmp"
