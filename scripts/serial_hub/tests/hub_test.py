#!/usr/bin/env python3
"""serial_hub 功能自测（对着已经在跑的 hub 测（不碰串口，只连 TCP））：
1) 两个客户端(A=自动化脚本角色, B=人开的终端角色) 同时连 5555
2) A 写 version -> 看串口回复是否【两个客户端都收到】（广播）
3) A 发 @@lock -> B 再写 -> 应被丢弃（status 的"丢弃(锁)"增长）
4) A 发 @@unlock -> B 再写 -> 应放行
5) 通过控制口 5556 查 status/clients
"""

# __pycache__ 统一写到仓库的 out/pycache（sys.pycache_prefix 只影响设置之后的 import，
# 所以要在所有本地 import 之前，但又必须在 from __future__ 之后）。
import os as _os
import sys as _sys

_d = _os.path.abspath(__file__)
while _d != _os.path.dirname(_d) and not _os.path.exists(_os.path.join(_d, ".git")):
    _d = _os.path.dirname(_d)
_sys.pycache_prefix = _os.path.join(_d, "out", "pycache")

import contextlib  # noqa: E402
import socket  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402

HOST = "127.0.0.1"
PORT = 5555
CTL = 5556


def data_conn():
    s = socket.create_connection((HOST, PORT), timeout=3)
    s.setblocking(False)
    return s


def ctl(cmd):
    try:
        s = socket.create_connection((HOST, CTL), timeout=3)
        s.settimeout(2)
        with contextlib.suppress(Exception):
            s.recv(4096)
        s.sendall((cmd + "\r\n").encode())
        time.sleep(0.25)
        out = b""
        try:
            while True:
                d = s.recv(4096)
                if not d:
                    break
                out += d
                if len(out) > 4096:
                    break
        except Exception:
            pass
        s.close()
        return out.decode("utf-8", "replace").replace("\r\n", " | ").strip()
    except Exception as exc:
        return f"CTL-ERR {exc}"


def drain(socks, wait=1.0):
    keys = [(s, i) for i, s in enumerate(socks)]
    buf = {i: b"" for i, _ in enumerate(socks)}
    t0 = time.time()
    while time.time() - t0 < wait:
        for s, i in keys:
            try:
                d = s.recv(65536)
                if d:
                    buf[i] += d
            except BlockingIOError:
                pass
            except Exception:
                pass
        time.sleep(0.03)
    return buf


def show(tag, b):
    print(f"  {tag:<34s} {b[:160]!r}")


def main():
    print("[1] 连接两个数据口客户端 A(AI) / B(人)")
    A = data_conn()
    B = data_conn()
    time.sleep(0.3)
    print("  status : " + ctl("status"))
    print("  clients: " + ctl("clients"))

    print("[2] A 写 'version' -> 串口回复应广播给 A 和 B")
    A.sendall(b"version\r\n")
    r = drain([A, B], 1.2)
    show("A 收到:", r[0])
    show("B 收到:", r[1])

    print("[3] A 发 @@lock（A 成为写锁持有者）")
    A.sendall(b"@@lock\r\n")
    r = drain([A, B], 0.6)
    show("A 收到回执:", r[0])
    show("B 收到:", r[1])
    print("  status : " + ctl("status"))

    print("[4] 锁住后 B 写 'B_SHOULD_BE_DROPPED' -> 必须被丢弃")
    B.sendall(b"B_SHOULD_BE_DROPPED\r\n")
    time.sleep(0.6)
    r = drain([A, B], 0.4)
    show("B 收到:", r[1])
    print("  status : " + ctl("status"))
    print("  clients: " + ctl("clients"))

    print("[5] A 发 @@unlock -> B 再写 -> 应放行")
    A.sendall(b"@@unlock\r\n")
    r = drain([A, B], 0.5)
    show("A 收到回执:", r[0])
    B.sendall(b"B_AFTER_UNLOCK\r\n")
    time.sleep(0.5)
    print("  status : " + ctl("status"))
    print("  clients: " + ctl("clients"))

    print("[6] 关闭 B（人开的终端退出）后 A 仍可用")
    B.close()
    time.sleep(0.4)
    print("  clients: " + ctl("clients"))
    A.sendall(b"@@status\r\n")
    r = drain([A], 0.6)
    show("A 收到 @@status 回执:", r[0])
    A.close()
    print("[done]")


if __name__ == "__main__":
    sys.exit(main())
