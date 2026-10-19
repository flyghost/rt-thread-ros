"""数据模型与地址常量：分析结果的结构、内存映射的边界值。"""

from __future__ import annotations

from dataclasses import dataclass, field

# Optional imports
from arm_backtrace import RegisterSnapshot, StackFrame
from rtthread_parser import ThreadInfo


@dataclass
class ExceptionRecord:
    """Parsed exception record from ramdump."""

    valid: bool
    fault_type: int = 0
    fault_name: str = ""
    cfsr: int = 0
    hfsr: int = 0
    mmfar: int = 0
    bfar: int = 0
    fpscr: int = 0
    hw_frame_ptr: int = 0
    current_thread_sp: int = 0
    thread_name: str = ""
    tick: int = 0
    registers: RegisterSnapshot | None = None

    def __str__(self):
        if not self.valid:
            return "No valid exception record found."
        lines = [
            "=== Exception Record ===",
            f"Fault Type: {self.fault_name}",
            f"Thread:     {self.thread_name}",
            f"Tick:       {self.tick}",
            f"CFSR:       0x{self.cfsr:08X}",
            f"HFSR:       0x{self.hfsr:08X}",
            f"MMFAR:      0x{self.mmfar:08X}",
            f"BFAR:       0x{self.bfar:08X}",
            f"Frame Ptr:  0x{self.hw_frame_ptr:08X}",
            f"Thread SP:  0x{self.current_thread_sp:08X}",
        ]
        if self.registers:
            lines.append("Registers:")
            lines.append(str(self.registers))
        return "\n".join(lines)


@dataclass
class RamdumpAnalysis:
    """Complete ramdump analysis result."""

    exception: ExceptionRecord
    fault_decode: str
    backtrace: list[StackFrame]
    threads: list[ThreadInfo]
    sram_path: str
    ccm_path: str
    elf_path: str
    symbols: dict[int, str] = field(default_factory=dict)


SRAM_BASE = 0x20000000


SRAM_SIZE = 128 * 1024


CCM_BASE = 0x10000000


CCM_SIZE = 64 * 1024


FLASH_BASE = 0x08000000


FLASH_SIZE = 1024 * 1024


EXCEPTION_MAGIC = 0x52414D44  # "RAMD"


EXCEPTION_STRUCT_FORMAT = "<9I8sII"


RT_NAME_MAX = 8


FAULT_NAMES = {
    0: "HardFault",
    1: "MemManage",
    2: "BusFault",
    3: "UsageFault",
    4: "Assert",
}
