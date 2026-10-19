#!/usr/bin/env python3
"""环形缓冲：给 UI 面板用的「最近 N 字节 / N 行」，与 hub 状态解耦。

刻意做成纯数据结构（无锁、无 IO、无线程）：

- 写侧：sink 收到事件后 `add()`，然后看 `dirty` 决定要不要唤醒 UI；
- 读侧：UI 按自己的帧率 `bytes()/tail()/lines()` 取快照，`take_dirty()` 清标记。

这样 UI 想换成 ANSI / Textual / 独立进程 / Web，都只是换渲染层，ringbuf 不用动。
"""

from __future__ import annotations

import collections


class ByteRing:
    """按字节上限保留最近的数据（不切断语义，半行问题交给渲染层）。"""

    def __init__(self, max_bytes: int = 65536):
        self.max_bytes = max(1024, int(max_bytes))
        self._chunks = collections.deque()
        self._size = 0
        self.dirty = False

    def add(self, data: bytes) -> int:
        if not data:
            return 0
        self._chunks.append(bytes(data))
        self._size += len(data)
        dropped = 0
        while self._size > self.max_bytes and self._chunks:
            old = self._chunks.popleft()
            dropped += len(old)
            self._size -= len(old)
        self.dirty = True
        return dropped

    def clear(self) -> None:
        self._chunks.clear()
        self._size = 0
        self.dirty = True

    def take_dirty(self) -> bool:
        """取出并清除「有新数据」标记（渲染层每帧调一次）。"""
        d, self.dirty = self.dirty, False
        return d

    @property
    def size(self) -> int:
        return self._size

    def __len__(self) -> int:
        return self._size

    def bytes(self) -> bytes:
        return b"".join(self._chunks)

    def tail(self, n: int) -> bytes:
        return self.bytes()[-n:] if n > 0 else b""


class LineRing:
    """按行上限保留最近的行（hub 消息、状态行）。"""

    def __init__(self, max_lines: int = 2000):
        self.max_lines = max(16, int(max_lines))
        self._lines = collections.deque(maxlen=self.max_lines)
        self.dirty = False

    def add(self, line: str) -> None:
        self._lines.append(line)
        self.dirty = True

    def extend(self, lines) -> None:
        for line in lines:
            self._lines.append(line)
        self.dirty = True

    def clear(self) -> None:
        self._lines.clear()
        self.dirty = True

    def take_dirty(self) -> bool:
        d, self.dirty = self.dirty, False
        return d

    def lines(self) -> list:
        return list(self._lines)

    def tail(self, n: int) -> list:
        if n <= 0:
            return []
        return list(self._lines)[-n:]

    def __len__(self) -> int:
        return len(self._lines)
