#!/usr/bin/env python3
"""串口枚举与首选端口的编排层。

这里**只做枚举、选取、打印**，不含任何厂商/型号知识 —— "什么样的端口算哪一类"
全部由 `discovery/` 下的规则表决定（VID:PID、串口名 glob、描述关键字、硬件 ID 关键字）。
"""

from __future__ import annotations

import sys

from discovery import (
    preferred,
    print_ports_table,
    scan,
)


def candidate_ports():
    """返回 [PortInfo, ...]。"""
    return scan()


def print_ports(rules=()) -> None:
    """打印候选串口表；顺带标出按当前规则会自动选中的那个。"""
    ports = scan()
    port, _, _ = preferred(ports, rules, require_usb=not rules)
    print_ports_table(ports, rules, picked=port.device if port else None)


def autodetect_port(rules=()) -> str | None:
    """按规则表挑一个端口；挑不出来时把原因打到 stderr（要人来指定 --com）。"""
    port, rule, why = preferred(rules=rules, require_usb=not rules)
    if port is None:
        print(f"[hub] 自动选择失败：{why}", file=sys.stderr)
        return None
    print(f"[hub] 自动选中 {port.brief()}（{rule.label or rule.name}：{why}）")
    return port.device
