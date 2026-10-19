"""SerialHub 的状态基类：只声明实例属性与类型，不放任何逻辑。

拆成多个 mixin 后，各自通过继承本类获得属性类型，mypy 才能检查跨文件访问
`self.ser` / `self.clients` 这类字段；真正的赋值仍然只在 SerialHub.__init__。
"""

from __future__ import annotations

import queue
import selectors
import threading
from typing import Any

import serial

from core.session import Client

SEL_READ = selectors.EVENT_READ
SEL_WRITE = selectors.EVENT_WRITE


class HubBase:
    """SerialHub 的全部实例属性（仅类型声明，见 SerialHub.__init__）。"""

    args: Any
    ser: serial.Serial | None
    ser_lock: threading.RLock
    ser_ok: bool
    last_open_try: float
    reopen_count: int
    clients: dict[int, Client]
    next_cid: int
    owner_cid: int | None
    tx: queue.Queue[tuple[bytes, str]]
    running: bool
    started: float
    rx_bytes: int
    tx_bytes: int
    drop_locked: int
    log_lock: threading.Lock
    print_lock: threading.Lock
    raw_f: Any
    log_f: Any
    log_stem: str | None
    sel: selectors.DefaultSelector
    srv: Any
    tsrv: Any
    ctl: Any
    drop_proto: int
    prefix: bytes
    tui: Any
    sinks: Any
    _state_dirty: bool
