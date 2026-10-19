"""TCP 会话：监听/接入/写仲裁/协议判定/广播。

拆自 core/relay.py 的 SerialHub（逻辑未改，只换容器）。
"""

from __future__ import annotations

import queue
import socket
import sys
import time

try:
    pass
except Exception as exc:  # pragma: no cover
    print(f"需要 pyserial：pip install pyserial  （导入失败：{exc}）", file=sys.stderr)
    raise SystemExit(2) from exc  # 缺依赖属于部署错误，保留原因链

import contextlib

from core.control import ControlServer
from core.hub_base import SEL_READ, SEL_WRITE, HubBase
from core.logstore import esc
from core.session import Client
from core.util import human


class ClientsMixin(HubBase):
    """TCP 会话：监听/接入/写仲裁/协议判定/广播。"""

    def start_servers(self) -> bool:
        a = self.args
        host = "0.0.0.0" if a.allow_lan else a.host
        try:
            self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.srv.bind((host, a.port))
            self.srv.listen(16)
            self.srv.setblocking(False)
            self.sel.register(self.srv, SEL_READ, ("srv", None))
        except OSError as exc:
            print(f"[hub] 数据口绑定 {host}:{a.port:d} 失败：{exc}", file=sys.stderr)
            return False
        self.log(
            "[hub] 数据口  %s:%d  raw%s"  # noqa: UP031
            % (a.host, a.port, "（首字节 0xFF 自动切 telnet）" if a.sniff else "（不做嗅探）")
        )
        if a.telnet_port:
            try:
                self.tsrv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.tsrv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.tsrv.bind((host, a.telnet_port))
                self.tsrv.listen(16)
                self.tsrv.setblocking(False)
                self.sel.register(self.tsrv, SEL_READ, ("tsrv", None))
                self.log(f"[hub] telnet 口 {a.host}:{a.telnet_port:d}  （Telnet 前端）")
            except OSError as exc:
                print(
                    f"[hub] telnet 口绑定 {host}:{a.telnet_port:d} 失败（继续跑）：{exc}",
                    file=sys.stderr,
                )
                self.tsrv = None
        if a.control_port:
            self.ctl = ControlServer(self, host, a.control_port)
            self.ctl.start()
        return True

    def accept_data(self) -> None:
        try:
            conn, addr = self.srv.accept()
        except OSError:
            return
        # --port 上先不定协议，等首字节嗅探；--no-sniff 时直接 raw
        c = Client(
            conn, addr, self.next_cid, proto=None if self.args.sniff else "raw", locked=not self.args.sniff
        )
        self.next_cid += 1
        self.clients[c.cid] = c
        self.sel.register(conn, SEL_READ, ("data", c))
        self.log(f"[hub] 客户端接入 {c.name}（当前 {len(self.clients):d} 个，协议={c.proto or '待嗅探'}）")
        self.mark_state()

    def accept_telnet(self) -> None:
        try:
            conn, addr = self.tsrv.accept()
        except OSError:
            return
        c = Client(conn, addr, self.next_cid, proto="telnet", locked=True)
        self.next_cid += 1
        self.clients[c.cid] = c
        self.sel.register(conn, SEL_READ, ("data", c))
        greet = c.codec.greeting()
        if greet:
            c.feed_raw(greet)
            self.log(f"[hub] {c.name} 主动协商 {esc(greet)}（WILL ECHO / WILL SGA / DO SGA，未转发给串口）")
        self.log(f"[hub] 客户端接入 {c.name}（当前 {len(self.clients):d} 个，telnet 口）")
        self.mark_state()

    def drop_client(self, c: Client, why: str = "断开") -> None:
        if c.cid not in self.clients:
            return
        self.clients.pop(c.cid, None)
        with contextlib.suppress(Exception):
            self.sel.unregister(c.sock)
        c.close()
        if self.owner_cid == c.cid:
            self.owner_cid = None
            self.log(f"[hub] 持有写锁的客户端 {c.name} 已离开，自动解锁")
        self.log(
            "[hub] 客户端离开 %s（%s，收 %s 发 %s，剩余 %d 个）"  # noqa: UP031
            % (c.name, why, human(c.rx), human(c.tx), len(self.clients))
        )
        self.mark_state()

    def refresh_interest(self) -> None:
        for c in list(self.clients.values()):
            want = SEL_READ | (SEL_WRITE if c.has_out() else 0)
            with contextlib.suppress(Exception):
                self.sel.modify(c.sock, want, ("data", c))

    def handle_client_read(self, c: Client) -> None:
        try:
            data = c.sock.recv(65536)
        except BlockingIOError:
            return
        except OSError as exc:
            self.drop_client(c, f"读取失败 {exc}")
            return
        if not data:
            self.drop_client(c, "对端关闭")
            return
        c.rx += len(data)
        if c.codec is None:
            self.decide_proto(c, data)
        to_board, reply = c.codec.decode(data)
        notes = getattr(c.codec, "notes", None)
        if notes:
            self.log("[hub] {} 协商：{}".format(c.name, " | ".join(notes)))
            del notes[:]
        if reply:
            # telnet 协商应答：只回给提出协商的那条连接，绝不写进串口
            c.feed_raw(reply)
            self.log(f"[hub] {c.name} 协议应答 {esc(reply)}（未转发给串口）")
        eaten = len(data) - len(to_board)
        if eaten > 0:
            c.drop_proto += eaten
        if to_board:
            self.client_to_serial(c, to_board)

    def decide_proto(self, c: Client, first: bytes) -> None:
        """首字节嗅探：0xFF = Telnet IAC；其余按 raw。"""
        if c.proto_locked:
            c.flush_held_out()
            return
        if first[:1] == b"\xff":
            c.use_proto("telnet")
            why = "首字节 0xFF"
        else:
            c.use_proto("raw")
            why = f"首字节 0x{first[0]:02x}"
        c.flush_held_out()
        self.log(f"[hub] {c.name} 协议判定 -> {c.proto}（{why}）")

    def decide_pending_protos(self) -> None:
        """迟迟不开口的连接不能一直等：超时按 raw。"""
        now = time.time()
        for c in list(self.clients.values()):
            if c.codec is None and (now - c.since) >= self.args.sniff_timeout:
                c.use_proto("raw")
                c.flush_held_out()
                self.log(f"[hub] {c.name} {self.args.sniff_timeout:.1f}s 没开口，按 raw 处理")

    def handle_client_write(self, c: Client) -> None:
        data = c.take_out()
        if not data:
            return
        try:
            sent = c.sock.send(data)
        except BlockingIOError:
            c.push_front(data)
            return
        except OSError as exc:
            self.drop_client(c, f"写入失败 {exc}")
            return
        if sent < len(data):
            c.push_front(data[sent:])

    def client_to_serial(self, c: Client, data: bytes) -> None:
        # 内联控制命令（以 @@ 开头的行）
        if c.linebuf or (self.prefix and data.startswith(self.prefix)):
            # telnet 前端会把 Enter 规整成 CR，这里统一成行尾处理
            c.linebuf += data.replace(b"\r", b"\n")
            while b"\n" in c.linebuf:
                line, _, rest = c.linebuf.partition(b"\n")
                c.linebuf = rest
                cmd = line.decode("utf-8", "replace").strip()
                if not cmd.startswith(self.args.control_prefix):
                    self.push_tx(line + b"\r", c)  # 不是已知前缀就当普通数据放行
                    continue
                reply = self.command(cmd[len(self.args.control_prefix) :].strip(), source="inline", client=c)
                if reply:
                    c.feed(("\r\n" + reply + "\r\n").encode())
                    self.log_data("CTL", c.name, reply.encode())
            return
        self.push_tx(data, c)

    def push_tx(self, data: bytes, c: Client) -> bool:
        """客户端 -> 设备（带写锁仲裁）。返回是否真的进了发送队列。"""
        return self.send(data, who=c.name, owner_cid=c.cid)

    def send(self, data: bytes, who: str = "tui", owner_cid=None) -> bool:
        """任何来源把字节发往设备的**唯一入口**（客户端 / TUI / 将来的别的 UI）。

        `owner_cid=None` 表示"不是某个客户端发起的"（例如 TUI 自己敲的），
        但**写锁是全局的**：只要有人 `@@lock` 了，谁都得排队，UI 不例外。
        """
        if not data:
            return False
        if self.args.lock_writes and self.owner_cid is not None and owner_cid != self.owner_cid:
            self.drop_locked += len(data)
            self.log(f"[hub] 丢弃 {who} 的 {len(data):d} 字节（写锁在 {self.owner_name()} 手上）")
            return False
        try:
            self.tx.put_nowait((data, who))
            return True
        except queue.Full:
            self.log(f"[hub] 发送队列满，丢弃 {who} 的 {len(data):d} 字节")
            return False

    def owner_name(self) -> str:
        """写锁持有者的人话名字；没人持锁时是「无」（不是「已离开」）。"""
        if not self.owner_cid:
            return "无"
        c = self.clients.get(self.owner_cid)
        return c.name if c else "(已离开)"
