"""把状态画成一屏（含搜索高亮与会话侧栏）。

拆自 tui/app.py 的 TuiApp（逻辑未改，只换容器）。"""

from __future__ import annotations

import sys
import time

from core.util import human

from tui import ansi as A
from tui.base import TuiBase
from tui.view import kind_color, render


class RenderMixin(TuiBase):
    """把状态画成一屏（含搜索高亮与会话侧栏）。"""

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

    def sidebar_lines(self):
        if not self.sidebar:
            return []
        st = self.state or {}
        out = ["会话 %d   写锁 %s" % (int(st.get("clients") or 0), st.get("owner") or "无"), "-" * 26]
        sessions = st.get("sessions") or []
        for s in sessions:
            mark = " <=锁" if s.get("locked") else ""
            out.append("#{} {} {}{}".format(s.get("cid"), s.get("proto") or "?", s.get("addr") or "", mark))
            out.append("   收 {}  发 {}".format(human(int(s.get("rx") or 0)), human(int(s.get("tx") or 0))))
            extra = "   会话 %ds" % int(s.get("uptime") or 0)
            if s.get("drop_proto"):
                extra += "  协议吃掉 {}".format(human(int(s["drop_proto"])))
            out.append(extra)
        if not sessions:
            out.append("(暂无客户端)")
        out.append("")
        out.append("串口 {} {}".format(st.get("com") or "?", "OK" if st.get("ser_ok") else "断开"))
        out.append("收 {}   发 {}".format(human(int(st.get("rx") or 0)), human(int(st.get("tx") or 0))))
        if st.get("drop_locked"):
            out.append("丢(锁) {}".format(human(int(st["drop_locked"]))))
        if st.get("drop_proto"):
            out.append("协议吃掉 {}".format(human(int(st["drop_proto"]))))
        sinks = st.get("sinks")
        if isinstance(sinks, (list, tuple)):
            for name in sinks:
                out.append(f"sink {name}")
        elif sinks is not None:
            out.append(f"sink 数量 {sinks}")
        if int(st.get("sink_errors") or 0):
            out.append("sink 错误 {}".format(int(st["sink_errors"])))
        if st.get("log"):
            out.append("日志 {}".format(str(st["log"]).replace("\\", "/").split("/")[-1]))
        return out

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
