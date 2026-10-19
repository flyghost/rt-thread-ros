"""导出与瞬时提示。

拆自 tui/app.py 的 TuiApp（逻辑未改，只换容器）。"""

from __future__ import annotations

import os
import time
from pathlib import Path

from core.logstore import hexdump_text, sync
from core.util import repo_root

from tui.base import TuiBase


class OutputMixin(TuiBase):
    """导出与瞬时提示。"""

    def save_dump(self):
        out_dir = os.path.join(repo_root(), "out", "dump")
        stamp = time.strftime("%Y%m%d-%H%M%S")
        raw_path = os.path.join(out_dir, f"log-{stamp}.raw")
        txt_path = os.path.join(out_dir, f"log-{stamp}.txt")
        hex_path = os.path.join(out_dir, f"log-{stamp}.hex")
        try:
            os.makedirs(out_dir, exist_ok=True)
            with Path(raw_path).open("wb") as f:
                f.write(self.raw.bytes())
                sync(f)
            with Path(txt_path).open("w", encoding="utf-8", newline="") as f:
                for _kind, text in self.lines:
                    f.write(text + "\n")
                sync(f)
            hex_text, _off = hexdump_text(self.raw.bytes(), 0, "")
            with Path(hex_path).open("w", encoding="utf-8", newline="") as f:
                if hex_text:
                    f.write(hex_text + "\n")
                sync(f)
        except Exception as exc:
            self.flash_msg(f"存盘失败：{exc}")
            self.errors += 1
            return None
        self.flash_msg(f"已存 log-{stamp}.{{raw,txt,hex}}（{self.raw.size:d} 字节 RX）")
        return raw_path

    def flash_msg(self, text: str, seconds: float = 3.0):
        self.flash = text
        self.flash_until = time.time() + seconds
