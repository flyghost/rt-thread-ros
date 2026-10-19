"""收到的字节 → 行缓冲 → 搜索命中。

拆自 tui/app.py 的 TuiApp（逻辑未改，只换容器）。"""

from __future__ import annotations

from core.logstore import esc, hexdump_text

from tui.base import TuiBase


class BufferMixin(TuiBase):
    """收到的字节 → 行缓冲 → 搜索命中。"""

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

    def text_lines(self):
        """文本面板的源数据（同时也是搜索的作用对象）。"""
        lines = list(self.lines)
        if self.partial and not self.paused:
            lines.append(("rx", self.partial))
        return lines

    def visible_lines(self):
        """兼容旧接口：文本行 —— 渲染由 render(..., mode=) 决定画哪一份。"""
        return self.text_lines()

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
            self.flash_msg(f"没有命中「{self.search}」")
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
            self.flash_msg(f"没有命中「{self.search}」")

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
            return f"搜索「{self.search}」无命中"
        return "搜索「%s」%d/%d" % (self.search, self.hit + 1, len(hits))
