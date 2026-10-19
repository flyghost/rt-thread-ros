#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TUI：hub 的又一个 sink，同时是它自己的主循环驱动。

分工（换 UI 时只替换本目录）：

    串口/网络/协议/命令      ->  core/（一行都不属于 UI）
    Event -> 面板行          ->  TuiApp.on_event
    面板行 + 状态 -> 字符帧  ->  tui/view.py（纯函数，可离线断言）
    字符帧 -> 终端           ->  tui/ansi.py
    键盘 -> 动作             ->  TuiApp.handle_key（动作只走 hub.send()/hub.command()）

铁律：**不把串口读搬进 UI 线程**。IO 仍然由 hub 的读/写线程做，
UI 每帧只做 hub.tick(0.05)（转发 select）+ 重画。
"""

from __future__ import annotations

import os
import sys
import time
from collections import deque

from core.logstore import esc, hexdump_text, sync
from core.ringbuf import ByteRing
from core.util import human, repo_root, ts

from tui import ansi as A
from tui import keys as K
from tui.view import kind_color, render

PANEL_MAX = 4000  # 面板保留的最大行数
RAW_MAX = 256 * 1024  # Ctrl-S 存盘保留的最大 RX 字节
FRAME_SECONDS = 0.05  # 每帧让给 hub.tick() 的时间


class TuiApp:
    """实现 sink 契约（on_event/on_state/close）+ 自己的 loop()。"""

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

    # ---------------- sink 契约 ----------------
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
        return None

    @staticmethod
    def _text_of(data: bytes) -> str:
        return esc(data).replace("\\r\\n", "\n").replace("\\r", "\n").rstrip("\n")

    def _on_rx(self, data: bytes):
        try:
            self.raw.add(data)
        except Exception:
            self.errors += 1
        text, self.hex_off = hexdump_text(data, self.hex_off, "")
        for line in text.split("\n"):
            if line:
                self.hex_lines.append(line)
        if self.paused:
            return
        chunk = self.partial + data.decode("utf-8", "replace")
        parts = chunk.split("\n")
        self.partial = parts.pop()
        for part in parts:
            self.lines.append(("rx", part.rstrip("\r")))

    # ---------------- 面板内容 ----------------
    def text_lines(self):
        """文本面板的源数据（同时也是搜索的作用对象）。"""
        lines = list(self.lines)
        if self.partial and not self.paused:
            lines.append(("rx", self.partial))
        return lines

    def visible_lines(self):
        """兼容旧接口：文本行 —— 渲染由 render(..., mode=) 决定画哪一份。"""
        return self.text_lines()

    # ---------------- 搜索 ----------------
    def recompute_hits(self, force=False):
        """算命中下标；行数没变就不重算（每帧都会调）。"""
        if not self.search:
            self.hits = []
            self._hits_len = -1
            return []
        src = self.text_lines()
        if force or len(src) != self._hits_len:
            needle = self.search.lower()
            self.hits = [i for i, (_k, t) in enumerate(src) if needle in t.lower()]
            self._hits_len = len(src)
            if self.hits:
                self.hit = min(self.hit, len(self.hits) - 1)
            else:
                self.hit = 0
        return self.hits

    def jump_hit(self, delta):
        hits = self.recompute_hits()
        if not hits:
            self.flash_msg("没有命中「%s」" % self.search)
            return
        self.hit = max(0, min(len(hits) - 1, self.hit + delta))
        self.scroll = max(0, len(self.text_lines()) - 1 - hits[self.hit])
        self.flash_msg("命中 %d/%d" % (self.hit + 1, len(hits)))

    def start_search(self):
        self.input_mode = "search"
        self.input_text = self.search
        self.flash_msg("输入关键字后回车开始搜索（Esc 取消）")

    def run_search(self):
        self.search = self.input_text.strip()
        self.input_text = ""
        self.input_mode = "dev"
        self.search_on = bool(self.search)
        self.hits = []
        self._hits_len = -1
        if not self.search_on:
            self.flash_msg("搜索已关闭")
            return
        if self.mode == "hex":  # hex 面板不参与高亮 -> 自动切回文本
            self.mode = "text"
        hits = self.recompute_hits(force=True)
        if hits:
            self.hit = len(hits) - 1
            self.scroll = max(0, len(self.text_lines()) - 1 - hits[self.hit])
            self.flash_msg("命中 %d 处" % len(hits))
        else:
            self.flash_msg("没有命中「%s」" % self.search)

    def exit_search(self):
        self.search_on = False
        self.search = ""
        self.hits = []
        self._hits_len = -1
        self.flash_msg("搜索已退出")

    def search_status(self):
        if not (self.search_on and self.search):
            return ""
        hits = self.recompute_hits()
        if not hits:
            return "搜索「%s」无命中" % self.search
        return "搜索「%s」%d/%d" % (self.search, self.hit + 1, len(hits))

    @staticmethod
    def _mark(text, needle_lower, current, kind):
        """给行内匹配加底色：当前命中 = 黄底加粗，其余 = 反色。"""
        low = text.lower()
        bg = A.BG_YELLOW + A.BOLD if current else A.REVERSE
        color = kind_color(kind)
        out = []
        i = 0
        while True:
            pos = low.find(needle_lower, i)
            if pos < 0:
                out.append(text[i:])
                break
            out.append(text[i:pos])
            out.append(bg + text[pos : pos + len(needle_lower)] + A.RESET + color)
            i = pos + len(needle_lower)
        return "".join(out)

    def decorated_text_lines(self):
        """文本行 + 搜索高亮（view 只管画，不知道有搜索这回事）。"""
        src = self.text_lines()
        if not (self.search_on and self.search):
            return src
        hits = set(self.recompute_hits())
        cur = self.hits[self.hit] if self.hits and self.hit < len(self.hits) else -1
        needle = self.search.lower()
        out = []
        for i, (kind, text) in enumerate(src):
            if i in hits:
                out.append((kind, self._mark(text, needle, i == cur, kind)))
            else:
                out.append((kind, text))
        return out

    # ---------------- 会话侧栏 ----------------
    def sidebar_lines(self):
        if not self.sidebar:
            return []
        st = self.state or {}
        out = ["会话 %d   写锁 %s" % (int(st.get("clients") or 0), st.get("owner") or "无"), "-" * 26]
        sessions = st.get("sessions") or []
        for s in sessions:
            mark = " <=锁" if s.get("locked") else ""
            out.append("#%s %s %s%s" % (s.get("cid"), s.get("proto") or "?", s.get("addr") or "", mark))
            out.append("   收 %s  发 %s" % (human(int(s.get("rx") or 0)), human(int(s.get("tx") or 0))))
            extra = "   会话 %ds" % int(s.get("uptime") or 0)
            if s.get("drop_proto"):
                extra += "  协议吃掉 %s" % human(int(s["drop_proto"]))
            out.append(extra)
        if not sessions:
            out.append("(暂无客户端)")
        out.append("")
        out.append("串口 %s %s" % (st.get("com") or "?", "OK" if st.get("ser_ok") else "断开"))
        out.append("收 %s   发 %s" % (human(int(st.get("rx") or 0)), human(int(st.get("tx") or 0))))
        if st.get("drop_locked"):
            out.append("丢(锁) %s" % human(int(st["drop_locked"])))
        if st.get("drop_proto"):
            out.append("协议吃掉 %s" % human(int(st["drop_proto"])))
        sinks = st.get("sinks")
        if isinstance(sinks, (list, tuple)):
            for name in sinks:
                out.append("sink %s" % name)
        elif sinks is not None:
            out.append("sink 数量 %s" % sinks)
        if int(st.get("sink_errors") or 0):
            out.append("sink 错误 %s" % int(st["sink_errors"]))
        if st.get("log"):
            out.append("日志 %s" % str(st["log"]).replace("\\", "/").split("/")[-1])
        return out

    # ---------------- 屏幕 ----------------
    def enter_screen(self):
        sys.stdout.write(A.ALT_ON + A.CLEAR + A.HIDE_CURSOR + A.HOME)
        sys.stdout.flush()

    def leave_screen(self):
        sys.stdout.write(A.RESET + A.SHOW_CURSOR + A.ALT_OFF)
        sys.stdout.flush()

    def draw(self, size=None):
        if self.hub is not None:
            try:
                snap = self.hub.snapshot()
                if isinstance(snap, dict):
                    self.state = snap
            except Exception:
                self.errors += 1
        if self.flash and time.time() > self.flash_until:
            self.flash = ""
        w, h = size or A.term_size()
        frame = render(
            self.state,
            self.decorated_text_lines(),
            w,
            h,
            input_text=self.input_text,
            input_mode=self.input_mode,
            mode=self.mode,
            scroll=self.scroll,
            paused=self.paused,
            flash=self.flash,
            help_on=self.help_on,
            hex_lines=list(self.hex_lines),
            sidebar=self.sidebar_lines(),
            extra_status=self.search_status(),
        )
        prefix = A.HOME
        if size is not None and self._last_size is not None and tuple(size) != self._last_size:
            prefix = A.CLEAR + A.HOME
        self._last_size = (w, h)
        sys.stdout.write(prefix + "\r\n".join(frame))
        sys.stdout.flush()
        return frame

    # ---------------- 键盘 ----------------
    def pump(self, read=None, limit=32):
        read = read or K.read_key
        for _ in range(limit):
            tok = read()
            if not tok:
                break
            if not self.handle_key(tok):
                return False
        return True

    def handle_key(self, tok: str) -> bool:
        """返回 False 表示「退出 UI」。"""
        hub = self.hub
        # n / N：搜索命中之间跳（仅在「搜索浏览」状态、且输入行是空的）
        if tok in ("c:n", "c:N") and self.search_on and self.input_mode == "dev" and not self.input_text:
            self.jump_hit(1 if tok == "c:n" else -1)
            return True
        if tok.startswith("c:"):
            ch = tok[2:]
            if ch.isprintable() and len(self.input_text) < 400:
                self.input_text += ch
            return True
        if tok == "enter":
            self.submit()
        elif tok == "backspace":
            self.input_text = self.input_text[:-1]
        elif tok == "esc":
            if self.input_mode == "search":  # 放弃搜索输入
                self.input_mode = "dev"
                self.input_text = ""
                self.flash_msg("搜索输入已取消")
            elif self.search_on:  # 先退搜索，再谈关帮助
                self.exit_search()
            else:
                self.help_on = False
                self.input_text = ""
        elif tok == "tab":
            self.input_mode = "hub" if self.input_mode == "dev" else "dev"
        elif tok in ("ctrl-q", "ctrl-c"):
            if hub is not None:
                hub.running = False
            return False
        elif tok == "ctrl-t":
            order = ("text", "hex", "both")
            self.mode = order[(order.index(self.mode) + 1) % len(order)]
            self.flash_msg("视图：" + self.mode)
        elif tok == "ctrl-w":
            self.sidebar = not self.sidebar
            self.flash_msg("会话侧栏：" + ("开" if self.sidebar else "关"))
        elif tok == "ctrl-f":
            self.start_search()
        elif tok == "ctrl-l":
            self.lines.clear()
            self.hex_lines.clear()
            self.flash_msg("面板已清空")
        elif tok == "ctrl-s":
            self.save_dump()
        elif tok == "ctrl-p":
            self.paused = not self.paused
            self.flash_msg("面板已暂停" if self.paused else "面板已恢复")
        elif tok == "ctrl-e":
            self.echo_tx = not self.echo_tx
            self.flash_msg("回显 TX" if self.echo_tx else "不回显 TX")
        elif tok in ("f1", "ctrl-h"):
            self.help_on = not self.help_on
        elif tok == "pgup":
            self.jump_hit(-10) if self.search_on else self.scroll_up(10)
        elif tok == "pgdn":
            self.jump_hit(10) if self.search_on else self.scroll_up(-10)
        elif tok == "up":
            self.jump_hit(-1) if self.search_on else self.scroll_up(1)
        elif tok == "down":
            self.jump_hit(1) if self.search_on else self.scroll_up(-1)
        elif tok == "home":
            self.scroll += PANEL_MAX
        elif tok == "end":
            self.scroll = 0
        return True

    def scroll_up(self, n: int):
        self.scroll = max(0, self.scroll + n)

    # ---------------- 动作（一律走 hub 的公开入口） ----------------
    def submit(self):
        if self.input_mode == "search":  # 输入行此时是「搜索关键字」
            self.run_search()
            return ""
        text = self.input_text.strip()
        self.input_text = ""
        if not text:
            self.scroll = 0
            return ""
        forced = text.startswith("@@")  # 显式 @@ = 一定是 hub 命令（与数据口内联惯例一致）
        if forced:
            text = text[2:].strip()
            if not text:
                return ""
        verb = text.split(" ")[0]
        if (
            forced
            or self.input_mode == "hub"
            or verb
            in ("help", "status", "sessions", "lock", "unlock", "proto", "kill", "reset", "shutdown", "ping")
        ):
            return self.run_command(text)
        return self.send_line(text)

    def send_line(self, text: str) -> bool:
        """把一行发给设备（补 CR）。失败（写锁/串口断开）只提示，不抛。"""
        if self.hub is None:
            return False
        try:
            ok = bool(self.hub.send(text.encode("utf-8", "replace") + b"\r", who="tui"))
        except Exception:
            ok = False
            self.errors += 1
        if not ok:
            self.flash_msg("没发出去：写锁在别的会话手上，或串口断开了")
        return ok

    def run_command(self, text: str) -> str:
        if self.hub is None:
            return ""
        try:
            reply = self.hub.command(text, source="tui", client=None)
        except Exception as exc:  # 命令有 bug 也不能把 UI 带走
            reply = "命令出错：%s" % exc
            self.errors += 1
        for line in str(reply or "").split("\n"):
            if line:
                self.lines.append(("ctl", line))
        self.flash_msg("hub 命令：" + text)
        return reply

    def save_dump(self):
        out_dir = os.path.join(repo_root(), "out", "dump")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        raw_path = os.path.join(out_dir, "log-%s.raw" % stamp)
        txt_path = os.path.join(out_dir, "log-%s.txt" % stamp)
        hex_path = os.path.join(out_dir, "log-%s.hex" % stamp)
        try:
            os.makedirs(out_dir, exist_ok=True)
            with open(raw_path, "wb") as f:
                f.write(self.raw.bytes())
                sync(f)
            with open(txt_path, "w", encoding="utf-8", newline="") as f:
                for _kind, text in self.lines:
                    f.write(text + "\n")
                sync(f)
            hex_text, _off = hexdump_text(self.raw.bytes(), 0, "")
            with open(hex_path, "w", encoding="utf-8", newline="") as f:
                if hex_text:
                    f.write(hex_text + "\n")
                sync(f)
        except Exception as exc:
            self.flash_msg("存盘失败：%s" % exc)
            self.errors += 1
            return None
        self.flash_msg("已存 log-%s.{raw,txt,hex}（%d 字节 RX）" % (stamp, self.raw.size))
        return raw_path

    def flash_msg(self, text: str, seconds: float = 3.0):
        self.flash = text
        self.flash_until = time.time() + seconds

    # ---------------- 主循环 ----------------
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
                try:
                    self.hub.running = False
                except Exception:
                    pass
            self.leave_screen()
            restore()
        return self.frames
