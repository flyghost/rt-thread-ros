"""导入回归网：拆分/移动模块后，任何一根导入根断掉都会在这里炸。"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]

# (导入根, 模块名) —— 三套导入根是历史遗留，不是重构引入的
CASES: list[tuple[str, str]] = []
for _name in (
    "rtros.guard.cli",
    "rtros.guard.executor",
    "rtros.guard.request",
    "rtros.guard.config",
    "rtros.guard.mailbox",
    "rtros.guard.procenv",
    "rtros.firmware.build",
    "rtros.firmware.pipeline",
    "rtros.firmware.pyocd",
    "rtros.firmware.scons",
    "rtros.firmware.status",
    "rtros.firmware.config",
    "rtros.runtime.errors",
    "rtros.runtime.paths",
    "rtros.runtime.proc",
    "rtros.runtime.fs",
    "rtros.runtime.logging",
    "ai_services",
    "services_table",
    "quality",
    "check_bat",
):
    CASES.append((str(SCRIPTS), _name))

for _name in (
    "core.relay",
    "core.hub_base",
    "core.hub_serial",
    "core.hub_clients",
    "core.hub_commands",
    "core.hub_state",
    "core.control",
    "core.session",
    "core.sinks",
    "core.events",
    "core.logstore",
    "core.util",
    "core.ringbuf",
    "discovery",
    "protocols",
    "serial_hub",
    "tui.app",
    "tui.base",
    "tui.buffer",
    "tui.render",
    "tui.input",
    "tui.output",
    "tui.view",
    "tui.keys",
):
    CASES.append((str(SCRIPTS / "serial_hub"), _name))

for _name in (
    "lib.builder",
    "lib.config",
    "lib.console",
    "lib.serial_utils",
    "lib.ymodem_protocol",
    "lib.ymodem_session",
    "lib.ymodem_receiver",
):
    CASES.append((str(SCRIPTS / "ramdump"), _name))

for _name in (
    "ramdump_analyzer",
    "model",
    "memory",
    "analysis",
    "report",
    "arm_backtrace",
    "rtthread_parser",
):
    CASES.append((str(SCRIPTS / "ramdump" / "analyzer"), _name))


@pytest.mark.parametrize(("root", "module"), CASES, ids=[f"{m}" for _, m in CASES])
def test_module_imports(root: str, module: str) -> None:
    """每个模块都能被导入（先按需把导入根放到 sys.path 最前面）。"""
    sys.path.insert(0, root)
    try:
        importlib.import_module(module)
    finally:
        sys.path.remove(root)
