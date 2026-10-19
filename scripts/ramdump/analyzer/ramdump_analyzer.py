"""离线解析 ramdump：命令行入口（模型/内存/判定/报告见同目录模块）。"""

from __future__ import annotations

# __pycache__ 统一写到仓库 out/pycache：仓库根由本文件位置直接推出（parents[3]），不做搜索
import sys as _sys
from pathlib import Path as _Path

_sys.pycache_prefix = str(_Path(__file__).resolve().parents[3] / "out" / "pycache")

import argparse  # noqa: E402
import sys  # noqa: E402

try:
    from elftools.elf.elffile import ELFFile

    HAS_ELFTOOLS = True
except ImportError:
    HAS_ELFTOOLS = False

from pathlib import Path  # noqa: E402

from analysis import analyze_registers, parse_exception_record  # noqa: E402
from arm_backtrace import backtrace, format_backtrace  # noqa: E402
from exception_decoder import decode_fault_registers  # noqa: E402
from memory import build_memory_map, load_elf_symbols, load_memory  # noqa: E402
from model import (  # noqa: E402
    FLASH_BASE,
    FLASH_SIZE,
    SRAM_BASE,
    SRAM_SIZE,
    ExceptionRecord,
    RamdumpAnalysis,
)
from report import generate_html_report  # noqa: E402
from rtthread_parser import format_thread_list, scan_threads  # noqa: E402


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
            with Path(args.elf).open("rb") as f:
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
        with Path(args.output).open("w", encoding="utf-8") as f:
            f.write(html)
        print(f"\nHTML report saved to: {args.output}")


if __name__ == "__main__":
    main()
