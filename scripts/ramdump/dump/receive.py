#!/usr/bin/env python3
"""只收：设备侧已经在跑，本脚本只负责「下发 dump 命令 → YMODEM 收 → 落盘」。

    python scripts/ramdump/dump/receive.py --com COM46                # 触发一次并收
    python scripts/ramdump/dump/receive.py --com COM46 --no-trigger    # 设备已在发 YMODEM，直接收
    python scripts/ramdump/dump/receive.py --region sram               # 只收 SRAM
    python scripts/ramdump/dump/receive.py                             # 自动找口

和 dump.py 的区别：不编译、不下载、不进 ramdump（除 --no-check 外会先探一次 MSH）。
"""

# __pycache__ 统一写到仓库的 out/pycache（sys.pycache_prefix 只影响设置之后的 import，
# 所以要在所有本地 import 之前，但又必须在 from __future__ 之后）。
import os as _os
import sys as _sys

_d = _os.path.abspath(__file__)
while _d != _os.path.dirname(_d) and not _os.path.exists(_os.path.join(_d, ".git")):
    _d = _os.path.dirname(_d)
_sys.pycache_prefix = _os.path.join(_d, "out", "pycache")

import argparse
import os
import sys
import time
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/ramdump
sys.path.insert(0, _ROOT)

from lib import console, serial_utils, ymodem_receiver  # noqa: E402
from lib.config import OUT_DUMP_DIR  # noqa: E402
from lib.serial_utils import BAUDRATE  # noqa: E402

REGION_CMD = {
    "all": "ramdump",
    "flash": "ramdump_flash",
    "sram": "ramdump sram",
    "ccm": "ramdump ccm",
}


def main(argv=None):
    p = argparse.ArgumentParser(prog="receive.py", description="只做 YMODEM 收取（设备已在运行）")
    p.add_argument("--com", help="串口号（省略则按 VID:PID 自动找 CH340）")
    p.add_argument("--baud", type=int, default=BAUDRATE)
    p.add_argument("--region", choices=sorted(REGION_CMD), default="all")
    p.add_argument("--out-dir", help="落盘目录（默认 out/dump/<时间戳>）")
    p.add_argument("--no-trigger", action="store_true", help="不下发任何命令，设备已经在等/在发 YMODEM")
    p.add_argument("--no-check", action="store_true", help="跳过 MSH 探测")
    a = p.parse_args(argv)

    port = a.com or serial_utils.find_ch340_port()
    if not port:
        print("[COM] 没自动找到 USB-UART 口，请用 --com 指定")
        return 2
    if not a.com:
        print(f"[COM] 自动选中 {port}")

    ser = serial_utils.open_serial(port, a.baud)
    try:
        if not a.no_check and not console.check_console(ser):
            return 1
        if not a.no_trigger:
            cmd = REGION_CMD[a.region]
            print(f"\n[CONSOLE] 下发：{cmd}")
            serial_utils.serial_send(ser, cmd)
            print("[CONSOLE] 等 3s 让 YMODEM 发送方就绪 ...")
            time.sleep(3.0)
            ser.reset_input_buffer()

        out = a.out_dir or str(OUT_DUMP_DIR / time.strftime("%Y%m%d_%H%M%S"))
        print(f"[DUMP] 收到 {out}")
        saved = ymodem_receiver.ymodem_receive(ser, out)
        if not saved:
            print("[DUMP] 没收到文件")
            return 1
        total = sum(Path(f).stat().st_size for f in saved)
        print("[DUMP] %d 个文件，共 %d B" % (len(saved), total))
        for f in saved:
            print("   %-24s %10d B" % (Path(f).name, Path(f).stat().st_size))
    finally:
        ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
