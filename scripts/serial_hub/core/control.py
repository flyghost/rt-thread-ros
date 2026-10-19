#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""控制口（默认 127.0.0.1:5556）的服务端。

每连接一个线程、`makefile("rwb", buffering=0)` 逐行读；命令执行交给
`hub.command(cmd, source, client)` —— 命令实现留在 relay，因为它要读 hub 状态。
"""

from __future__ import annotations


import socket
import sys
import threading


class ControlServer:
    """控制口监听 + 每连接一个线程。"""

    def __init__(self, hub, host: str, port: int):
        self.hub = hub
        self.host = host
        self.port = port
        self.sock = None

    def start(self) -> bool:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((self.host, self.port))
            self.sock.listen(4)
        except OSError as exc:
            print("[hub] 控制口绑定失败（继续跑）：%s" % exc, file=sys.stderr)
            self.sock = None
            return False
        threading.Thread(target=self._accept_loop, daemon=True).start()
        self.hub.log("[hub] 控制口  %s:%d（lock/unlock/status/reset/shutdown）" % (self.host, self.port))
        return True

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass

    def _accept_loop(self) -> None:
        while self.hub.running:
            try:
                conn, addr = self.sock.accept()
            except OSError:
                break
            threading.Thread(target=self._serve, args=(conn, addr), daemon=True).start()

    def _serve(self, conn, addr) -> None:
        """原 SerialHub.control_client，原样搬过来（self. -> self.hub.）。"""
        conn.settimeout(600)
        self.hub.log("[hub] 控制口连接 %s:%s" % addr)
        try:
            conn.sendall(b"# serial_hub control v1; 'help' for commands\r\n")
            f = conn.makefile("rwb", buffering=0)
            while self.hub.running:
                try:
                    line = f.readline()
                except Exception:
                    break
                if not line:
                    break
                reply = self.hub.command(
                    line.decode("utf-8", "replace").strip(), source="control", client=None
                )
                if reply:
                    try:
                        f.write((reply + "\r\n").encode())
                    except Exception:
                        break
                if not self.hub.running:
                    break
        finally:
            try:
                conn.close()
            except OSError:
                pass
