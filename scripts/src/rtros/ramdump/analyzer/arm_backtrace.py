#!/usr/bin/env python3
"""
arm_backtrace.py -- ARM Thumb-2 call stack backtrace analysis.

Reconstructs the call stack from a ramdump memory image using:
1. The saved hardware exception frame (r0-r3, r12, lr, pc, xpsr)
2. ELF symbol table (for function name resolution)
3. ARM Thumb-2 call convention: BL/BLX instructions at (return_address - 2/4)

The algorithm scans the stack for potential return addresses (words that
point into known code regions) and verifies they are preceded by a call
instruction (BL or BLX).
"""

import struct
from dataclasses import dataclass


@dataclass
class StackFrame:
    """Represents one stack frame in a backtrace."""

    depth: int
    stack_addr: int  # address on the stack where this frame was found
    return_addr: int  # the return address (value on stack)
    call_addr: int  # the call instruction address
    func_name: str  # resolved function name (or "unknown")
    func_offset: int  # offset into the function


@dataclass
class RegisterSnapshot:
    """Hardware exception frame registers (from ARM cortex-M auto-stack)."""

    r0: int = 0
    r1: int = 0
    r2: int = 0
    r3: int = 0
    r12: int = 0
    lr: int = 0
    pc: int = 0
    xpsr: int = 0

    @classmethod
    def from_bytes(cls, data: bytes) -> "RegisterSnapshot":
        """Parse 32 bytes of hardware-stacked frame."""
        values = struct.unpack("<8I", data[:32])
        return cls(
            r0=values[0],
            r1=values[1],
            r2=values[2],
            r3=values[3],
            r12=values[4],
            lr=values[5],
            pc=values[6],
            xpsr=values[7],
        )

    def __str__(self):
        return (
            f"  r0=0x{self.r0:08X} r1=0x{self.r1:08X} "
            f"r2=0x{self.r2:08X} r3=0x{self.r3:08X}\n"
            f"  r12=0x{self.r12:08X} lr=0x{self.lr:08X} "
            f"pc=0x{self.pc:08X} xpsr=0x{self.xpsr:08X}"
        )


def _is_thumb_bl(word: int) -> bool:
    """Check if a halfword is a BL/BLX instruction (Thumb-2).

    BL instruction encoding (32-bit Thumb-2):
      - First halfword:  1111 0 S imm10[9:0]  -> 0xF000-0xF7FF (S=0)
                                               -> 0xF400-0xF7FF (S=1)
      - Second halfword: 11 J1 1 J2 imm11
    More practically, check first halfword for BL pattern.
    """
    hw = word & 0xFFFF
    # BL: 11110... in bits [15:11]
    return (hw & 0xF800) in (0xF000, 0xF800)


def _is_thumb_blx(word: int) -> bool:
    """Check for BLX (register or immediate)."""
    hw = word & 0xFFFF
    # BLX reg: 0100 0111 0xxx x000 -> 0x4780 with low bits in xxx
    if (hw & 0xFF87) == 0x4780:
        return True
    # BLX imm (Thumb-2): same encoding as BL but with different H bit
    return (hw & 0xF800) == 0xF000


def is_call_instruction(data: bytes, addr: int) -> bool:
    """Check if the instruction at 'addr' is a call (BL/BLX).

    ARM Thumb-2: BL is a 32-bit instruction (4 bytes).
    The return address saved in LR = pc + 4 for 32-bit instructions,
    or pc + 2 for 16-bit instructions.
    """
    # Try 4-byte instruction at (addr - 4)
    if addr >= 4:
        instr = struct.unpack("<I", data[addr - 4 : addr])[0]
        if _is_thumb_bl(instr):
            return True

    # Try 2-byte instruction at (addr - 2) -- BLX reg is 16-bit
    if addr >= 2:
        instr16 = struct.unpack("<H", data[addr - 2 : addr])[0]
        if _is_thumb_blx(instr16):
            return True

    return False


def backtrace(
    memory: bytes,
    memory_base: int,
    sp: int,
    stack_limit: int,
    code_start: int,
    code_end: int,
    symbols: dict[int, str],
) -> list[StackFrame]:
    """Perform ARM Thumb-2 stack backtrace.

    Args:
        memory:      The full memory image bytes
        memory_base: Base address of the memory image
        sp:          Stack pointer at crash time
        stack_limit: Upper bound of the stack
        code_start:  Start of .text section
        code_end:    End of .text section
        symbols:     Dict mapping address -> function name

    Returns:
        List of StackFrame objects, deepest frame first.
    """
    frames = []

    # Helper: resolve symbol name
    def resolve(addr: int) -> tuple[str, int]:
        best_name = "unknown"
        best_offset = 0
        best_sym_addr = 0
        for sym_addr, name in symbols.items():
            if sym_addr <= addr and sym_addr > best_sym_addr:
                best_sym_addr = sym_addr
                best_name = name
                best_offset = addr - sym_addr
        return best_name, best_offset

    # Helper: read 32-bit word from memory image
    def read32(addr: int) -> int | None:
        if memory_base <= addr < memory_base + len(memory):
            return struct.unpack("<I", memory[addr - memory_base : addr - memory_base + 4])[0]
        return None

    # Add initial frame from pc
    name, offset = resolve(sp)
    frames.append(
        StackFrame(
            depth=0,
            stack_addr=0,
            return_addr=0,
            call_addr=sp,
            func_name=name,
            func_offset=offset,
        )
    )

    # Walk the stack looking for return addresses
    depth = 1
    for addr in range(sp, min(stack_limit, sp + 4096), 4):
        if depth >= 64:  # safety limit
            break

        value = read32(addr)
        if value is None:
            continue

        # Check if this value could be a return address (in code region)
        if not (code_start <= value <= code_end):
            continue

        # Verify the instruction before this address is a call
        offset_in_mem = value - memory_base
        if not is_call_instruction(memory, offset_in_mem):
            continue

        # This is a valid return address
        name, func_offset = resolve(value)
        frames.append(
            StackFrame(
                depth=depth,
                stack_addr=addr,
                return_addr=value,
                call_addr=value - 4,  # approximate call site
                func_name=name,
                func_offset=func_offset,
            )
        )
        depth += 1

    return frames


def format_backtrace(frames: list[StackFrame]) -> str:
    """Format a backtrace for display."""
    lines = ["=== Call Stack Backtrace ==="]
    lines.append(f"{'#':>3} {'Stack Addr':>10} {'Return Addr':>10} {'Function':<40} {'Offset':>6}")
    lines.append("-" * 80)

    for frame in frames:
        if frame.depth == 0:
            lines.append(
                f"{frame.depth:>3} {'(crash pc)':>10} "
                f"0x{frame.call_addr:08X} "
                f"{frame.func_name:<40} +0x{frame.func_offset:X}"
            )
        else:
            lines.append(
                f"{frame.depth:>3} 0x{frame.stack_addr:08X} "
                f"0x{frame.return_addr:08X} "
                f"{frame.func_name:<40} +0x{frame.func_offset:X}"
            )

    lines.append("=" * 80)
    return "\n".join(lines)


# ---- Standalone test ----
if __name__ == "__main__":
    print("ARM Thumb-2 Backtrace Module")
    print("Usage: import from ramdump_analyzer.py")
