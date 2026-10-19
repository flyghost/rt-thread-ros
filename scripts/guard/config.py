"""守卫的配置层：把 tasks.toml 读成 Task 列表与派生常量。

`tasks.toml` 是「允许执行哪些命令」的唯一事实来源；这里只负责解析、校验与取值，
不含任何执行逻辑，因此可以被 request/executor/cli 任一层安全导入。
"""

from __future__ import annotations

from pathlib import Path

PROTOCOL = 1


REPO = Path(__file__).resolve().parents[2]


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


PYOCD_PKG_DIR = _path("pyocd_pkg", "tools/pyocd/pkg")


PY_PKG_PY = _path("pyocd_python", r"E:\software\InstallerEdition\DevTools\Python\Python313\python.exe")


PYOCD_PACK = _path("pyocd_pack", "tools/pyocd/packs/Keil.STM32F4xx_DFP.2.14.0-small.pack")


BUILD_ENTRY = _path("build_entry", "scripts/firmware/build.py")


VENV_PY = _path("venv_python", r"E:\software\EnvEdition\rt-thread-env\env-windows\.venv\Scripts\python.exe")


ENV_ROOT = _path("env_root", r"E:\software\EnvEdition\rt-thread-env\env-windows")


ARM_GCC_BIN = _path(
    "arm_gcc_bin", r"E:\software\EnvEdition\rt-thread-env\env-windows\tools\gnu_gcc\arm_gcc\mingw\bin"
)


DEFAULT_BIN = _path("default_bin", "out/bin/base/rtthread.bin")


DEFAULT_TARGET = PATHS.get("default_target") or "STM32F407VE"


POLL_SECONDS = float(SETTINGS.get("poll_seconds", 2.0))


HEARTBEAT_SECONDS = float(SETTINGS.get("heartbeat_seconds", 2.0))


RUNNING_SECONDS = 1.0


STALL_SECONDS = float(SETTINGS.get("stall_seconds", 180.0))


DEFAULT_EXPIRES = int(SETTINGS.get("default_expires", 900))


DEFAULT_WAIT = float(SETTINGS.get("default_wait", 300.0))


TAIL_LINES = 40


MAILBOX_DEFAULT = str(SETTINGS.get("mailbox", "out/guard"))


CHILD_TMP = REPO / "out" / "tmp"
