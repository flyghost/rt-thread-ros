#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ANSI 小工具：VT 模式、光标/颜色控制、按「显示宽度」对齐（中文算 2 列）。

零依赖：只用 ANSI 转义序列 + ctypes 打开 Windows 控制台的 VT 处理能力。
其它 UI（别的前端）可以完全不用这个文件。
"""

from __future__ import annotations

import re
import shutil
import sys
import unicodedata

CSI = "\x1b["
RESET = CSI + "0m"
BOLD = CSI + "1m"
DIM = CSI + "2m"
REVERSE = CSI + "7m"
FG_RED = CSI + "31m"
FG_GREEN = CSI + "32m"
FG_YELLOW = CSI + "33m"
FG_BLUE = CSI + "34m"
FG_CYAN = CSI + "36m"
FG_GREY = CSI + "90m"
BG_BLUE = CSI + "44m"
BG_RED = CSI + "41m"
BG_YELLOW = CSI + "43m"
BG_CYAN = CSI + "46m"

CLEAR = CSI + "2J"
HOME = CSI + "H"
CLR_EOL = CSI + "K"
HIDE_CURSOR = CSI + "?25l"
SHOW_CURSOR = CSI + "?25h"
ALT_ON = CSI + "?1049h"
ALT_OFF = CSI + "?1049l"

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    """去掉转义序列（测试要把渲染结果按显示宽度量一遍）。"""
    return _ANSI_RE.sub("", text)


def enable_vt() -> bool:
    """打开本进程控制台的 VT 处理（Windows 必须；其它平台恒真）。"""
    if sys.platform != "win32":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        enable_vt_flag = 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        if mode.value & enable_vt_flag:
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | enable_vt_flag))
    except Exception:
        return False


def term_size(default=(100, 30)):
    try:
        size = shutil.get_terminal_size(fallback=default)
        w, h = int(size.columns), int(size.lines)
    except Exception:
        w, h = default
    return max(20, w), max(5, h)


def char_width(ch: str) -> int:
    if ch == "\t":
        return 1
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def width(text: str) -> int:
    """可见宽度（已去掉 ANSI 序列）。"""
    return sum(char_width(ch) for ch in strip_ansi(text))


def truncate(text: str, cols: int) -> str:
    """按显示宽度截断（保留 ANSI 序列，序号在截断处补 RESET）。"""
    if cols <= 0:
        return ""
    out = []
    used = 0
    i = 0
    while i < len(text):
        m = _ANSI_RE.match(text, i)
        if m:
            out.append(m.group(0))
            i = m.end()
            continue
        ch = text[i]
        cw = char_width(ch)
        if used + cw > cols:
            break
        out.append(ch)
        used += cw
        i += 1
    return "".join(out) + (RESET if used < width(text) else "")


def pad(text: str, cols: int, fill: str = " ") -> str:
    """补空格到指定显示宽度（超宽不截断，交给 truncate）。"""
    return text + fill * max(0, cols - width(text))


def fit(text: str, cols: int, fill: str = " ") -> str:
    return pad(truncate(text, cols), cols, fill)


def at(row: int, col: int) -> str:
    return "%s%d;%dH" % (CSI, row, col)
