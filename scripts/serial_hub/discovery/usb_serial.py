#!/usr/bin/env python3
"""兜底规则：任何"看起来挂在 USB 上"的串口。

放在最后、priority 最低 —— 只在没有任何具体家族规则命中时才起作用，
用来支持"机器上只有一个 USB 转串口就直接用它"这种常见情形。
虚拟串口对、蓝牙 SPP 端口一般不带 USB 标记，因此不会被它选中。
"""

from __future__ import annotations

from discovery.base import PortRule

RULES = (
    PortRule(
        name="usb-serial",
        label="任意 USB 串口（兜底）",
        priority=10,
        hwid_keywords=("USB",),
    ),
)
