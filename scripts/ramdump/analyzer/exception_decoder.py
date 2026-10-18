#!/usr/bin/env python3
"""
exception_decoder.py -- ARM Cortex-M SCB register exception decoder.

Decodes CFSR (Configurable Fault Status Register), HFSR (HardFault Status
Register), MMFAR, and BFAR register values from ramdump exception records.
"""

from dataclasses import dataclass
from typing import List, Tuple


# ---- CFSR Bit Definitions ----

# MemManage Fault Status Register (MMFSR) -- bits [7:0]
CFSR_MMFSR = {
    0: "IACCVIOL - Instruction access violation",
    1: "DACCVIOL - Data access violation",
    3: "MUNSTKERR - Exception return unstacking error",
    4: "MSTKERR - Exception entry stacking error",
    5: "MLSPERR - FPU lazy state preservation error",
    7: "MMARVALID - MMFAR holds valid fault address",
}

# BusFault Status Register (BFSR) -- bits [15:8]
CFSR_BFSR = {
    8:  "IBUSERR - Instruction bus error",
    9:  "PRECISERR - Precise data bus error",
    10: "IMPRECISERR - Imprecise data bus error",
    11: "UNSTKERR - Exception return unstacking bus error",
    12: "STKERR - Exception entry stacking bus error",
    13: "LSPERR - FPU lazy state preservation bus error",
    15: "BFARVALID - BFAR holds valid fault address",
}

# UsageFault Status Register (UFSR) -- bits [25:16]
CFSR_UFSR = {
    16: "UNDEFINSTR - Undefined instruction",
    17: "INVSTATE - Invalid state (EPSR.T=0 for non-BL/BLX)",
    18: "INVPC - Invalid PC load (EXC_RETURN to non-existent state)",
    19: "NOCP - No coprocessor",
    24: "UNALIGNED - Unaligned access",
    25: "DIVBYZERO - Divide by zero",
}


def decode_cfsr(cfsr: int) -> List[str]:
    """Decode SCB->CFSR value into human-readable fault descriptions."""
    faults = []

    # Check MMFSR (bits 0-7)
    for bit, desc in CFSR_MMFSR.items():
        if cfsr & (1 << bit):
            faults.append(f"[MemManage] {desc}")

    # Check BFSR (bits 8-15)
    for bit, desc in CFSR_BFSR.items():
        if cfsr & (1 << bit):
            faults.append(f"[BusFault] {desc}")

    # Check UFSR (bits 16-25)
    for bit, desc in CFSR_UFSR.items():
        if cfsr & (1 << bit):
            faults.append(f"[UsageFault] {desc}")

    return faults


def decode_hfsr(hfsr: int) -> List[str]:
    """Decode SCB->HFSR value."""
    faults = []

    if hfsr & (1 << 1):
        faults.append("VECTBL - Hard fault from failed vector fetch")
    if hfsr & (1 << 30):
        faults.append("FORCED - Escalated from MemManage/BusFault/UsageFault")
    if hfsr & (1 << 31):
        faults.append("DEBUGEVT - Hard fault from debug event")

    return faults


def decode_fault_registers(cfsr: int, hfsr: int,
                           mmfar: int, bfar: int) -> str:
    """Decode all SCB fault registers and return a formatted string."""
    lines = []
    lines.append("=== ARM Cortex-M Fault Decode ===")
    lines.append(f"CFSR  = 0x{cfsr:08X}")
    lines.append(f"HFSR  = 0x{hfsr:08X}")
    lines.append(f"MMFAR = 0x{mmfar:08X} (MemManage fault address)")
    lines.append(f"BFAR  = 0x{bfar:08X} (BusFault address)")
    lines.append("")

    cfsr_decoded = decode_cfsr(cfsr)
    hfsr_decoded = decode_hfsr(hfsr)

    if cfsr_decoded:
        lines.append("CFSR Decoded:")
        for fault in cfsr_decoded:
            lines.append(f"  {fault}")
    else:
        lines.append("CFSR Decoded: (no configurable faults)")

    if hfsr_decoded:
        lines.append("HFSR Decoded:")
        for fault in hfsr_decoded:
            lines.append(f"  {fault}")

    return "\n".join(lines)


def get_fault_summary(cfsr: int, hfsr: int) -> str:
    """Return a one-line summary of the fault type."""
    if hfsr & (1 << 30):
        # FORCED -- check what escalated
        if cfsr & 0xFF:
            return "BusFault escalated to HardFault"
        if cfsr & 0xFF00:
            return "MemManage fault escalated to HardFault"
        if cfsr & 0xFFFF0000:
            return "UsageFault escalated to HardFault"
        return "Escalated HardFault (unknown cause)"
    elif hfsr & (1 << 1):
        return "HardFault: Vector fetch error"
    elif hfsr & (1 << 31):
        return "HardFault: Debug event"
    else:
        return "HardFault: Unknown cause"


# ---- Standalone test ----
if __name__ == "__main__":
    # Example: BusFault escalated to HardFault (PRECISERR)
    test_cfsr = 0x00008200
    test_hfsr = 0x40000000
    print(decode_fault_registers(test_cfsr, test_hfsr, 0, 0xFFFFFFFF))
    print(f"\nSummary: {get_fault_summary(test_cfsr, test_hfsr)}")
