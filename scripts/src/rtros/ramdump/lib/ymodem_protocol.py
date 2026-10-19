"""YMODEM 的帧格式、常量与 CRC：纯函数，不持有任何会话状态。

帧结构（SOH/STX 之后的部分）：
    seq(1) + ~seq(1) + payload + CRC16(2)
    - Block 0：payload 固定 128 B，内容是 "文件名\\0大小\\0" 补零
    - 数据块：payload 固定 1024 B（STX）
"""

from __future__ import annotations

import time

# ---- 控制字节 ----
SOH = 0x01
STX = 0x02
EOT = 0x04
ACK = 0x06
NAK = 0x15
CRC = ord("C")

# ---- 帧长度 ----
BLOCK0_SIZE = 128
DATA_SIZE = 1024
PKT_OVERHEAD = 5  # SOH/STX(1) + seq(1) + ~seq(1) + CRC(2)
BLOCK0_REST = BLOCK0_SIZE + 4  # 去掉头字节后还需读的字节数（132）
DATA_REST = DATA_SIZE + 4  # 1028


def _build_crc_table() -> list[int]:
    """XMODEM CRC-16 查表（poly 0x1021，MSB first）。

    原实现是 256 行字面量；这里是等价生成式，改动前后逐项比对过完全相同。
    """
    table: list[int] = []
    for index in range(256):
        crc = index << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
        table.append(crc)
    return table


_CRC_TAB = _build_crc_table()


def crc16(data: bytes) -> int:
    """XMODEM CRC-16 (poly 0x1021)；`crc16(b"123456789") == 0x31C3`。"""
    crc = 0
    for byte in data:
        crc = ((crc << 8) ^ _CRC_TAB[((crc >> 8) ^ byte) & 0xFF]) & 0xFFFF
    return crc


def read_all(ser, count: int, timeout: float = 5.0) -> bytes:
    """读满 count 字节（超时或对端关闭则返回已读部分）。"""
    ser.timeout = timeout
    buf = b""
    while len(buf) < count:
        chunk = ser.read(count - len(buf))
        if not chunk:
            break
        buf += chunk
    return buf


def wait_header(ser, timeout: float = 60.0) -> int | None:
    """等一个 SOH 或 EOT 头字节；超时返回 None，其余字节一律丢弃。"""
    started = time.time()
    while (time.time() - started) < timeout:
        raw = ser.read(1)
        if raw and raw[0] in (SOH, EOT):
            return raw[0]
    return None


def block0_crc_ok(rest: bytes) -> bool:
    """校验 Block 0（seq + ~seq + 128 B + CRC16）。"""
    if len(rest) < BLOCK0_REST:
        return False
    received = (rest[BLOCK0_REST - 2] << 8) | rest[BLOCK0_REST - 1]
    return crc16(rest[2 : BLOCK0_REST - 2]) == received


def data_crc_ok(block: bytes) -> bool:
    """校验 STX 数据块（seq + ~seq + 1024 B + CRC16）。"""
    if len(block) < DATA_REST:
        return False
    received = (block[DATA_REST - 2] << 8) | block[DATA_REST - 1]
    return crc16(block[2 : DATA_REST - 2]) == received
