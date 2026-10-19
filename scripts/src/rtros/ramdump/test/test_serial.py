#!/usr/bin/env python3
"""串口探针：列口 / 探控制台 / 回显自检（不碰 ramdump 逻辑）。

    scripts/ramdump.bat list
    scripts/ramdump.bat probe                 # 自动找口，看是否在 MSH
    scripts/ramdump.bat probe --com COM46 --seconds 5
    scripts/ramdump.bat probe --echo --com COM46      # 发一行看是否回显

为什么不再有 kill_com.bat / test_com3.py 那种 `taskkill /F /IM python.exe`：
那会把别的脚本一起杀掉。端口被占时请用 `python scripts/run_rtros.py hub --list`
看是谁，或用串口中枢接管该口（见 scripts/src/rtros/serial_hub/）。
"""

# __pycache__ 统一写到仓库 out/pycache：仓库根由本文件位置直接推出（parents[3]），不做搜索
import sys as _sys
from pathlib import Path as _Path

_sys.pycache_prefix = str(_Path(__file__).resolve().parents[3] / "out" / "pycache")

import argparse  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

from rtros.ramdump.lib import serial_utils  # noqa: E402

BAUDRATE = serial_utils.BAUDRATE


def list_ports():
    from serial.tools import list_ports as lp

    ports = list(lp.comports())
    pick = serial_utils.find_ch340_port()
    if not ports:
        print("没有发现任何串口")
        return 0
    print(f"{'口':<8s} {'描述':<34s} {'VID:PID':<12s} {''}")
    for p in ports:
        vidpid = f"{p.vid:04X}:{p.pid:04X}" if (p.vid and p.pid) else "----:----"
        mark = "  <== 自动选中" if p.device == pick else ""
        print(f"{p.device:<8s} {(p.description or '')[:34]:<34s} {vidpid:<12s} {mark}")
    if not pick:
        print("\n没有 VID:PID=1A86:7523 的口；请用 --com 指定（USB CDC 口是 FFFF:FFFF）")
    return 0


def probe(port, baud, seconds):
    try:
        ser = serial_utils.open_serial(port, baud)
    except Exception as exc:
        print(f"[PROBE] 打不开 {port}：{exc}")
        print("        口被占用时用 scripts/run_rtros.py hub --list 查占用者（别 taskkill python）")
        return 1
    print(f"[PROBE] 已打开 {port} @ {baud:d} 8N1，{seconds:d}s 内尝试敲回车 ...")
    try:
        deadline = time.time() + seconds
        buf = ""
        while time.time() < deadline:
            serial_utils.serial_send(ser, "")
            chunk = serial_utils.serial_read_until(ser, "msh />", timeout=1.0)
            buf += chunk
            if "msh />" in buf:
                break
        shape = (
            "MSH（可下发 cmd_ramdump）"
            if "msh />" in buf
            else "@ramdump>（已在 dump CLI）"
            if "@ramdump>" in buf
            else "没识别（可能没跑固件/被别的进程占着）"
        )
        print(f"[PROBE] 判定：{shape}")
        tail = [ln for ln in buf.replace("\r", "").split("\n") if ln.strip()][-8:]
        for ln in tail:
            print(f"   | {ln}")
        return 0 if ("msh />" in buf or "@ramdump>" in buf) else 1
    finally:
        ser.close()


def echo_check(port, baud):
    try:
        ser = serial_utils.open_serial(port, baud)
    except Exception as exc:
        print(f"[ECHO] 打不开 {port}：{exc}")
        return 1
    token = "ramdump_echo_12345"
    try:
        print(f"[ECHO] 发 {token!r}，看是否回显 ...")
        serial_utils.serial_send(ser, token)
        out = serial_utils.serial_read_until(ser, token, timeout=3.0)
        hit = token in out
        print("[ECHO] %s" % ("回显正常（TX/RX 都在工作）" if hit else "没收到回显（看接线/波特率/固件）"))
        return 0 if hit else 1
    finally:
        ser.close()


def main(argv=None):
    p = argparse.ArgumentParser(prog="test_serial.py", description="串口探针：列口 / 探控制台 / 回显自检")
    p.add_argument("--list", action="store_true", help="列出所有串口并标出会自动选哪个")
    p.add_argument("--probe", action="store_true", help="打开串口敲回车，判断在 MSH 还是 @ramdump>")
    p.add_argument("--echo", action="store_true", help="发一行看是否回显")
    p.add_argument("--com", help="串口号（省略则自动找 CH340）")
    p.add_argument("--baud", type=int, default=BAUDRATE)
    p.add_argument("--seconds", type=float, default=3.0, help="--probe 的探测时长")
    a = p.parse_args(argv)

    if a.list:
        return list_ports()
    if a.probe or a.echo:
        port = a.com or serial_utils.find_ch340_port()
        if not port:
            print("没自动找到口，请用 --com 指定")
            return 2
        if not a.com:
            print(f"[COM] 自动选中 {port}")
        return probe(port, a.baud, a.seconds) if a.probe else echo_check(port, a.baud)
    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
