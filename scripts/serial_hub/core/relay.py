"""SerialHub：唯一持有串口的那个进程。

职责：独占串口、selector 主循环、广播、写方向仲裁、掉线重连、日志落盘。
具体实现按职责拆到同目录的 4 个 mixin；本文件只保留对象装配、事件出口与主循环。
拆自 core/relay.py 的 SerialHub（逻辑未改，只换容器）。
"""

from __future__ import annotations

import queue
import selectors
import sys
import threading
import time

try:
    pass
except Exception as exc:  # pragma: no cover
    print(f"需要 pyserial：pip install pyserial  （导入失败：{exc}）", file=sys.stderr)
    raise SystemExit(2) from exc  # 缺依赖属于部署错误，保留原因链

import contextlib

from core.events import EV_HUB, EV_RX, EV_TX, Event, SinkGroup
from core.hub_clients import ClientsMixin
from core.hub_commands import CommandsMixin
from core.hub_serial import SerialMixin
from core.hub_state import StateMixin
from core.session import Client
from core.sinks import LogSink, StreamSink
from core.util import human, ts


class SerialHub(SerialMixin, ClientsMixin, CommandsMixin, StateMixin):
    """组装：串口 + 会话 + 命令 + 状态；对外只暴露 run() 与几个事件出口。"""

    def __init__(self, args):
        self.args = args
        self.ser = None
        self.ser_lock = threading.RLock()
        self.ser_ok = False
        self.last_open_try = 0.0
        self.reopen_count = 0
        self.clients: dict[int, Client] = {}
        self.next_cid = 1
        self.owner_cid = None  # 持有写权限的客户端（None = 谁都能写）
        self.tx: queue.Queue[tuple[bytes, str]] = queue.Queue(maxsize=args.tx_queue)
        self.running = True
        self.started = time.time()
        self.rx_bytes = 0
        self.tx_bytes = 0
        self.drop_locked = 0
        self.log_lock = threading.Lock()
        self.print_lock = threading.Lock()
        self.raw_f = None
        self.log_f = None
        self.log_stem = None
        self.sel = selectors.DefaultSelector()
        self.srv = None
        self.tsrv = None
        self.ctl = None
        self.drop_proto = 0
        self.prefix = args.control_prefix.encode() if args.control_prefix else b""
        # ---- 输出层：hub 只"发事件"，落盘 / 本窗口 / UI 都是 sink ----
        # ui=tui 时用 TuiApp 取代本窗口输出（日志 sink 照旧，协议层完全不受影响）
        self.tui = None
        sinks = [LogSink(self)]
        if getattr(args, "ui", "stream") == "tui":
            from tui.app import TuiApp  # 只有选了 TUI 才会 import

            self.tui = TuiApp(self, mode="hex" if getattr(args, "stdout", "rx") == "hex" else "text")
            sinks.append(self.tui)
        elif getattr(args, "ui", "stream") == "stream":
            sinks.append(StreamSink(self))
        self.sinks = SinkGroup(sinks)
        self._state_dirty = False

    def log(self, text: str) -> None:
        """hub 自身消息：排版一次，交给 sink（落盘 / 条件打印本窗口）。"""
        self.emit(Event(kind=EV_HUB, msg=text, text=f"[{ts()}] {text}"))

    def emit(self, ev: Event) -> None:
        self.sinks.emit(ev)

    def mark_state(self) -> None:
        """标记状态变了：下一次 tick 推送一次快照（无 UI 的 sink 会忽略）。"""
        self._state_dirty = True

    def emit_state(self) -> None:
        self.sinks.state(self.snapshot())

    def log_data(self, direction: str, who: str, data: bytes) -> None:
        """兼容旧调用点：等价于发一个方向事件（落盘由 LogSink 完成）。"""
        self.emit(Event(kind=EV_RX if direction == "RX" else EV_TX, direction=direction, who=who, data=data))

    def out_console(self, direction: str, who: str, data: bytes) -> None:
        """兼容旧调用点：等价于发一个方向事件（窗口渲染由 StreamSink 完成）。"""
        self.emit(Event(kind=EV_RX if direction == "RX" else EV_TX, direction=direction, who=who, data=data))

    def run(self) -> int:
        a = self.args
        self.open_logs()
        if not self.open_serial():
            if not a.reopen:
                return 2
            self.last_open_try = time.time()
        if not self.start_servers():
            return 2
        self.mark_state()
        self.log(
            "[hub] 就绪。Raw 口 / %s / %d ；Telnet 口 / %s / %s ；控制口 %s"  # noqa: UP031
            % (a.host, a.port, a.host, a.telnet_port or "关闭", a.control_port or "关闭")
        )
        threading.Thread(target=self.reader_loop, daemon=True).start()
        threading.Thread(target=self.writer_loop, daemon=True).start()
        try:
            if self.tui is not None:
                self.tui.loop(self)  # UI 自己驱动 tick + 重画
            else:
                while self.running:
                    self.tick(0.05)
        except KeyboardInterrupt:
            self.log("[hub] Ctrl+C 退出")
        finally:
            self.running = False
            time.sleep(0.1)
            for c in list(self.clients.values()):
                c.close()
            if self.ctl:
                self.ctl.close()
            self.drop_serial("退出")
            self.log(
                "[hub] 结束：收 {} / 发 {}，日志 {}".format(
                    human(self.rx_bytes), human(self.tx_bytes), (self.log_stem or "(未开)")
                )
            )
            if self.log_f:
                with contextlib.suppress(Exception):
                    self.log_f.close()
            if self.raw_f:
                with contextlib.suppress(Exception):
                    self.raw_f.close()
            self.sinks.close()
        return 0
