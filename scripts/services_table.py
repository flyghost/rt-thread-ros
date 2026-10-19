"""服务表：ai_services 面板上「有哪些命令」的唯一事实来源。

这里只有数据与查表，不做任何执行；执行在 ai_services.py 里。加一条服务只需改这个文件。
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

PY = sys.executable
PY313 = Path(r"E:\software\InstallerEdition\DevTools\Python\Python313\python.exe")
VENV_PY = Path(r"E:\software\EnvEdition\rt-thread-env\env-windows\.venv\Scripts\python.exe")
PLACEHOLDER_HUB = "{hub_python}"


@dataclass(frozen=True)
class Service:
    """一条服务：名字 + 菜单文案 + 要跑的 argv（或按序执行的多条命令）。"""

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
        argv=("{python}", "scripts/run_rtros.py", "build"),
        note="产出 out/bin/base/",
    ),
    Service(
        "flash",
        "flash 烧录（默认 out/bin/base/rtthread.bin）",
        "2",
        argv=("{python}", "scripts/run_rtros.py", "flash"),
    ),
    Service(
        "build-flash",
        "build-flash 编译 + 烧录",
        "3",
        argv=("{python}", "scripts/run_rtros.py", "build-flash"),
    ),
    Service(
        "board-build",
        "board 板级 BSP 编译（对照用）",
        "4",
        argv=("{python}", "scripts/run_rtros.py", "--board", "build"),
        note="入口 bsp/stm32/stm32f407-atk-explorer",
    ),
    Service(
        "clean",
        "clean 清理中间文件与产物",
        "5",
        argv=("{python}", "scripts/run_rtros.py", "clean"),
    ),
    Service(
        "status",
        "status 状态总览（固件/守卫/串口/端口）",
        "6",
        group=(
            ("{python}", "scripts/run_rtros.py", "status"),
            ("{python}", "scripts/run_rtros.py", "guard", "--status"),
            ("{hub_python}", "scripts/serial_hub/serial_hub.py", "--list"),
        ),
        needs_pyserial=True,
        allow_fail=True,
    ),
    Service(
        "guard",
        "guard 起守卫（前台常驻，AI 无人值守用）",
        "7",
        argv=("{python}", "scripts/run_rtros.py", "guard"),
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
    Service("guard-status", "守卫状态", argv=("{python}", "scripts/run_rtros.py", "guard", "--status")),
    Service(
        "guard-tasks",
        "守卫允许的任务（tasks.toml）",
        argv=("{python}", "scripts/run_rtros.py", "guard", "--tasks"),
    ),
    Service(
        "hub-list",
        "列出串口",
        argv=(PLACEHOLDER_HUB, "scripts/serial_hub/serial_hub.py", "--list"),
        needs_pyserial=True,
    ),
    Service("help", "打印帮助", argv=("{python}", "scripts/ai_services.py", "--help")),
)


def find(name: str) -> Service | None:
    """按名字或菜单编号查一条服务；找不到返回 None。"""
    name = name.lower()
    for svc in SERVICES:
        if svc.name == name:
            return svc
    for svc in SERVICES:
        if svc.key and svc.key == name:
            return svc
    return None
