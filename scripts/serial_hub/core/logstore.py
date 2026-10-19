#!/usr/bin/env python3
"""日志的格式与落盘原语。

esc(data)                字节 -> 可读文本（除 \n 外全转义，别把终端搞乱）
hexdump_text(data, off)  两栏 hex 视图的一行行文本（每 8 字节一个空档）
sync(f)                  flush + fsync（Windows 上不 fsync，别的进程看不到新内容）
"""

from __future__ import annotations

import os


def esc(data: bytes) -> str:
    """把字节流转成可读文本；除 \\n 外都转义，避免把终端搞乱。"""
    out = []
    for b in data:
        if b == 0x0A:
            out.append("\n")
        elif b == 0x0D:
            out.append("\\r")
        elif b == 0x09:
            out.append("\\t")
        elif 32 <= b < 127:
            out.append(chr(b))
        else:
            out.append(f"\\x{b:02x}")
    return "".join(out)


def hexdump_text(data: bytes, off: int, tag: str = "") -> tuple[str, int]:
    """经典两栏 hex 视图：offset + 16 字节 hex（每 8 字节一个空档）+ ASCII。

    返回 (文本, 新的偏移量)。纯函数，方便离线测。
    """
    cols = 16
    rows = []
    for i in range(0, len(data), cols):
        piece = data[i : i + cols]
        left = (" ".join(f"{b:02x}" for b in piece[:8]) + " ").ljust(8 * 3)
        right = (" ".join(f"{b:02x}" for b in piece[8:]) + " ").ljust(8 * 3)
        hexs = left + " " + right
        asc = "".join(chr(b) if 32 <= b < 127 else "." for b in piece)
        rows.append(f"{tag}{off + i:08x}  {hexs} |{asc}|")
    return "\n".join(rows), off + len(data)


def sync(f) -> None:
    """把已写数据推到操作系统。

    Windows 上只 flush 的话，别进程读文件大小时仍看到旧值（实测：hub 运行中 tail 到 0 B，
    进程退出后才变正常），所以这里再 fsync 一次。
    """
    try:
        f.flush()
        os.fsync(f.fileno())
    except Exception:
        pass
