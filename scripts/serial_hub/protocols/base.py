#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""接入协议的公共基类：Codec。

每个连接一个实例（内部可以有跨包状态）。

    encode(data): 串口 -> 客户端（广播时，每个会话各自调用一次）
    decode(data): 客户端 -> 串口，返回 (发给串口的字节, 只回给该客户端的字节)
    greeting():   连接建立后立刻发给客户端的协议层字节（raw 为空）

字段：
    name        协议名（写进会话表/日志）
    notes       协商轨迹（人类可读），由 hub 打日志
"""

from __future__ import annotations


class Codec:
    """接入协议编解码器。每个连接一个实例（内部可以有跨包状态）。

    encode(data): 串口 -> 客户端（广播时每个会话各自调用一次）
    decode(data): 客户端 -> 串口，返回 (发给串口的字节, 只回给该客户端的字节)
    """

    name = "raw"

    def encode(self, data: bytes) -> bytes:
        return data

    def decode(self, data: bytes) -> tuple[bytes, bytes]:
        return data, b""

    def reset(self) -> None:
        pass

    def greeting(self) -> bytes:
        """连接建立后立刻发给客户端的协议层字节（raw 为空）。"""
        return b""
