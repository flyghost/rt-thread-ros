#!/usr/bin/env python3
"""
rtthread_parser.py -- RT-Thread kernel structure parser for ramdump analysis.

Parses RT-Thread kernel objects from a memory dump:
  - Thread list (name, SP, stack usage, priority, state)
  - Object containers

This is a simplified parser that works on raw memory images.
For production use, pyelftools symbol resolution should be added.
"""

import struct
from dataclasses import dataclass

# RT-Thread thread state masks (from rtdef.h)
THREAD_STATES = {
    0x00: "INIT",
    0x01: "READY",
    0x02: "SUSPEND",
    0x03: "RUNNING",
    0x04: "CLOSE",
}

THREAD_STAT_MASK = 0x0F

# RT_NAME_MAX from rtconfig.h
RT_NAME_MAX = 8

# Approximate sizes for key structures
# rt_thread size (approximate for Cortex-M4, no FPU): ~140 bytes
# These are estimates; accurate values require DWARF debug info
RT_THREAD_SP_OFFSET = 4  # sp pointer offset
RT_THREAD_ENTRY_OFFSET = 8  # entry function
RT_THREAD_STACK_ADDR_OFFSET = 56  # stack_addr
RT_THREAD_STACK_SIZE_OFFSET = 60  # stack_size
RT_THREAD_PRIORITY_OFFSET = 84  # current_priority
RT_THREAD_STAT_OFFSET = 88  # stat
RT_THREAD_NAME_OFFSET = 140  # name (approximate, after parent + list nodes)

# rt_list_node: next (4 bytes), prev (4 bytes)
RT_LIST_NODE_SIZE = 8


@dataclass
class ThreadInfo:
    """Parsed RT-Thread thread information."""

    name: str
    sp: int
    stack_addr: int
    stack_size: int
    priority: int
    state: int
    state_name: str
    raw_offset: int  # offset in memory image


def parse_thread_state(stat: int) -> str:
    """Convert thread state value to human-readable string."""
    base = stat & THREAD_STAT_MASK
    name = THREAD_STATES.get(base, f"UNKNOWN(0x{base:02X})")

    if stat & 0x10:
        name += "|SIGNAL"
    if stat & 0x20:
        name += "|SIGNAL_WAIT"
    if stat & 0x40:
        name += "|SIGNAL_PENDING"

    return name


def scan_threads(
    memory: bytes, memory_base: int, thread_obj_start: int, thread_obj_end: int
) -> list[ThreadInfo]:
    """Scan for thread objects in a memory image.

    This uses heuristics to find thread objects by looking for
    rt_thread structures. For production use, resolve the thread
    list via ELF symbols instead.
    """
    threads = []

    for offset in range(thread_obj_start - memory_base, thread_obj_end - memory_base, 4):
        if offset + 200 > len(memory):
            break

        try:
            # Try to read thread name (8 bytes at name offset)
            name_start = offset + RT_THREAD_NAME_OFFSET
            name_bytes = memory[name_start : name_start + RT_NAME_MAX]
            raw = name_bytes.split(b"\x00")[0]

            # Basic validation: name should be printable ASCII。
            # 必须按**原始字节**判定：先 decode(errors='replace') 再 encode 会把
            # U+FFFD 变成 '?'(0x3F)，让乱码名蒙混过关，最后 print 时在 GBK 控制台崩掉。
            if not raw or not all(32 <= c < 127 for c in raw):
                continue
            name = raw.decode("ascii")

            # Read thread fields
            sp = struct.unpack_from("<I", memory, offset + RT_THREAD_SP_OFFSET)[0]
            stack_addr = struct.unpack_from("<I", memory, offset + RT_THREAD_STACK_ADDR_OFFSET)[0]
            stack_size = struct.unpack_from("<I", memory, offset + RT_THREAD_STACK_SIZE_OFFSET)[0]
            priority = struct.unpack_from("<B", memory, offset + RT_THREAD_PRIORITY_OFFSET)[0]
            stat = struct.unpack_from("<B", memory, offset + RT_THREAD_STAT_OFFSET)[0]

            threads.append(
                ThreadInfo(
                    name=name,
                    sp=sp,
                    stack_addr=stack_addr,
                    stack_size=stack_size,
                    priority=priority,
                    state=stat,
                    state_name=parse_thread_state(stat),
                    raw_offset=offset + memory_base,
                )
            )
        except (struct.error, IndexError):
            continue

    return threads


def compute_stack_usage(memory: bytes, memory_base: int, thread: ThreadInfo) -> tuple[int, int, float]:
    """Compute stack usage for a thread.

    RT-Thread fills thread stacks with '#' (0x23) on creation.
    By scanning for non-0x23 bytes, we can estimate stack usage.
    """
    stack_start = thread.stack_addr
    used = 0

    # 候选线程是启发式扫出来的，stack_addr / stack_size 可能是垃圾值：
    #   * stack_start 低于 memory_base → 偏移为负（Python 会回绕成从尾部索引，直接 IndexError）
    #   * 整段落在映射内存之外 → 跳过
    base = stack_start - memory_base
    size = max(0, thread.stack_size)
    start = max(0, base)
    end = min(len(memory), base + size)
    for offset in range(start, end):
        if memory[offset] != 0x23:
            used = offset - base

    used = max(0, min(used, size))
    pct = (used / size * 100) if size > 0 else 0
    return used, size, pct


def format_thread_list(
    threads: list[ThreadInfo],
    memory: bytes | None = None,
    memory_base: int = 0,
) -> str:
    """Format thread list for display."""
    lines = []
    lines.append("=== RT-Thread Thread List ===")
    header = (
        f"{'Name':<10} {'SP':>10} {'Stack Base':>10} "
        f"{'Stack Size':>10} {'Used':>10} {'%':>5} "
        f"{'Prio':>4} {'State':<20}"
    )
    lines.append(header)
    lines.append("-" * len(header))

    for t in threads:
        if memory:
            used, _total, pct = compute_stack_usage(memory, memory_base, t)
            lines.append(
                f"{t.name:<10} 0x{t.sp:08X} 0x{t.stack_addr:08X} "
                f"{t.stack_size:>10} {used:>10} {pct:>4.1f}% "
                f"{t.priority:>4} {t.state_name:<20}"
            )
        else:
            lines.append(
                f"{t.name:<10} 0x{t.sp:08X} 0x{t.stack_addr:08X} "
                f"{t.stack_size:>10} {'N/A':>10} {'N/A':>5} "
                f"{t.priority:>4} {t.state_name:<20}"
            )

    lines.append("=" * len(header))
    return "\n".join(lines)


# ---- Standalone test ----
if __name__ == "__main__":
    print("RT-Thread Parser Module")
    print("Usage: import from ramdump_analyzer.py")
