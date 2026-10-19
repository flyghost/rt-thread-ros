#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事件与 sink 契约：hub 只发事件，"谁来渲染"是 sink 的事。

这一层是"UI 可换"的全部秘密：

    读线程 / 写线程 / 状态变更  --emit(Event)-->  [ LogSink | StreamSink | TuiSink | ... ]

- 业务逻辑（串口独占、广播、写仲裁、协议协商、命令）**一行都不属于 sink**；
- sink 只做"把字节/状态变成人或机器能看的东西"（以及 TUI 需要的键位收集）；
- 加一个新 UI = 再写一个 EventSink 实现，`core/` 的逻辑不用改；
- sink 出错只累加计数，绝不影响串口侧（`SinkGroup` 逐个 try/except）。

状态用两种方式暴露，避免 UI 去摸内部结构：
- `on_state(snapshot)` —— 状态**变化**时推送；
- `hub.snapshot()` —— UI 需要按自己的帧率主动拉。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol, runtime_checkable

# 事件种类
EV_RX = "rx"  # 设备 -> PC 的字节
EV_TX = "tx"  # PC -> 设备的字节
EV_HUB = "hub"  # hub 自身消息（连接/断开/写锁/协商/重连/就绪…）
EV_STATE = "state"  # 状态快照（会话表、计数、写锁、串口状态）


@dataclass
class Event:
    """一次可观测的事情。

    - ``kind == EV_HUB``：用 ``msg``（原始消息）与 ``text``（已格式化整行，含时间戳）。
    - ``kind == EV_RX/EV_TX``：用 ``direction`` / ``who`` / ``data``。
    """

    kind: str
    msg: str = ""  # hub 消息原文（不带时间戳），供 sink 判断要不要打窗口
    text: str = ""  # 已格式化整行（含时间戳），sink 原样落盘/打印
    direction: str = ""  # "RX" / "TX"
    who: str = ""  # 会话名，或设备侧固定为 "board"
    data: bytes = b""
    ts: float = field(default_factory=time.time)


@runtime_checkable
class EventSink(Protocol):
    """所有 sink 的契约，只有三件事。"""

    def on_event(self, ev: Event) -> None: ...

    def on_state(self, st: Dict[str, Any]) -> None: ...

    def close(self) -> None: ...


class SinkGroup:
    """一次 emit 分发给所有 sink；单个 sink 抛异常不影响别人，也不影响串口侧。"""

    def __init__(self, sinks: List[EventSink] | None = None):
        self.sinks: List[EventSink] = list(sinks or [])
        self.errors = 0

    def add(self, sink: EventSink) -> None:
        self.sinks.append(sink)

    def emit(self, ev: Event) -> None:
        for s in self.sinks:
            try:
                s.on_event(ev)
            except Exception:
                self.errors += 1

    def state(self, st: Dict[str, Any]) -> None:
        for s in self.sinks:
            try:
                s.on_state(st)
            except Exception:
                self.errors += 1

    def close(self) -> None:
        for s in self.sinks:
            try:
                s.close()
            except Exception:
                pass
