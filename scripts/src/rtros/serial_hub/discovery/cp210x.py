#!/usr/bin/env python3
"""Silicon Labs CP210x 系列 USB 转串口。"""

from __future__ import annotations

from rtros.serial_hub.discovery.base import PortRule

VENDOR = 0x10C4
PIDS = (
    0xEA60,  # CP2102 / CP2104
    0xEA70,  # CP2105
    0xEA71,  # CP2108
)

RULES = (
    PortRule(
        name="cp210x",
        label="CP210x 系列 USB 转串口",
        priority=50,
        vid_pids=tuple((VENDOR, pid) for pid in PIDS),
        description_keywords=("cp210",),
        hwid_keywords=("VID_10C4",),
    ),
)
