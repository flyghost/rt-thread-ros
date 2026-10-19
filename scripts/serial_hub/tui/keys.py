#!/usr/bin/env python3
"""键盘读取：把按键变成稳定的「token」字符串，UI 只认 token。

token 形式：
    c:<字符>   可打印字符（含中文输入法直接落下的字符）
    enter / tab / backspace / esc / del
    up / down / left / right / home / end / pgup / pgdn
    f1 / f2 ...
    ctrl-a .. ctrl-z
读不到键时返回 ""（非阻塞）。Windows 用 msvcrt；其它平台退回 termios 原始模式。
"""

from __future__ import annotations

import sys

_SPECIAL = {
    "H": "up",
    "P": "down",
    "K": "left",
    "M": "right",
    "G": "home",
    "O": "end",
    "I": "pgup",
    "Q": "pgdn",
    "S": "del",
    ";": "f1",
    "<": "f2",
    "=": "f3",
    ">": "f4",
    "?": "f5",
    "@": "f6",
    "A": "f7",
    "B": "f8",
    "C": "f9",
    "D": "f10",
    "R": "insert",
    "s": "ctrl-end",
    "t": "ctrl-pgdn",
}

_CTRL = {
    "\x01": "ctrl-a",
    "\x02": "ctrl-b",
    "\x03": "ctrl-c",
    "\x04": "ctrl-d",
    "\x05": "ctrl-e",
    "\x06": "ctrl-f",
    "\x07": "ctrl-g",
    "\x08": "backspace",
    "\x09": "tab",
    "\x0a": "enter",
    "\x0c": "ctrl-l",
    "\x0d": "enter",
    "\x0e": "ctrl-n",
    "\x10": "ctrl-p",
    "\x11": "ctrl-q",
    "\x12": "ctrl-r",
    "\x13": "ctrl-s",
    "\x14": "ctrl-t",
    "\x15": "ctrl-u",
    "\x16": "ctrl-v",
    "\x17": "ctrl-w",
    "\x18": "ctrl-x",
    "\x19": "ctrl-y",
    "\x1a": "ctrl-z",
    "\x1b": "esc",
    "\x7f": "backspace",
}


def _win():
    import msvcrt

    return msvcrt


def _posix_setup():
    """把 stdin 切成非阻塞原始模式；返回还原函数。"""
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    tty.setcbreak(fd)
    return lambda: termios.tcsetattr(fd, termios.TCSADRAIN, old)


def read_key() -> str:
    """非阻塞读一个键；没有按键时返回 ""。"""
    if sys.platform == "win32":
        msvcrt = _win()
        if not msvcrt.kbhit():
            return ""
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):  # 功能键/方向键前缀
            if not msvcrt.kbhit():
                return ""
            return _SPECIAL.get(msvcrt.getwch(), "")
        if ch in _CTRL:
            return _CTRL[ch]
        return "c:" + ch

    import os
    import select

    if not select.select([sys.stdin], [], [], 0)[0]:
        return ""
    ch = os.read(sys.stdin.fileno(), 1).decode("utf-8", "replace")
    if not ch:
        return ""
    if ch == "\x1b":  # 方向键：ESC [ A ..
        seq = ""
        while select.select([sys.stdin], [], [], 0.01)[0] and len(seq) < 4:
            seq += os.read(sys.stdin.fileno(), 1).decode("utf-8", "replace")
        return {
            "[A": "up",
            "[B": "down",
            "[C": "right",
            "[D": "left",
            "[H": "home",
            "[F": "end",
            "[5~": "pgup",
            "[6~": "pgdn",
            "[2~": "insert",
            "[3~": "del",
        }.get(seq, "esc")
    if ch in _CTRL:
        return _CTRL[ch]
    return "c:" + ch


def setup_terminal():
    """进入 UI 前的终端准备，返回还原函数。"""
    if sys.platform == "win32":
        return lambda: None
    try:
        return _posix_setup()
    except Exception:
        return lambda: None
