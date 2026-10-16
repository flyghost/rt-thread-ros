#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端口探测：枚举候选串口、按规则分类、挑出首选端口。

规则表 = 本目录下各家族模块暴露的 ``RULES`` + 调用方临时追加的规则（例如命令行 ``--prefer``）。
**加一个新家族 = 在本目录新建一个 .py，暴露 RULES，再到下面 import 登记**，别的文件都不用改。

三个对外函数：
    scan()                     -> [PortInfo, ...]                     枚举（不去重、不挑）
    classify(port, rules)      -> (PortRule|None, 命中理由)           单个端口是什么
    preferred(ports, rules)    -> (PortInfo, PortRule, 理由) | (None, None, 原因)
    print_ports_table(ports, rules)                                   给人看的表格
"""
from __future__ import annotations


from discovery import ch34x, cp210x, ftdi, usb_serial
from discovery.base import (MATCH_NONE, PortInfo, PortRule, order_key,  # noqa: F401
                            parse_rule_spec)

# 内置规则（顺序无关，判定靠"命中强度 + priority"）
BUILTIN_RULES: tuple[PortRule, ...] = (
    tuple(ch34x.RULES) + tuple(cp210x.RULES) + tuple(ftdi.RULES) + tuple(usb_serial.RULES)
)


def all_rules(extra=()) -> tuple:
    """内置规则 + 调用方追加的规则（追加的 priority 更高，用于"我点名要这个"）。"""
    return tuple(BUILTIN_RULES) + tuple(extra or ())


def scan() -> list:
    """枚举当前机器上的串口（pyserial 的 comports()）。"""
    from serial.tools import list_ports
    return [PortInfo.from_pyserial(p) for p in list_ports.comports()]


def classify(port: PortInfo, rules=()) -> tuple:
    """判断单个端口命中哪条规则，返回 (PortRule|None, 理由)。"""
    best = None
    for rule in all_rules(rules):
        strength, why = rule.match(port)
        if strength == MATCH_NONE:
            continue
        key = order_key(rule, strength)
        if best is None or key < best[0]:
            best = (key, rule, why)
    if best is None:
        return None, ""
    return best[1], best[2]


def preferred(ports=None, rules=(), require_usb: bool = True) -> tuple:
    """挑一个首选端口。

    返回 ``(PortInfo, PortRule, 理由)``；挑不出来时返回 ``(None, None, 原因)`` ——
    原因是要给用户看的（"没有发现任何串口" / "有 3 个端口同级，请用 --com 指定"）。
    ``require_usb=False`` 允许把虚拟串口/蓝牙端口也算候选（用户点名时用）。
    """
    ports = scan() if ports is None else list(ports)
    if not ports:
        return None, None, "没有发现任何串口"
    rows = []
    for p in ports:
        rule, why = classify(p, rules)
        if rule is None:
            continue
        if require_usb and not p.is_usb:
            continue
        rows.append((rule.priority, p, rule, why))
    if not rows:
        return None, None, "没有端口命中任何规则"
    top_pri = max(x[0] for x in rows)
    top = [x for x in rows if x[0] == top_pri]
    if len(top) == 1:
        _, port, rule, why = top[0]
        return port, rule, why
    return None, None, "有 %d 个端口同级命中（%s），请用 --com 指定" % (
        len(top), "、".join(p.brief() for _, p, _, _ in top))


def print_ports_table(ports=None, rules=(), picked=None) -> None:
    """打印候选端口表；``picked`` 是首选端口名，会打上标记。"""
    ports = scan() if ports is None else list(ports)
    if not ports:
        print("没有发现任何串口")
        return
    print("可用串口：")
    for p in ports:
        rule, why = classify(p, rules)
        mark = "  <== 自动选中" if picked and p.device == picked else ""
        print("  %-10s %-38s %-9s %-22s %s%s"
              % (p.device, (p.description or "-")[:38], p.vidpid,
                 (rule.label or rule.name) if rule else "-", why, mark))


def print_rules(rules=()) -> None:
    """打印规则表，方便用户知道"什么样的端口会被自动选中"以及怎么加规则。"""
    print("探测规则（命中强度：VID:PID > 硬件ID > 描述 > 串口名；同级比 priority）：")
    for rule in all_rules(rules):
        bits = []
        if rule.vid_pids:
            bits.append("VID:PID=" + ",".join("%04X:%04X" % vp for vp in rule.vid_pids))
        if rule.hwid_keywords:
            bits.append("硬件ID含 " + "/".join(rule.hwid_keywords))
        if rule.description_keywords:
            bits.append("描述含 " + "/".join(rule.description_keywords))
        if rule.device_patterns:
            bits.append("串口名 " + "/".join(rule.device_patterns))
        print("  %-12s priority=%-4d %s" % (rule.name, rule.priority, "；".join(bits) or "-"))
    print("  加规则：在 discovery/ 下新建一个 .py 暴露 RULES；临时用 --prefer 1A86:7523 / "
          "--prefer name:COM7 / --prefer desc:ch340 / --prefer hwid:USB")
