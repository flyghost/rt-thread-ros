"""一次 YMODEM 传输的会话步骤：发起、解析 Block 0、收数据块、EOT 握手、落盘。

只处理"单个文件"，批量调度在 ymodem_receiver.py；帧格式在 ymodem_protocol.py。
"""

from __future__ import annotations

import time
from pathlib import Path

from ymodem_protocol import (
    ACK,
    BLOCK0_SIZE,
    CRC,
    DATA_REST,
    DATA_SIZE,
    EOT,
    NAK,
    SOH,
    STX,
    data_crc_ok,
    read_all,
)

INIT_REQUESTS = 5
INIT_INTERVAL = 0.3
FILE_TIMEOUT = 120.0
EOT_WAIT = 3.0


def request_transfer(ser, verbose: bool = True) -> None:
    """连发 'C' 把设备从 shell 拉进 YMODEM 发送态（并清掉进入前的残留输出）。"""
    if verbose:
        print("  Sending 'C' to initiate YMODEM...")
    ser.reset_input_buffer()  # 丢掉进 dump 前残留的输出，避免把老字节当包头
    for _ in range(INIT_REQUESTS):
        ser.write(b"C")
        ser.flush()
        time.sleep(INIT_INTERVAL)


def parse_block0(rest: bytes) -> tuple[str, int] | None:
    """Block-0 → (文件名, 字节数)；空 Block-0 表示批量结束，返回 None。"""
    parts = rest[2 : 2 + BLOCK0_SIZE].rstrip(b"\x00").split(b"\x00")
    if len(parts) < 2 or not parts[0]:
        # 空载荷（全零补齐）或文件名为空都是批量结束；判空名字是防御性的，
        # 否则空名字会拼出输出目录本身，写文件时报权限错误。
        return None
    return parts[0].decode("ascii", errors="replace"), int(parts[1].decode("ascii"))


def receive_one_file(ser, size: int, verbose: bool = True) -> bytes:
    """收一个文件的全部数据块，并完成两次 EOT 的握手。"""
    data = bytearray()
    started = time.time()
    expected_seq = 1  # 数据块从 seq=1 开始

    while len(data) < size and (time.time() - started) < FILE_TIMEOUT:
        raw = ser.read(1)
        if not raw:
            continue
        header = raw[0]

        if header == STX:
            block = read_all(ser, DATA_REST)
            if len(block) < DATA_REST:
                if verbose:
                    print("    Incomplete STX block")
                break
            if not data_crc_ok(block):
                if verbose:
                    print(f"    CRC mismatch at block seq={block[1]} — NAK")
                ser.write(bytes([NAK]))
                ser.flush()
                continue

            seq = block[0]
            chunk = block[2 : DATA_REST - 2]
            remaining = size - len(data)
            if seq == expected_seq:
                data.extend(chunk[:remaining])
                expected_seq = (expected_seq + 1) & 0xFF
                ser.write(bytes([ACK]))
                ser.flush()
                if verbose and len(data) % (32 * 1024) < DATA_SIZE:
                    print(f"    {len(data) * 100 // size}%  {len(data):,} bytes")
            elif seq == ((expected_seq - 1) & 0xFF):
                # 重传：上一块的 ACK 丢了；补 ACK，但不重复追加数据
                ser.write(bytes([ACK]))
                ser.flush()
            else:
                if verbose:
                    print(f"    Unexpected seq {seq} (expected {expected_seq}) — NAK")
                ser.write(bytes([NAK]))
                ser.flush()

        elif header == SOH:
            # 迟到的 Block 0 重发：丢弃并重新 ACK + 'C'
            read_all(ser, BLOCK0_SIZE + 4)
            ser.write(bytes([ACK, CRC]))
            ser.flush()

        elif header == EOT:
            break

        # 其余字节是噪声，忽略

    _finish_eot(ser)
    return bytes(data)


def _finish_eot(ser) -> None:
    """EOT 握手：设备两次 EOT。第一次回 NAK（还要后续文件），第二次回 ACK。"""
    raw = ser.read(1)
    if not (raw and raw[0] == EOT):
        started = time.time()
        while (time.time() - started) < EOT_WAIT:
            raw = ser.read(1)
            if raw and raw[0] == EOT:
                break
    ser.write(bytes([NAK]))
    ser.flush()
    time.sleep(0.05)
    raw = read_all(ser, 1, timeout=1.0)
    if raw and raw[0] == EOT:
        ser.write(bytes([ACK]))
        ser.flush()


def save_file(output: Path, name: str, data: bytes, verbose: bool = True) -> Path:
    """按 Block 0 里的文件名落盘（只写声明的长度，丢弃块内填充）。"""
    path = output / name
    path.write_bytes(data)
    if verbose:
        print(f"  Saved: {path} ({len(data):,} bytes)")
    return path
