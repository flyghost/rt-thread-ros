#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""采集入口（全流程）：编译 → 下载 → 等 MSH → 触发 ramdump → YMODEM 收 → 落盘。

    python scripts/ramdump/dump/dump.py                      # 自动找口，全流程
    python scripts/ramdump/dump/dump.py --com COM46 --skip-build
    python scripts/ramdump/dump/dump.py --region sram         # 只收 SRAM
    python scripts/ramdump/dump/dump.py --crash               # 用 RAMDUMP_ASSERT 走真异常路径
    python scripts/ramdump/dump/dump.py --transport usb       # UART 触发 + USB CDC 收

落盘位置：out/dump/<YYYYmmdd_HHMMSS>/（--out-dir 可指定）。
只收不触发请用 dump/receive.py。
"""
# __pycache__ 统一写到仓库的 out/pycache（sys.pycache_prefix 只影响设置之后的 import，
# 所以要在所有本地 import 之前，但又必须在 from __future__ 之后）。
import os as _os, sys as _sys
_d = _os.path.abspath(__file__)
while _d != _os.path.dirname(_d) and not _os.path.exists(_os.path.join(_d, '.git')):
    _d = _os.path.dirname(_d)
_sys.pycache_prefix = _os.path.join(_d, 'out', 'pycache')

import argparse
import os
import sys
import time
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # scripts/ramdump
sys.path.insert(0, _ROOT)

from lib import builder, console, serial_utils, ymodem_receiver        # noqa: E402
from lib.config import OUT_DUMP_DIR                                    # noqa: E402
from lib.serial_utils import BAUDRATE                                  # noqa: E402

REGION_CMD = {
    "all":   "ramdump",
    "flash": "ramdump_flash",
    "sram":  "ramdump sram",
    "ccm":   "ramdump ccm",
}


def pick_port(args):
    if args.com:
        return args.com
    port = serial_utils.find_ch340_port()
    if not port:
        print("[COM] 没自动找到 USB-UART 口，请用 --com 指定")
        return None
    print("[COM] 自动选中 %s" % port)
    return port


def enter_and_trigger(ser, region, crash=False, crash_cmd="RAMDUMP_ASSERT"):
    """把设备带进 @ramdump> 并让它开始发 YMODEM。"""
    if crash:
        print("\n[CONSOLE] 触发真异常路径：%s" % crash_cmd)
        serial_utils.serial_send(ser, crash_cmd, flush=False)
        out = serial_utils.serial_read_until(ser, "@ramdump>", timeout=30.0)
        if "@ramdump>" not in out:
            print("\n[CONSOLE] ERROR: 没等到 @ramdump> 提示符")
            return False
        print("[CONSOLE] @ramdump> 出现")
    elif not console.enter_ramdump(ser):
        return False

    time.sleep(0.3)
    cmd = REGION_CMD.get(region, "ramdump")
    print("\n[CONSOLE] 开始 dump：%s" % cmd)
    serial_utils.serial_send(ser, cmd)
    print("[CONSOLE] 等 3s 让 YMODEM 发送方就绪 ...")
    time.sleep(3.0)
    ser.reset_input_buffer()
    return True


def receive(ser, out_dir=None):
    out = out_dir or str(OUT_DUMP_DIR / time.strftime("%Y%m%d_%H%M%S"))
    print("[DUMP] 收到 %s" % out)
    saved = ymodem_receiver.ymodem_receive(ser, out)
    if not saved:
        print("[DUMP] 没收到文件（设备没在发？先看 --region 命令是否被接受）")
        return None
    total = sum(Path(f).stat().st_size for f in saved)
    print("[DUMP] %d 个文件，共 %d B" % (len(saved), total))
    for f in saved:
        print("   %-24s %10d B" % (Path(f).name, Path(f).stat().st_size))
    return out


def parse(argv):
    p = argparse.ArgumentParser(
        prog="dump.py", description="ramdump 全流程采集（编译 → 下载 → 触发 → YMODEM 收）",
        epilog="三个桶：build/ 编译下载 · dump/ 采集 · test/ 探针")
    p.add_argument("--com", help="串口号（省略则按 VID:PID 自动找 CH340）")
    p.add_argument("--baud", type=int, default=BAUDRATE)
    p.add_argument("--skip-build", action="store_true", help="跳过编译下载，直接采集")
    p.add_argument("--build-only", action="store_true", help="只编译下载，不采集")
    p.add_argument("--region", choices=sorted(REGION_CMD), default="all", help="dump 区域（默认 all）")
    p.add_argument("--flash-only", dest="region", action="store_const", const="flash", help="等价 --region flash")
    p.add_argument("--sram-only", dest="region", action="store_const", const="sram", help="等价 --region sram")
    p.add_argument("--ccm-only", dest="region", action="store_const", const="ccm", help="等价 --region ccm")
    p.add_argument("--crash", action="store_true",
                   help="走真异常路径（发 RAMDUMP_ASSERT）而不是 cmd_ramdump")
    p.add_argument("--crash-cmd", default="RAMDUMP_ASSERT", help="真异常路径用的 MSH 命令名")
    p.add_argument("--transport", choices=("uart", "usb"), default="uart",
                   help="uart=全走串口（默认）；usb=UART 触发 + USB CDC 收 dump")
    p.add_argument("--no-check", action="store_true", help="跳过 MSH 探测，直接触发")
    p.add_argument("--out-dir", help="落盘目录（默认 out/dump/<时间戳>）")
    p.add_argument("--new-console", action="store_true", help="编译/下载时弹独立 cmd 窗口")
    return p.parse_args(argv)


def main(argv=None):
    a = parse(argv)

    if a.build_only and a.skip_build:
        print("[WARN] --build-only 与 --skip-build 同时给了：按 --build-only 处理")
        a.skip_build = False

    if not a.skip_build:
        print("=" * 60)
        print("[BUILD] 编译 + 下载")
        print("=" * 60)
        if not builder.build_and_flash(new_console=a.new_console):
            print("[ERROR] 编译/下载失败，已停")
            return 1
        if a.build_only:
            return 0

    port = pick_port(a)
    if not port:
        return 2

    if a.transport == "usb":
        return _run_usb(a, port)

    ser = serial_utils.open_serial(port, a.baud)
    try:
        if not a.no_check and not console.check_console(ser):
            return 1
        if not enter_and_trigger(ser, a.region, a.crash, a.crash_cmd):
            return 1
        out = receive(ser, a.out_dir)
    finally:
        ser.close()
    return 0 if out else 1


def _run_usb(a, port):
    print("\n[USB] 走 USB CDC：串口只用来触发，dump 走 USB")
    uart = serial_utils.open_serial(port, a.baud)
    if not a.no_check and not console.check_console(uart):
        uart.close()
        return 1
    usb, usb_port = console.enter_ramdump_usb(uart)     # 成功时它自己已关掉 uart
    if usb is None:
        return 1
    try:
        cmd = REGION_CMD.get(a.region, "ramdump")
        print("\n[USB] 在 %s 上下发：%s" % (usb_port, cmd))
        serial_utils.serial_send(usb, cmd)
        time.sleep(3.0)
        usb.reset_input_buffer()
        out = receive(usb, a.out_dir)
    finally:
        usb.close()
    return 0 if out else 1


if __name__ == "__main__":
    sys.exit(main())
