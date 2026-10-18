#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端口探测的两块积木：`PortInfo`（端口事实）与 `PortRule`（判定规则）。

这个模块**不含任何具体厂商知识** —— 具体家族（各 USB 转串口芯片）在 `discovery/` 下
各自一个文件里，靠 `PortRule` 描述自己怎么被认出来。加新家族不用改这里的代码。
"""
from __future__ import annotations


import fnmatch
from dataclasses import dataclass

# 命中强度：同一条规则里，VID:PID 比"名字像"可信得多；跨规则比较时先看强度再看 priority。
MATCH_VIDPID = 400
MATCH_HWID = 300
MATCH_DESC = 200
MATCH_NAME = 100
MATCH_NONE = 0


@dataclass(frozen=True)
class PortInfo:
    """一个候选端口的原始事实（pyserial 能给什么就存什么）。"""

    device: str
    description: str = ""
    hwid: str = ""
    vid: int | None = None
    pid: int | None = None
    serial_number: str | None = None
    manufacturer: str | None = None
    product: str | None = None
    location: str | None = None

    @classmethod
    def from_pyserial(cls, p) -> "PortInfo":
        g = lambda k: getattr(p, k, None)          # noqa: E731
        return cls(
            device=str(g("device") or ""),
            description=str(g("description") or ""),
            hwid=str(g("hwid") or ""),
            vid=g("vid"),
            pid=g("pid"),
            serial_number=g("serial_number"),
            manufacturer=g("manufacturer"),
            product=g("product"),
            location=g("location"),
        )

    @property
    def vidpid(self) -> str:
        if self.vid is None or self.pid is None:
            return "----:----"
        return "%04X:%04X" % (self.vid, self.pid)

    @property
    def is_usb(self) -> bool:
        """是不是挂在 USB 上的（虚拟串口 / 蓝牙 SPP 一般都不是）。"""
        if self.vid is not None or self.pid is not None:
            return True
        return "USB" in (self.hwid or "").upper()

    def brief(self) -> str:
        return "%s (%s)" % (self.device, self.description or "-")


@dataclass(frozen=True)
class PortRule:
    """「什么样的端口算这一类」的判定规则。

    四个维度可任意组合（填了才参与判定）：
      * ``vid_pids``            —— [(0x1A86, 0x7523), ...] 精确 VID:PID
      * ``device_patterns``     —— 串口名的 glob，如 ``("COM7", "ttyUSB*")``
      * ``description_keywords``—— 描述里的关键字（大小写不敏感）
      * ``hwid_keywords``       —— 硬件 ID 里的关键字（大小写不敏感）

    ``priority``：不同端口之间的取舍；数字大的优先被自动选中。同 priority 视为同级歧义。
    """

    name: str
    label: str = ""
    priority: int = 0
    vid_pids: tuple = ()
    device_patterns: tuple = ()
    description_keywords: tuple = ()
    hwid_keywords: tuple = ()

    def match(self, port: PortInfo) -> tuple[int, str]:
        """返回 (命中强度, 命中理由)；不命中返回 (MATCH_NONE, "")。"""
        if port.vid is not None and port.pid is not None and (port.vid, port.pid) in self.vid_pids:
            return MATCH_VIDPID, "VID:PID=%s" % port.vidpid
        up_hwid = (port.hwid or "").upper()
        for kw in self.hwid_keywords:
            if kw.upper() in up_hwid:
                return MATCH_HWID, "硬件ID含 %s" % kw
        low_desc = (port.description or "").lower()
        for kw in self.description_keywords:
            if kw.lower() in low_desc:
                return MATCH_DESC, "描述含 %s" % kw
        for pat in self.device_patterns:
            if fnmatch.fnmatch(port.device.upper(), pat.upper()):
                return MATCH_NAME, "串口名匹配 %s" % pat
        return MATCH_NONE, ""


def order_key(rule: PortRule, strength: int):
    """排序键：先命中强度、再规则 priority、最后规则名（保证结果稳定可复现）。"""
    return (-strength, -rule.priority, rule.name)


def parse_rule_spec(spec: str, priority: int = 100) -> PortRule:
    """把命令行上的 ``--prefer`` 取值解析成一条规则。

    支持四种写法（大小写不敏感）：
        ``1A86:7523``        精确 VID:PID
        ``name:COM7``        串口名（可用 ``*`` 通配）
        ``desc:ch340``       描述关键字
        ``hwid:USB``         硬件 ID 关键字

    用户给的规则 priority 默认 100，高于所有内置规则，即"我点名要的优先"。
    """
    text = (spec or "").strip()
    if not text:
        raise ValueError("空的 --prefer 规则")
    low = text.lower()
    if low.startswith("name:"):
        return PortRule(name="cli-name", label="命令行指定串口名", priority=priority,
                        device_patterns=(text[5:].strip(),))
    if low.startswith("desc:"):
        return PortRule(name="cli-desc", label="命令行指定描述", priority=priority,
                        description_keywords=(text[5:].strip(),))
    if low.startswith("hwid:"):
        return PortRule(name="cli-hwid", label="命令行指定硬件ID", priority=priority,
                        hwid_keywords=(text[5:].strip(),))
    body = text[7:] if low.startswith("vidpid:") else text
    parts = body.replace("-", ":").split(":")
    if len(parts) == 2:
        try:
            return PortRule(name="cli-vidpid", label="命令行指定 VID:PID", priority=priority,
                            vid_pids=((int(parts[0], 16), int(parts[1], 16)),))
        except ValueError:
            raise ValueError("VID:PID 不是十六进制：%r" % spec)
    # 兜底：当串口名用（COM7 这种最自然的写法）
    return PortRule(name="cli-name", label="命令行指定串口名", priority=priority,
                    device_patterns=(text,))
