"""TUI：全屏查看 + 搜索 + 命令行，实现 sink 契约（on_event/on_state/close）。

渲染、输入、缓冲区、导出各自拆到同目录 mixin；本文件只做装配与主循环。
拆自 tui/app.py 的 TuiApp（逻辑未改，只换容器）。"""

from __future__ import annotations

import contextlib
import sys
from collections import deque

from rtros.serial_hub.core.ringbuf import ByteRing
from rtros.serial_hub.tui import ansi as A
from rtros.serial_hub.tui import keys as K
from rtros.serial_hub.tui.base import PANEL_MAX, TuiBase
from rtros.serial_hub.tui.buffer import BufferMixin
from rtros.serial_hub.tui.input import InputMixin
from rtros.serial_hub.tui.output import OutputMixin
from rtros.serial_hub.tui.render import RenderMixin

RAW_MAX = 256 * 1024  # Ctrl-S 存盘保留的最大 RX 字节
FRAME_SECONDS = 0.05  # 每帧让给 hub.tick() 的时间


class TuiApp(BufferMixin, RenderMixin, InputMixin, OutputMixin, TuiBase):
    """sink 契约 + 自己的 loop()。"""

    name = "tui"

    def __init__(self, hub=None, mode="text", echo_tx=True):
        self.hub = hub
        self.state = {}
        self.lines = deque(maxlen=PANEL_MAX)  # (kind, text)
        self.hex_lines = deque(maxlen=PANEL_MAX)  # 已格式化行
        self.hex_off = 0
        self.raw = ByteRing(RAW_MAX)
        self.partial = ""
        self.mode = mode if mode in ("text", "hex", "both") else "text"
        self.input_text = ""
        self.input_mode = "dev"  # dev | hub | search
        self.sidebar = True  # 右侧会话侧栏
        self.search = ""  # 已提交的搜索关键字
        self.search_on = False  # 是否处于「搜索浏览」状态
        self.hits = []  # 命中行下标（针对文本行）
        self.hit = 0  # 当前命中序号
        self._hits_len = -1  # hits 是按多少行算出来的
        self.scroll = 0
        self.paused = False
        self.echo_tx = bool(echo_tx)
        self.help_on = False
        self.flash = ""
        self.flash_until = 0.0
        self.frames = 0
        self.errors = 0
        self._last_size = None

    def on_event(self, ev):
        try:
            if ev.kind == "rx" and ev.data:
                self._on_rx(ev.data)
            elif ev.kind == "tx" and ev.data:
                if self.echo_tx:
                    self.lines.append(("tx", ">>> " + self._text_of(ev.data)))
            elif ev.kind == "hub" and ev.msg:
                self.lines.append(("hub", "* " + ev.msg))
        except Exception:
            self.errors += 1

    def on_state(self, snapshot):
        if isinstance(snapshot, dict):
            self.state = snapshot

    def close(self):
        """sink 收尾：TUI 没有要关的句柄（屏幕由 loop() 的 finally 还原）。"""
        return

    def enter_screen(self):
        sys.stdout.write(A.ALT_ON + A.CLEAR + A.HIDE_CURSOR + A.HOME)
        sys.stdout.flush()

    def leave_screen(self):
        sys.stdout.write(A.RESET + A.SHOW_CURSOR + A.ALT_OFF)
        sys.stdout.flush()

    def pump(self, read=None, limit=32):
        read = read or K.read_key
        for _ in range(limit):
            tok = read()
            if not tok:
                break
            if not self.handle_key(tok):
                return False
        return True

    def loop(self, hub=None, key_source=None, max_frames=None, size=None):
        """驱动一帧帧刷新；串口 IO 在 hub 的线程里，这里只 tick + 画。"""
        if hub is not None:
            self.hub = hub
        read = key_source or K.read_key
        restore = K.setup_terminal()
        A.enable_vt()
        self.enter_screen()
        try:
            while getattr(self.hub, "running", False):
                self.frames += 1
                self.pump(read)
                self.draw(size)
                if self.hub is not None:
                    self.hub.tick(FRAME_SECONDS)
                if max_frames is not None and self.frames >= max_frames:
                    break
        except KeyboardInterrupt:
            pass
        finally:
            if self.hub is not None:
                with contextlib.suppress(Exception):
                    self.hub.running = False
            self.leave_screen()
            restore()
        return self.frames
