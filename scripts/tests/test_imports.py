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
    "rtros.serial_hub.core.relay",
    "rtros.serial_hub.core.hub_base",
    "rtros.serial_hub.core.hub_serial",
    "rtros.serial_hub.core.hub_clients",
    "rtros.serial_hub.core.hub_commands",
    "rtros.serial_hub.core.hub_state",
    "rtros.serial_hub.core.control",
    "rtros.serial_hub.core.session",
    "rtros.serial_hub.core.sinks",
    "rtros.serial_hub.core.events",
    "rtros.serial_hub.core.logstore",
    "rtros.serial_hub.core.util",
    "rtros.serial_hub.core.ringbuf",
    "rtros.serial_hub.discovery",
    "rtros.serial_hub.protocols",
    "rtros.serial_hub",
    "rtros.serial_hub.tui.app",
    "rtros.serial_hub.tui.base",
    "rtros.serial_hub.tui.buffer",
    "rtros.serial_hub.tui.render",
    "rtros.serial_hub.tui.input",
    "rtros.serial_hub.tui.output",
    "rtros.serial_hub.tui.view",
    "rtros.serial_hub.tui.keys",
):
    CASES.append((str(SCRIPTS / "serial_hub"), _name))

for _name in (
    "rtros.ramdump.lib.builder",
    "rtros.ramdump.lib.config",
    "rtros.ramdump.lib.console",
    "rtros.ramdump.lib.serial_utils",
    "rtros.ramdump.lib.ymodem_protocol",
    "rtros.ramdump.lib.ymodem_session",
    "rtros.ramdump.lib.ymodem_receiver",
):
    CASES.append((str(SCRIPTS / "ramdump"), _name))

for _name in (
    "rtros.ramdump.analyzer.ramdump_analyzer",
    "rtros.ramdump.analyzer.model",
    "rtros.ramdump.analyzer.memory",
    "rtros.ramdump.analyzer.analysis",
    "rtros.ramdump.analyzer.report",
    "rtros.ramdump.analyzer.arm_backtrace",
    "rtros.ramdump.analyzer.rtthread_parser",
):
    CASES.append((str(SCRIPTS / "ramdump" / "rtros.ramdump.analyzer"), _name))


@pytest.mark.parametrize(("root", "module"), CASES, ids=[f"{m}" for _, m in CASES])
def test_module_imports(root: str, module: str) -> None:
    """每个模块都能被导入（先按需把导入根放到 sys.path 最前面）。"""
    sys.path.insert(0, root)
    try:
        importlib.import_module(module)
    finally:
        sys.path.remove(root)
