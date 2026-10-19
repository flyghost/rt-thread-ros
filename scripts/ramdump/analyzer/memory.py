"""内存与符号：读内存镜像、从 ELF 取符号表、把记录地址映射到区域。"""

from __future__ import annotations

import os

# Optional imports
from pathlib import Path

try:
    from elftools.elf.elffile import ELFFile

    HAS_ELFTOOLS = True
except ImportError:  # 未安装 pyelftools 时退化成「无符号表」模式
    HAS_ELFTOOLS = False

from model import CCM_BASE, CCM_SIZE, SRAM_BASE, SRAM_SIZE


def load_memory(path: str) -> bytes | None:
    """Load a binary memory dump file."""
    if not path or not os.path.exists(path):
        return None
    with Path(path).open("rb") as f:
        return f.read()


def load_elf_symbols(elf_path: str) -> dict[int, str]:
    """Extract function symbols from an ELF file."""
    symbols: dict[int, str] = {}
    if not HAS_ELFTOOLS:
        print("Warning: pyelftools not installed. Symbol resolution disabled.")
        return symbols

    try:
        with Path(elf_path).open("rb") as f:
            elf = ELFFile(f)

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


def build_memory_map(sram_data: bytes | None, ccm_data: bytes | None) -> tuple[bytes, int]:
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
