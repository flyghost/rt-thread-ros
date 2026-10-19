"""解析与判定：把异常记录字节解成结构体，并给出故障解读。"""

from __future__ import annotations

import struct

# Optional imports
from arm_backtrace import RegisterSnapshot
from model import EXCEPTION_MAGIC, FAULT_NAMES, ExceptionRecord


def parse_exception_record(data: bytes) -> ExceptionRecord:
    """Parse the exception_record.bin file."""
    if len(data) < 52:
        return ExceptionRecord(valid=False)

    # Unpack the struct: 9 x uint32_t + 8-byte char array + 2 x uint32_t = 52 bytes
    fmt = "<9I8sII"
    try:
        fields = struct.unpack(fmt, data[:52])
    except struct.error:
        return ExceptionRecord(valid=False)

    magic = fields[0]
    if magic != EXCEPTION_MAGIC:
        return ExceptionRecord(valid=False)

    fault_type = fields[1]
    cfsr = fields[2]
    hfsr = fields[3]
    mmfar = fields[4]
    bfar = fields[5]
    fpscr = fields[6]
    hw_frame_ptr = fields[7]
    current_thread_sp = fields[8]
    thread_name_bytes = fields[9]
    tick = fields[10]
    checksum = fields[11]

    # Verify checksum: XOR all fields except checksum.
    # Thread name is treated as 2 uint32s (little-endian).
    calc_sum = 0
    for i in range(9):  # first 9 uint32 fields
        calc_sum ^= fields[i]
    tn1 = struct.unpack("<I", thread_name_bytes[:4])[0]
    tn2 = struct.unpack("<I", thread_name_bytes[4:])[0]
    calc_sum ^= tn1 ^ tn2 ^ tick

    valid = calc_sum == checksum

    # Decode thread name
    thread_name = thread_name_bytes.split(b"\x00")[0].decode("ascii", errors="replace")

    return ExceptionRecord(
        valid=valid,
        fault_type=fault_type,
        fault_name=FAULT_NAMES.get(fault_type, f"Unknown({fault_type})"),
        cfsr=cfsr,
        hfsr=hfsr,
        mmfar=mmfar,
        bfar=bfar,
        fpscr=fpscr,
        hw_frame_ptr=hw_frame_ptr,
        current_thread_sp=current_thread_sp,
        thread_name=thread_name,
        tick=tick,
    )


def analyze_registers(memory: bytes, memory_base: int, hw_frame_ptr: int) -> RegisterSnapshot | None:
    """Extract hardware exception frame registers from memory."""
    if hw_frame_ptr == 0:
        return None

    offset = hw_frame_ptr - memory_base
    if offset < 0 or offset + 32 > len(memory):
        return None

    return RegisterSnapshot.from_bytes(memory[offset : offset + 32])
