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

import contextlib
import os
import socket
import sys
import unicodedata
from pathlib import Path

from runtime import proc
from runtime.errors import ToolMissingError
from services_table import SERVICES, Service, find

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable  # 与运行本脚本的解释器一致（bat 已经探测过可用性）

PY313 = Path(r"E:\software\InstallerEdition\DevTools\Python\Python313\python.exe")
VENV_PY = Path(r"E:\software\EnvEdition\rt-thread-env\env-windows\.venv\Scripts\python.exe")

PLACEHOLDER_HUB = "{hub_python}"


# ---------------------------------------------------------------- 解释器探测


def _can_import(python: str, module: str) -> bool:
    try:
        done = proc.run([python, "-c", f"import {module}"], capture=False, timeout=20)
    except (OSError, ToolMissingError):
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
        return proc.run(argv, cwd=REPO, capture=False).returncode
    except ToolMissingError as exc:
        print(f"[ERROR] {exc.message}", flush=True)
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
        proc.popen(hub_cmd, cwd=REPO, creationflags=proc.CREATE_NEW_CONSOLE)
        guard = next(s for s in SERVICES if s.name == "guard")
        return run_argv(expand(guard.argv, hub) + extra)

    if service.group:
        worst = 0
        for group_argv in service.group:
            code = run_argv(expand(group_argv, hub))
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


def menu_loop() -> int:
    while True:
        print(render_menu(), flush=True)
        try:
            if sys.stdin.isatty():
                choice = input("select> ").strip().lower()
            else:
                raw = sys.stdin.readline()
                if not raw:  # 管道结束：当作退出，别抛 EOFError
                    print("（stdin 已关闭，退出）")
                    return 0
                choice = raw.strip().lower()
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
    with contextlib.suppress(AttributeError, OSError):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

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
