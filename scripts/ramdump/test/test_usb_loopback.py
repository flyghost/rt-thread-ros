#!/usr/bin/env python3
"""USB VCOM 回环测试：往 USB CDC 口写模式数据，看设备是否原样回显。

合并自原来的 usb_loopback_1024.py 与 usb_loopback_4k.py（两版只差载荷大小）。

    python scripts/ramdump/test/test_usb_loopback.py --com COM8
    python scripts/ramdump/test/test_usb_loopback.py --com COM8 --sizes 1024,4096
    python scripts/ramdump/test/test_usb_loopback.py --com COM8 --wait 10

前置：设备侧已经进 USB dump CLI，并在该 CDC 口上敲过 `vcom` 进入回环模式。
"""

# __pycache__ 统一写到仓库 out/pycache：仓库根由本文件位置直接推出（parents[3]），不做搜索
import sys as _sys
from pathlib import Path as _Path

_sys.pycache_prefix = str(_Path(__file__).resolve().parents[3] / "out" / "pycache")

import argparse  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/ramdump
sys.path.insert(0, _ROOT)

from lib import serial_utils  # noqa: E402


def one_round(port, size, wait=None):
    """发 size 字节模式数据并等回显，返回 (收到字节数, 是否逐字节相同, 首个差异下标)。"""
    usb = serial_utils.open_serial(port)
    usb.timeout = 0.1
    pattern = bytes([i % 256 for i in range(size)])
    echo = bytearray()
    done = threading.Event()

    def reader():
        while not done.is_set():
            try:
                chunk = usb.read(65536)
                if chunk:
                    echo.extend(chunk)
            except Exception:
                break

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    try:
        usb.write(pattern)
        usb.flush()
        w = wait if wait is not None else size / 500.0 + 2  # 粗估等待（沿用原 4k 脚本的公式）
        print(f"  发 {size:d} B，等 {w:.1f}s ...")
        time.sleep(w)
    finally:
        done.set()
        t.join(timeout=1)
        usb.close()

    got = len(echo)
    if got < size:
        return got, False, got
    diff = next((i for i in range(size) if echo[i] != pattern[i]), None)
    return got, diff is None, diff


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="test_usb_loopback.py", description="USB VCOM 回环测试（设备需已在 vcom 模式）"
    )
    p.add_argument(
        "--com", help="USB CDC 口（CDC 口 VID:PID 通常是 FFFF:FFFF，自动找口找不到，一般要显式给）"
    )
    p.add_argument("--baud", type=int, default=115200, help="CDC 口的波特率只是占位（USB 虚拟串口）")
    p.add_argument("--sizes", default="1024,4096,8192", help="逗号分隔的载荷大小（默认 1024,4096,8192）")
    p.add_argument("--wait", type=float, help="每轮等待秒数（默认按 size/500+2 估）")
    a = p.parse_args(argv)

    port = a.com or serial_utils.find_ch340_port()
    if not port:
        print("没自动找到口；USB CDC 口一般是 FFFF:FFFF，请显式 --com")
        return 2
    sizes = [int(x) for x in str(a.sizes).replace(" ", "").split(",") if x]
    print(f"[USB] 口={port} 轮次={sizes} 波特率={a.baud:d}（仅占位）")

    bad = 0
    for size in sizes:
        try:
            got, same, diff = one_round(port, size, a.wait)
        except Exception as exc:
            print(f"  {size:d}B: 打不开/出错：{exc}")
            bad += 1
            continue
        if same:
            print(f"  {size:d}B: 收到 {got:d}B，逐字节相同 OK")
        else:
            bad += 1
            if got < size:
                print(f"  {size:d}B: 只收到 {got:d}B（不完整）FAIL")
            else:
                print(f"  {size:d}B: 首个差异在下标 {diff:d} FAIL")
    print(f"[USB] {len(sizes) - bad:d}/{len(sizes):d} 轮通过")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
