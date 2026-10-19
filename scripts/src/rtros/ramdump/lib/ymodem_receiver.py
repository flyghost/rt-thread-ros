"""YMODEM 接收入口：跑完一次批量传输，返回落盘后的文件路径列表。

分层：
    ymodem_protocol.py  帧格式 / CRC / 读字节（纯函数）
    ymodem_session.py   单个文件的会话步骤（发起、Block 0、数据块、EOT）
    ymodem_receiver.py  批量调度 + 对外 API + 常量再导出（兼容旧的
                        `from lib import ymodem_receiver` / `ymodem_receiver.SOH`）
"""

from __future__ import annotations

from pathlib import Path

from rtros.ramdump.lib.ymodem_protocol import (  # 兼容旧引用
    ACK,
    BLOCK0_REST,
    BLOCK0_SIZE,
    CRC,
    DATA_REST,
    DATA_SIZE,
    EOT,
    NAK,
    PKT_OVERHEAD,
    SOH,
    STX,
    block0_crc_ok,
    crc16,
    data_crc_ok,
    read_all,
    wait_header,
)
from rtros.ramdump.lib.ymodem_session import parse_block0, receive_one_file, request_transfer, save_file

BLOCK_TIMEOUT = 60.0

__all__ = [
    "ACK",
    "BLOCK0_REST",
    "BLOCK0_SIZE",
    "CRC",
    "DATA_REST",
    "DATA_SIZE",
    "EOT",
    "NAK",
    "PKT_OVERHEAD",
    "SOH",
    "STX",
    "block0_crc_ok",
    "crc16",
    "data_crc_ok",
    "read_all",
    "wait_header",
    "ymodem_receive",
]


def ymodem_receive(ser, output_dir: str, verbose: bool = True):
    """Receive files via YMODEM. Returns list of saved file paths."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []

    request_transfer(ser, verbose)
    if verbose:
        print("  Waiting for device to respond (up to 60s)...")

    while True:
        header = wait_header(ser, timeout=BLOCK_TIMEOUT)
        if header is None:
            if verbose:
                print("  Timeout waiting for YMODEM transfer.")
            break
        if header == EOT:
            if verbose:
                print("  Received EOT — transfer complete.")
            break

        rest = read_all(ser, BLOCK0_REST)
        if len(rest) < BLOCK0_REST:
            if verbose:
                print("  Incomplete Block 0")
            break
        if not block0_crc_ok(rest):
            if verbose:
                print("  Block 0 CRC mismatch — NAK")
            ser.write(bytes([NAK]))
            ser.flush()
            continue

        parsed = parse_block0(rest)
        if parsed is None:
            if verbose:
                print("  Batch end (empty Block 0)")
            ser.write(bytes([ACK]))
            ser.flush()
            break

        name, size = parsed
        if verbose:
            print(f"  Receiving: {name} ({size:,} bytes)")

        # ACK 回应 Block 0，'C' 请求数据块
        ser.write(bytes([ACK, CRC]))
        ser.flush()

        data = receive_one_file(ser, size, verbose)
        saved.append(str(save_file(output, name, data, verbose)))

        # 紧接着发 'C'：固件只等 3 秒，中间不能插慢操作（磁盘 I/O 已在上一步完成）
        ser.write(b"C")
        ser.flush()

    if verbose:
        print(f"  Done. {len(saved)} file(s) received.")
    return saved


if __name__ == "__main__":
    print("这是库模块；命令行入口见 dump/dump.py 与 dump/receive.py")
