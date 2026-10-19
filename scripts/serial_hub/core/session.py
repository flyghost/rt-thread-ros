#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Client：一条连接 = 一个会话。

负责：本会话的协议 codec、待发缓冲（已 encode）、写锁、计数。
广播语义的关键：串口来的**原始字节**交给每个会话各自 encode（feed），
而不是广播"已编码"的字节。
"""

from __future__ import annotations


import socket
import threading
import time

from protocols import CODECS, Codec


class Client:
    """一个连接 = 一个会话（数据口 raw/嗅探，或 telnet 口）。"""

    def __init__(self, sock: socket.socket, addr, cid: int, proto: str | None = None, locked: bool = False):
        self.sock = sock
        self.addr = addr
        self.cid = cid
        self.lock = threading.Lock()
        self.out = bytearray()  # 待发给本客户端的字节（已 encode）
        self.linebuf = b""  # 内联控制命令的半行缓冲
        self.rx = 0  # 本客户端 -> hub
        self.tx = 0  # hub -> 本客户端（encode 后的字节数）
        self.closed = False
        self.since = time.time()
        self.codec: Codec | None = None
        self.proto = ""
        self.proto_locked = locked  # True = 端口/参数已定，不再嗅探
        self.held_out = bytearray()  # 协议未判定前，设备来的字节先攒着
        self.drop_proto = 0  # 被协议层吃掉的字节数（IAC/协商等）
        if proto:
            self.use_proto(proto)
        sock.setblocking(False)

    @property
    def name(self) -> str:
        try:
            host, port = self.addr[0], self.addr[1]
        except Exception:
            host, port = "?", 0
        return "#%d %s(%s:%s)" % (self.cid, self.proto or "?", host, port)

    def use_proto(self, name: str) -> None:
        """切换接入协议（重置 codec 状态）。"""
        self.codec = CODECS[name]()
        self.proto = name

    def feed(self, data: bytes) -> None:
        """串口 -> 客户端：按本会话自己的协议 encode 后再排队。"""
        with self.lock:
            if self.closed:
                return
            if self.codec is None:  # 协议还没判定，先攒着
                self.held_out += data
                return
            enc = self.codec.encode(data)
            self.out += enc
            self.tx += len(enc)

    def feed_raw(self, data: bytes) -> None:
        """已经 encode 好的字节（如 telnet 协商应答），直接排队。"""
        with self.lock:
            if self.closed:
                return
            self.out += data
            self.tx += len(data)

    def flush_held_out(self) -> None:
        with self.lock:
            if self.codec is None or not self.held_out:
                return
            enc = self.codec.encode(bytes(self.held_out))
            self.held_out.clear()
            self.out += enc
            self.tx += len(enc)

    def take_out(self) -> bytes:
        with self.lock:
            if not self.out:
                return b""
            d = bytes(self.out)
            self.out.clear()
            return d

    def push_front(self, data: bytes) -> None:
        with self.lock:
            self.out = bytearray(data) + self.out

    def has_out(self) -> bool:
        with self.lock:
            return bool(self.out)

    def close(self) -> None:
        with self.lock:
            self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass
