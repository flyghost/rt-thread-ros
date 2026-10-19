"""YMODEM 协议层与会话层的离线性测试（假串口，不碰硬件）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from rtros.ramdump.lib import ymodem_receiver
from rtros.ramdump.lib.ymodem_protocol import (
    ACK,
    BLOCK0_SIZE,
    CRC,
    DATA_SIZE,
    EOT,
    NAK,
    SOH,
    STX,
    crc16,
)


class FakeSerial:
    """按字节回放预设流，并记录主机写出的控制字节。"""

    def __init__(self, stream: bytes) -> None:
        self.buf = bytearray(stream)
        self.written = bytearray()
        self.timeout = 5.0

    def read(self, n: int = 1) -> bytes:
        took = bytes(self.buf[:n])
        del self.buf[:n]
        return took

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def flush(self) -> None:
        return

    def reset_input_buffer(self) -> None:
        return


def frame(seq: int, payload: bytes, header: int) -> bytes:
    size = BLOCK0_SIZE if header == SOH else DATA_SIZE
    body = payload[:size].ljust(size, b"\x00")
    crc = crc16(body)
    return bytes([header, seq & 0xFF, (~seq) & 0xFF]) + body + bytes([crc >> 8, crc & 0xFF])


def block0(name: bytes, size: int) -> bytes:
    return frame(0, name + b"\x00" + str(size).encode() + b"\x00", SOH)


@pytest.mark.parametrize(
    ("data", "expect"),
    [
        (b"", 0),
        (b"123456789", 0x31C3),  # XMODEM CRC-16 标准检验值
    ],
)
def test_crc16_vectors(data: bytes, expect: int) -> None:
    assert crc16(data) == expect


def test_receive_handles_bad_crc_retransmit_and_batch_end(work_dir: Path) -> None:
    """坏 CRC → NAK 重传；重复块只补 ACK；两次 EOT；空 Block 0 收尾。"""
    payload = bytes((i * 7 + 3) & 0xFF for i in range(2000))
    broken = bytearray(frame(1, payload[:DATA_SIZE], STX))
    broken[-1] ^= 0xFF

    stream = b"".join(
        [
            block0(b"SRAM.bin", len(payload)),
            bytes(broken),
            frame(1, payload[:DATA_SIZE], STX),
            frame(1, payload[:DATA_SIZE], STX),  # 重复块（ACK 丢失）
            frame(2, payload[DATA_SIZE:], STX),
            bytes([EOT]),
            bytes([EOT]),
            bytes([SOH, 0, 255]) + bytes(BLOCK0_SIZE + 2),  # 全零 Block 0 = 批量结束
        ]
    )
    ser = FakeSerial(stream)
    saved = ymodem_receiver.ymodem_receive(ser, str(work_dir), verbose=False)

    assert len(saved) == 1
    assert Path(saved[0]).read_bytes() == payload
    written = bytes(ser.written)
    assert NAK in written
    assert ACK in written
    assert bytes([ACK, CRC]) in written


def test_empty_block0_ends_batch_without_writing(work_dir: Path) -> None:
    """空载荷 Block 0（批量结束）不能拼出输出目录本身去写文件。"""
    ser = FakeSerial(bytes([SOH, 0, 255]) + bytes(BLOCK0_SIZE + 2))
    saved = ymodem_receiver.ymodem_receive(ser, str(work_dir), verbose=False)

    assert saved == []
    assert list(work_dir.iterdir()) == []


def test_constants_are_reexported() -> None:
    """旧代码用 `ymodem_receiver.SOH`，拆分后仍要能拿到。"""
    assert ymodem_receiver.SOH == 0x01
    assert ymodem_receiver.STX == 0x02
    assert ymodem_receiver.EOT == 0x04
