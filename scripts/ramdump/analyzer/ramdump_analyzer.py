#!/usr/bin/env python3
"""
ramdump_analyzer.py -- Main analysis script for RT-Thread RAM dump images.

Loads memory dumps (SRAM.bin, CCM.bin, exception_record.bin) produced by
the ramdump firmware component, resolves symbols from an ELF file, and
generates a comprehensive crash analysis report.

Usage:
    python ramdump_analyzer.py \\
        --sram SRAM.bin \\
        --ccm CCM.bin \\
        --exception exception_record.bin \\
        --elf rtthread.elf \\
        --output report.html

Requirements:
    pip install pyelftools numpy
"""

# __pycache__ 统一写到仓库的 out/pycache（sys.pycache_prefix 只影响设置之后的 import，
# 所以要在所有本地 import 之前，但又必须在 from __future__ 之后）。
import os as _os, sys as _sys

_d = _os.path.abspath(__file__)
while _d != _os.path.dirname(_d) and not _os.path.exists(_os.path.join(_d, ".git")):
    _d = _os.path.dirname(_d)
_sys.pycache_prefix = _os.path.join(_d, "out", "pycache")

import argparse
import struct
import sys
import os
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime

# Optional imports
try:
    from elftools.elf.elffile import ELFFile

    HAS_ELFTOOLS = True
except ImportError:
    HAS_ELFTOOLS = False

from exception_decoder import decode_fault_registers, get_fault_summary, decode_cfsr, decode_hfsr
from arm_backtrace import RegisterSnapshot, backtrace, format_backtrace, StackFrame
from rtthread_parser import ThreadInfo, scan_threads, format_thread_list, compute_stack_usage


# ---- Constants ----

# STM32F407 memory layout
SRAM_BASE = 0x20000000
SRAM_SIZE = 128 * 1024
CCM_BASE = 0x10000000
CCM_SIZE = 64 * 1024
FLASH_BASE = 0x08000000
FLASH_SIZE = 1024 * 1024

# Exception record magic
EXCEPTION_MAGIC = 0x52414D44  # "RAMD"

# Struct layout (from ramdump_exception.h):
#   9 x uint32_t (36 bytes) + char[8] (8 bytes) + 2 x uint32_t (8 bytes) = 52 bytes
EXCEPTION_STRUCT_FORMAT = "<9I8sII"

# RT-Thread constants
RT_NAME_MAX = 8

FAULT_NAMES = {
    0: "HardFault",
    1: "MemManage",
    2: "BusFault",
    3: "UsageFault",
    4: "Assert",
}


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
    registers: Optional[RegisterSnapshot] = None

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
    backtrace: List[StackFrame]
    threads: List[ThreadInfo]
    sram_path: str
    ccm_path: str
    elf_path: str
    symbols: Dict[int, str] = field(default_factory=dict)


def load_memory(path: str) -> Optional[bytes]:
    """Load a binary memory dump file."""
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


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


def load_elf_symbols(elf_path: str) -> Dict[int, str]:
    """Extract function symbols from an ELF file."""
    symbols = {}
    if not HAS_ELFTOOLS:
        print("Warning: pyelftools not installed. Symbol resolution disabled.")
        return symbols

    try:
        with open(elf_path, "rb") as f:
            elf = ELFFile(f)

            # Get .text section bounds
            text_section = elf.get_section_by_name(".text")
            if text_section:
                code_start = text_section["sh_addr"]
                code_end = code_start + text_section["sh_size"]

            # Extract symbols from symbol table
            symtab = elf.get_section_by_name(".symtab")
            if symtab is None:
                print("Warning: No .symtab section in ELF file.")
                return symbols

            for symbol in symtab.iter_symbols():
                if symbol["st_info"]["type"] == "STT_FUNC":
                    name = symbol.name
                    addr = symbol["st_value"]
                    if addr > 0:
                        symbols[addr] = name

            print(f"Loaded {len(symbols)} function symbols from {elf_path}")
    except Exception as e:
        print(f"Error loading ELF symbols: {e}")

    return symbols


def build_memory_map(sram_data: Optional[bytes], ccm_data: Optional[bytes]) -> Tuple[bytes, int]:
    """Build a unified memory map from SRAM and CCM dumps.

    Returns (memory_bytes, memory_base_address).
    Since SRAM and CCM are at different base addresses, we create
    a merged view.
    """
    # For simplicity, use SRAM as primary and CCM as secondary
    # A more sophisticated approach would create a sparse address space
    memory = bytearray(SRAM_SIZE + CCM_SIZE)
    memory_base = SRAM_BASE

    if sram_data:
        copy_len = min(len(sram_data), SRAM_SIZE)
        memory[:copy_len] = sram_data[:copy_len]

    if ccm_data:
        ccm_offset = CCM_BASE - SRAM_BASE
        copy_len = min(len(ccm_data), CCM_SIZE)
        end = min(ccm_offset + copy_len, len(memory))
        memory[ccm_offset:end] = ccm_data[: end - ccm_offset]

    return bytes(memory), memory_base


def analyze_registers(memory: bytes, memory_base: int, hw_frame_ptr: int) -> Optional[RegisterSnapshot]:
    """Extract hardware exception frame registers from memory."""
    if hw_frame_ptr == 0:
        return None

    offset = hw_frame_ptr - memory_base
    if offset < 0 or offset + 32 > len(memory):
        return None

    return RegisterSnapshot.from_bytes(memory[offset : offset + 32])


def generate_html_report(analysis: RamdumpAnalysis) -> str:
    """Generate an HTML analysis report."""
    fault_summary = get_fault_summary(analysis.exception.cfsr, analysis.exception.hfsr)

    backtrace_html = "<pre>" + format_backtrace(analysis.backtrace) + "</pre>"

    # Thread table
    thread_rows = ""
    for t in analysis.threads:
        thread_rows += (
            f"<tr>"
            f"<td>{t.name}</td>"
            f"<td><code>0x{t.sp:08X}</code></td>"
            f"<td><code>0x{t.stack_addr:08X}</code></td>"
            f"<td>{t.stack_size}</td>"
            f"<td>{t.priority}</td>"
            f"<td>{t.state_name}</td>"
            f"</tr>\n"
        )

    e = analysis.exception

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>RAM Dump Analysis Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         max-width: 1100px; margin: 20px auto; padding: 0 20px;
         background: #f5f5f5; color: #333; }}
  h1 {{ color: #c0392b; border-bottom: 3px solid #c0392b; padding-bottom: 10px; }}
  h2 {{ color: #2c3e50; border-bottom: 2px solid #bdc3c7; padding-bottom: 5px; margin-top: 30px; }}
  .card {{ background: white; border-radius: 8px; padding: 20px; margin: 15px 0;
           box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
  .fault-box {{ background: #ffeaa7; border-left: 4px solid #fdcb6e; padding: 12px 16px;
                border-radius: 4px; margin: 10px 0; }}
  .error-box {{ background: #fab1a0; border-left: 4px solid #e17055; padding: 12px 16px;
                border-radius: 4px; margin: 10px 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
  th {{ background: #2c3e50; color: white; padding: 8px 12px; text-align: left; }}
  td {{ padding: 6px 12px; border-bottom: 1px solid #ddd; }}
  tr:hover {{ background: #f8f9fa; }}
  pre {{ background: #2d3436; color: #dfe6e9; padding: 15px; border-radius: 6px;
         overflow-x: auto; font-size: 13px; line-height: 1.5; }}
  code {{ background: #dfe6e9; padding: 1px 4px; border-radius: 3px; font-size: 90%; }}
  .meta {{ color: #636e72; font-size: 14px; }}
  .footer {{ margin-top: 40px; padding-top: 10px; border-top: 1px solid #ddd;
             color: #b2bec3; font-size: 12px; text-align: center; }}
</style>
</head>
<body>

<h1> RAM Dump Analysis Report</h1>

<div class="meta">
  <p>Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
  <p>SRAM: {os.path.basename(analysis.sram_path) if analysis.sram_path else "N/A"}
     | CCM: {os.path.basename(analysis.ccm_path) if analysis.ccm_path else "N/A"}
     | ELF: {os.path.basename(analysis.elf_path) if analysis.elf_path else "N/A"}</p>
</div>

<!-- Fault Summary -->
<h2> Fault Summary</h2>
<div class="card">
  <div class="error-box">
    <strong>Fault Type:</strong> {e.fault_name}<br>
    <strong>Summary:</strong> {fault_summary}<br>
    <strong>Thread:</strong> {e.thread_name} (tick: {e.tick})<br>
    <strong>PC:</strong> <code>0x{e.registers.pc:08X}</code>
    {" (" + analysis.symbols.get(e.registers.pc, "unknown") + ")" if e.registers else ""}
  </div>

  <table>
    <tr><th>Register</th><th>Value</th><th>Description</th></tr>
    <tr><td>CFSR</td><td><code>0x{e.cfsr:08X}</code></td><td>Configurable Fault Status</td></tr>
    <tr><td>HFSR</td><td><code>0x{e.hfsr:08X}</code></td><td>HardFault Status</td></tr>
    <tr><td>MMFAR</td><td><code>0x{e.mmfar:08X}</code></td><td>MemManage Fault Address</td></tr>
    <tr><td>BFAR</td><td><code>0x{e.bfar:08X}</code></td><td>BusFault Address</td></tr>
    <tr><td>HW Frame</td><td><code>0x{e.hw_frame_ptr:08X}</code></td><td>Hardware stacked frame pointer</td></tr>
    <tr><td>Thread SP</td><td><code>0x{e.current_thread_sp:08X}</code></td><td>Stack pointer at crash</td></tr>
  </table>
</div>

<!-- Fault Decode -->
<h2> SCB Register Decode</h2>
<div class="card">
  <pre>{decode_fault_registers(e.cfsr, e.hfsr, e.mmfar, e.bfar)}</pre>
</div>

<!-- Call Stack -->
<h2> Call Stack Backtrace</h2>
<div class="card">
  {backtrace_html}
</div>

<!-- Thread List -->
<h2> Thread List</h2>
<div class="card">
  <table>
    <tr>
      <th>Name</th><th>SP</th><th>Stack Base</th>
      <th>Stack Size</th><th>Priority</th><th>State</th>
    </tr>
    {thread_rows}
  </table>
</div>

<div class="footer">
  RT-Thread Ramdump Analyzer &mdash; Generated report
</div>

</body>
</html>"""

    return html


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze RT-Thread RAM dump images",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ramdump_analyzer.py --sram SRAM.bin --ccm CCM.bin --elf rtthread.elf
  python ramdump_analyzer.py --sram SRAM.bin --elf rtthread.elf --output report.html
  python ramdump_analyzer.py --sram SRAM.bin --exception exception_record.bin --text
        """,
    )

    parser.add_argument("--sram", "-s", help="SRAM.bin dump file (128KB)")
    parser.add_argument("--ccm", "-c", help="CCM.bin dump file (64KB)")
    parser.add_argument("--flash", "-f", help="Flash dump file (1MB, optional)")
    parser.add_argument("--exception", "-e", help="exception_record.bin file")
    parser.add_argument("--elf", "-l", help="ELF file with debug symbols")
    parser.add_argument("--output", "-o", help="Output HTML report file path")
    parser.add_argument("--text", "-t", action="store_true", help="Output plain text report to stdout")
    parser.add_argument(
        "--object-start",
        type=lambda x: int(x, 0),
        default=SRAM_BASE,
        help="Start address for thread scan (default: SRAM base)",
    )
    parser.add_argument(
        "--object-end",
        type=lambda x: int(x, 0),
        default=SRAM_BASE + SRAM_SIZE,
        help="End address for thread scan (default: SRAM end)",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    # Load memory dumps
    sram_data = load_memory(args.sram)
    ccm_data = load_memory(args.ccm)
    exc_data = load_memory(args.exception)

    if not sram_data:
        print("Error: SRAM dump (--sram) is required.")
        sys.exit(1)

    print(f"SRAM: {len(sram_data)} bytes")
    if ccm_data:
        print(f"CCM:  {len(ccm_data)} bytes")

    # Build unified memory map
    memory, memory_base = build_memory_map(sram_data, ccm_data)
    print(f"Memory map: 0x{memory_base:08X} - 0x{memory_base + len(memory):08X} ({len(memory)} bytes)")

    # Parse exception record
    exception = ExceptionRecord(valid=False)
    if exc_data:
        exception = parse_exception_record(exc_data)
        print(f"Exception record: {'valid' if exception.valid else 'invalid'}")

    # Load ELF symbols
    symbols = {}
    code_start = FLASH_BASE
    code_end = FLASH_BASE + FLASH_SIZE

    if args.elf and HAS_ELFTOOLS:
        symbols = load_elf_symbols(args.elf)
        # Try to get actual code section bounds from ELF
        try:
            with open(args.elf, "rb") as f:
                elf = ELFFile(f)
                text = elf.get_section_by_name(".text")
                if text:
                    code_start = text["sh_addr"]
                    code_end = code_start + text["sh_size"]
                    print(f".text: 0x{code_start:08X} - 0x{code_end:08X}")
        except Exception:
            pass
    elif args.elf and not HAS_ELFTOOLS:
        print("Warning: Install pyelftools for symbol resolution: pip install pyelftools")

    # Extract registers from exception frame
    registers = None
    if exception.valid and exception.hw_frame_ptr:
        registers = analyze_registers(memory, memory_base, exception.hw_frame_ptr)
        exception.registers = registers

    # Perform backtrace
    sp = exception.current_thread_sp if exception.valid else SRAM_BASE + 0x10000
    stack_limit = SRAM_BASE + SRAM_SIZE

    frames = backtrace(memory, memory_base, sp, stack_limit, code_start, code_end, symbols)
    print(f"Backtrace: {len(frames)} frames")

    # Scan for threads (heuristic)
    print(f"Scanning for threads in 0x{args.object_start:08X}..0x{args.object_end:08X}...")
    threads = scan_threads(memory, memory_base, args.object_start, args.object_end)
    print(f"Found {len(threads)} potential threads")

    # Build analysis result
    analysis = RamdumpAnalysis(
        exception=exception,
        fault_decode=decode_fault_registers(exception.cfsr, exception.hfsr, exception.mmfar, exception.bfar),
        backtrace=frames,
        threads=threads,
        sram_path=args.sram or "",
        ccm_path=args.ccm or "",
        elf_path=args.elf or "",
        symbols=symbols,
    )

    # Output
    if args.text or not args.output:
        print("\n" + "=" * 70)
        print(analysis.exception)
        print()
        print(analysis.fault_decode)
        print()
        print(format_backtrace(analysis.backtrace))
        print()
        print(format_thread_list(analysis.threads, memory, memory_base))

    if args.output:
        html = generate_html_report(analysis)
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\nHTML report saved to: {args.output}")


if __name__ == "__main__":
    main()
