#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内置 sink：落盘日志 + 本窗口文本/hex 流。

第 1 步重构（引入事件层）**刻意保持行为逐字节不变**，所以这两个 sink 的代码
就是从 `core/relay.py` 里原样搬出来的那两段：

    LogSink     —— <log_dir>/serial-<时间>.raw（设备->PC 字节精确流）+ .log（双向 + hub 消息）
    StreamSink  —— `--stdout {rx,rxtx,hex,none}` 的窗口输出（hex 视图带 8 字节空档）

锁复用 hub 的 `log_lock` / `print_lock`：与重构前是同一把锁，串行化语义不变。
句柄由 `relay.open_logs()` 打开、`relay.run()` 的 finally 关闭，sink 只负责写。
"""
from __future__ import annotations

import sys
from typing import Any, Dict

from core.events import EV_HUB, EV_RX, EV_TX, Event
from core.logstore import esc, hexdump_text, sync
from core.util import ts


class LogSink:
    """落盘（.raw / .log）。"""

    def __init__(self, hub):
        self.hub = hub

    def _write(self, text: str) -> None:
        f = self.hub.log_f
        if f is None:
            return
        with self.hub.log_lock:
            try:
                f.write(text)
                sync(f)
            except Exception:
                pass

    def _write_raw(self, data: bytes) -> None:
        f = self.hub.raw_f
        if f is None:
            return
        with self.hub.log_lock:
            try:
                f.write(data)
                sync(f)
            except Exception:
                pass

    def _data_lines(self, direction: str, who: str, data: bytes) -> None:
        if self.hub.log_f is None:
            return
        chunks = esc(data).split("\n")
        with self.hub.log_lock:
            try:
                for i, chunk in enumerate(chunks):
                    if i == len(chunks) - 1 and chunk == "":
                        break
                    self.hub.log_f.write("[%s] %s %s %s\n" % (ts(), direction, who, chunk))
                sync(self.hub.log_f)
            except Exception:
                pass

    # ---------------- EventSink ----------------
    def on_event(self, ev: Event) -> None:
        if ev.kind == EV_HUB:
            self._write(ev.text + "\n")
        elif ev.kind == EV_RX:
            self._write_raw(ev.data)          # 二进制留档：设备 -> PC 的原始字节
            self._data_lines("RX", ev.who, ev.data)
        elif ev.kind == EV_TX:
            self._data_lines("TX", ev.who, ev.data)

    def on_state(self, st: Dict[str, Any]) -> None:
        pass

    def close(self) -> None:
        pass


class StreamSink:
    """本窗口输出：`--stdout` 的四种语义 + hub 自身消息。"""

    def __init__(self, hub):
        self.hub = hub
        self.mode = getattr(hub.args, "stdout", "rx")
        self.hex_off = 0

    def _out(self, text: str) -> None:
        with self.hub.print_lock:
            try:
                sys.stdout.write(text)
                sys.stdout.flush()
            except Exception:
                pass

    def hexdump(self, data: bytes, tag: str = "") -> None:
        """设备 -> PC 的字节流按两栏 hex 视图（格式函数在 core/logstore.py）。"""
        text, self.hex_off = hexdump_text(data, self.hex_off, tag)
        self._out(text + "\n")

    # ---------------- EventSink ----------------
    def on_event(self, ev: Event) -> None:
        if ev.kind == EV_HUB:
            # hub 自己的消息：正常模式下都打；全静音(--stdout none)时仍打 [hub] 开头的关键信息
            if self.mode in ("rx", "rxtx", "hex") or ev.msg.startswith("[hub]"):
                self._out(ev.text + "\n")
            return
        if self.mode == "none":
            return
        if self.mode == "hex":
            # 只抓 设备 -> PC 的字节流；自己敲的东西看终端回显就够了
            if ev.direction == "RX":
                self.hexdump(ev.data)
            return
        if ev.direction == "RX" or self.mode == "rxtx":
            txt = esc(ev.data).replace("\\r\\n", "\n").replace("\\r", "\n")
            if ev.direction == "TX":
                txt = ">>> " + txt.replace("\n", "\n>>> ")
            if not txt.endswith("\n"):
                txt += "\n"
            self._out(txt)

    def on_state(self, st: Dict[str, Any]) -> None:
        pass

    def close(self) -> None:
        pass
