"""按键分发、命令行提交与 hub 命令执行。

拆自 tui/app.py 的 TuiApp（逻辑未改，只换容器）。"""

from __future__ import annotations

from tui.base import TuiBase


class InputMixin(TuiBase):
    """按键分发、命令行提交与 hub 命令执行。"""

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
            reply = f"命令出错：{exc}"
            self.errors += 1
        for line in str(reply or "").split("\n"):
            if line:
                self.lines.append(("ctl", line))
        self.flash_msg("hub 命令：" + text)
        return reply
