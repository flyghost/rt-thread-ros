"""ai_services.py -- 给「人」用的一键服务清单（菜单 + 命令行）。

设计原则
--------
* **命令表就是本文件的 SERVICES**（单一事实来源）。`ai_services.bat` 只是几十行的启动外壳，
  不再把命令硬编码在 bat 里；以后增加服务只改这里的一行。
* **AI / CI 不要走 bat**：直接用 `python scripts/ai_services.py --run <name>`，
  或干脆调各脚本本身（比如 `python scripts/firmware/build.py build-flash`）。
* 命令一律用 **argv 列表**（不拼字符串、不过 shell），所以 `& | > % "` 这些字符不会被 cmd 二次解析。

用法
----
    python scripts/ai_services.py                 # 交互菜单（双击 bat 即是这条）
    python scripts/ai_services.py --list          # 打印清单（含等价命令，供文档/AI 读取）
    python scripts/ai_services.py --run build     # 按名字执行
    python scripts/ai_services.py build           # 裸名字 == --run build
    python scripts/ai_services.py hub COM5 9600   # 多余参数透传给对应命令
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable  # 与运行本脚本的解释器一致（bat 已经探测过可用性）

PY313 = Path(r"E:\software\InstallerEdition\DevTools\Python\Python313\python.exe")
VENV_PY = Path(r"E:\software\EnvEdition\rt-thread-env\env-windows\.venv\Scripts\python.exe")

PLACEHOLDER_HUB = "{hub_python}"


@dataclass(frozen=True)
class Service:
    name: str  # 命令行名字（--run 用）
    title: str  # 菜单文案
    key: str = ""  # 菜单编号（空=只给命令行用）
    argv: tuple[str, ...] = ()  # 单条命令
    group: tuple[tuple[str, ...], ...] = ()  # 多条命令按序执行
    needs_pyserial: bool = False
    daemon: bool = False  # 前台常驻（Ctrl+C 结束），菜单执行后不暂停
    note: str = ""  # 菜单右侧补充说明
    allow_fail: bool = False  # 组命令允许个别失败（如 status）


SERVICES: tuple[Service, ...] = (
    Service(
        "build",
        "build 编译固件（projects/base）",
        "1",
        argv=("{python}", "scripts/firmware/build.py", "build"),
        note="产出 out/bin/base/",
    ),
    Service(
        "flash",
        "flash 烧录（默认 out/bin/base/rtthread.bin）",
        "2",
        argv=("{python}", "scripts/firmware/build.py", "flash"),
    ),
    Service(
        "build-flash",
        "build-flash 编译 + 烧录",
        "3",
        argv=("{python}", "scripts/firmware/build.py", "build-flash"),
    ),
    Service(
        "board-build",
        "board 板级 BSP 编译（对照用）",
        "4",
        argv=("{python}", "scripts/firmware/build.py", "--board", "build"),
        note="入口 bsp/stm32/stm32f407-atk-explorer",
    ),
    Service(
        "clean",
        "clean 清理中间文件与产物",
        "5",
        argv=("{python}", "scripts/firmware/build.py", "clean"),
    ),
    Service(
        "status",
        "status 状态总览（固件/守卫/串口/端口）",
        "6",
        group=(
            ("{python}", "scripts/firmware/build.py", "status"),
            ("{python}", "scripts/guard/guard.py", "--status"),
            ("{hub_python}", "scripts/serial_hub/serial_hub.py", "--list"),
        ),
        needs_pyserial=True,
        allow_fail=True,
    ),
    Service(
        "guard",
        "guard 起守卫（前台常驻，AI 无人值守用）",
        "7",
        argv=("{python}", "scripts/guard/guard.py"),
        daemon=True,
        note="窗口别关；Ctrl+C 结束",
    ),
    Service(
        "hub",
        "hub 起串口 hub（TCP 5555 / 5556，前台常驻）",
        "8",
        argv=(
            PLACEHOLDER_HUB,
            "scripts/serial_hub/serial_hub.py",
            "--com",
            "COM46",
            "--baud",
            "115200",
            "--ui",
            "tui",
        ),
        needs_pyserial=True,
        daemon=True,
        note="可选参数：hub COM5 [baud]",
    ),
    Service(
        "both",
        "both 守卫 + hub（hub 另开窗口）",
        "9",
        note="先开 hub 窗口，再前台起守卫",
    ),
    Service("guard-status", "守卫状态", argv=("{python}", "scripts/guard/guard.py", "--status")),
    Service(
        "guard-tasks", "守卫允许的任务（tasks.toml）", argv=("{python}", "scripts/guard/guard.py", "--tasks")
    ),
    Service(
        "hub-list",
        "列出串口",
        argv=(PLACEHOLDER_HUB, "scripts/serial_hub/serial_hub.py", "--list"),
        needs_pyserial=True,
    ),
    Service("help", "打印帮助", argv=("{python}", "scripts/ai_services.py", "--help")),
)


# ---------------------------------------------------------------- 解释器探测


def _can_import(python: str, module: str) -> bool:
    try:
        done = subprocess.run(
            [python, "-c", f"import {module}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def hub_python() -> str:
    """选出装了 pyserial 的解释器（串口 hub 需要）。"""
    for candidate in (PY, str(PY313), str(VENV_PY), "python"):
        if candidate and Path(candidate).exists() and _can_import(candidate, "serial"):
            return candidate
    for candidate in (PY, str(PY313), str(VENV_PY), "python"):
        if _can_import(candidate, "serial"):
            return candidate
    return PY


def expand(argv: tuple[str, ...], hub: str) -> list[str]:
    """展开占位符；串口 hub 的 COM/波特率/UI 允许用环境变量覆盖。"""
    out = [
        item.replace("{python}", PY).replace("{root}", str(REPO)).replace(PLACEHOLDER_HUB, hub)
        for item in argv
    ]
    if "serial_hub.py" in out:
        for flag, env in (("--com", "HUB_COM"), ("--baud", "HUB_BAUD"), ("--ui", "HUB_UI")):
            if flag in out and env in os.environ:
                out[out.index(flag) + 1] = os.environ[env]
    return out


def run_argv(argv: list[str], *, show: bool = True) -> int:
    if show:
        print(f"$ {' '.join(argv)}", flush=True)
    try:
        return subprocess.call(argv, cwd=str(REPO))
    except FileNotFoundError:
        print(f"[ERROR] 找不到可执行文件：{argv[0]}", flush=True)
        return 127
    except KeyboardInterrupt:
        print("\n[interrupted]", flush=True)
        return 130


# ---------------------------------------------------------------- 单项执行


def port_state() -> str:
    parts = []
    for port in (5555, 5556):
        sock = socket.socket()
        sock.settimeout(0.3)
        try:
            sock.connect(("127.0.0.1", port))
            parts.append(f"{port}=LISTEN")
        except OSError:
            parts.append(f"{port}=closed")
        finally:
            sock.close()
    return "  ".join(parts)


def run_service(service: Service, extra: list[str]) -> int:
    hub = hub_python()
    print(f"[{service.name}] {service.title}", flush=True)

    if service.name == "both":
        hub_cmd = expand(
            (
                PLACEHOLDER_HUB,
                "scripts/serial_hub/serial_hub.py",
                "--com",
                os.environ.get("HUB_COM", "COM46"),
                "--baud",
                os.environ.get("HUB_BAUD", "115200"),
                "--ui",
                os.environ.get("HUB_UI", "tui"),
            ),
            hub,
        )
        print(f"$ {' '.join(hub_cmd)}   (new console)", flush=True)
        subprocess.Popen(hub_cmd, cwd=str(REPO), creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
        guard = next(s for s in SERVICES if s.name == "guard")
        return run_argv(expand(guard.argv, hub) + extra)

    if service.group:
        worst = 0
        for argv in service.group:
            code = run_argv(expand(argv, hub))
            if code != 0 and not service.allow_fail:
                return code
            worst = max(worst, code)
        print(f"[{service.name}] 端口：{port_state()}", flush=True)
        return 0 if service.allow_fail else worst

    argv = expand(service.argv, hub) + extra
    if service.needs_pyserial and hub == PY and not _can_import(hub, "serial"):
        print("[ERROR] 没找到装了 pyserial 的 Python（试过 python / Python313 / venv）", flush=True)
        return 2
    return run_argv(argv)


# ---------------------------------------------------------------- 清单与菜单


def render_list() -> str:
    hub = hub_python()
    lines = ["key  name          command"]
    lines.append("---  ------------  -------")
    for svc in SERVICES:
        if svc.group:
            cmd = " ; ".join(" ".join(expand(a, hub)) for a in svc.group)
        elif svc.argv:
            cmd = " ".join(expand(svc.argv, hub))
        else:
            cmd = "(定制流程)"
        lines.append(f"{svc.key or '-':<3}  {svc.name:<12}  {cmd}")
    return "\n".join(lines)


def _display_width(text: str) -> int:
    """中文在控制台占两格，按显示宽度对齐菜单。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _display_width(text))


def render_menu() -> str:
    lines = ["", "=" * 72, " rt-thread-ros  ai_services（命令表在 scripts/ai_services.py）", "=" * 72]
    for svc in SERVICES:
        if svc.key:
            lines.append(f"  {svc.key}  {_pad(svc.title, 50)}{svc.note}")
    lines.append("  0  exit")
    lines.append("=" * 72)
    return "\n".join(lines)


def find(name: str) -> Service | None:
    name = name.lower()
    for svc in SERVICES:
        if svc.name == name:
            return svc
    for svc in SERVICES:
        if svc.key and svc.key == name:
            return svc
    return None


def menu_loop() -> int:
    while True:
        print(render_menu(), flush=True)
        try:
            choice = input("select> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if choice in ("0", "q", "quit", "exit", ""):
            return 0
        if choice in ("l", "list"):
            print(render_list(), flush=True)
            continue
        svc = find(choice)
        if svc is None:
            print(f"[ERROR] 没有这个条目：{choice}", flush=True)
            continue
        code = run_service(svc, [])
        print(f"\n[{svc.name}] exit code {code}\n", flush=True)
        if svc.daemon:
            return code


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        pass

    args = list(argv)
    if not args:
        return menu_loop()

    first = args[0].lower()
    if first in ("-h", "--help", "help"):
        print(__doc__)
        print(render_list())
        return 0
    if first in ("-l", "--list"):
        print(render_list())
        return 0
    if first in ("--run",):
        if len(args) < 2:
            print("[ERROR] --run 需要条目名，例如 --run build", flush=True)
            return 2
        name, extra = args[1], args[2:]
    else:
        name, extra = args[0], args[1:]

    svc = find(name)
    if svc is None:
        print(f"[ERROR] 未知条目：{name}\n", flush=True)
        print(render_list(), flush=True)
        return 2
    if svc.name == "help":
        print(__doc__)
        return 0
    return run_service(svc, extra)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
