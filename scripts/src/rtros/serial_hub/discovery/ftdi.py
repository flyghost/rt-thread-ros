#!/usr/bin/env python3
"""FTDI FT232 / FT2232 / FT4232 系列 USB 转串口。"""

from __future__ import annotations

from rtros.serial_hub.discovery.base import PortRule

VENDOR = 0x0403
PIDS = (
    0x6001,  # FT232R / FT245R
    0x6010,  # FT2232
    0x6011,  # FT4232
    0x6014,  # FT232H
    0x6015,  # FT231X / FT230X
    0x6048,  # FT4232H
)

RULES = (
    PortRule(
        name="ftdi",
        label="FTDI 系列 USB 转串口",
        priority=50,
        vid_pids=tuple((VENDOR, pid) for pid in PIDS),
        description_keywords=("ft232", "ft231", "ft2232", "ft4232", "ftdi"),
        hwid_keywords=("VID_0403",),
    ),
)
