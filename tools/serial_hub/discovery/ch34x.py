#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CH340 / CH341 / CH343 / CH347 系列 USB 转串口。

认法：VID 固定 0x1A86，PID 按型号；再补描述关键字兜住驱动改名的情形。
"""
from __future__ import annotations


from discovery.base import PortRule

VENDOR = 0x1A86
PIDS = (
    0x7523,   # CH340 / CH341（最常见）
    0x5523,   # CH341 另一模式
    0x55D4,   # CH9101/CH9102 等
    0x7522,   # CH340K
    0x55D3,   # CH343
)

RULES = (
    PortRule(
        name="ch34x",
        label="CH34x 系列 USB 转串口",
        priority=50,
        vid_pids=tuple((VENDOR, pid) for pid in PIDS),
        description_keywords=("ch340", "ch341", "ch343", "ch347", "ch910"),
        hwid_keywords=("VID_1A86",),
    ),
)
