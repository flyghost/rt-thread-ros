"""TuiApp 的状态基类：只声明实例属性与类型，不放逻辑。

拆成多个 mixin 后各自继承本类拿到属性类型，mypy 才能检查跨文件访问
`self.lines` / `self.mode` 这类字段；赋值仍然只在 TuiApp.__init__。
"""

from __future__ import annotations

from collections import deque
from typing import Any

from core.ringbuf import ByteRing


class TuiBase:
    """TuiApp 的实例属性（仅类型声明，见 TuiApp.__init__）。"""

    hub: Any
    state: dict[str, Any]
    lines: deque[tuple[str, str]]
    hex_lines: deque[str]
    hex_off: int
    raw: ByteRing
    partial: str
    mode: str
    input_text: str
    input_mode: str
    sidebar: bool
    search: str
    search_on: bool
    hits: list[int]
    hit: int
    _hits_len: int
    scroll: int
    paused: bool
    echo_tx: bool
    help_on: bool
    flash: str
    flash_until: float
    frames: int
    errors: int
    _last_size: tuple[int, int] | None
