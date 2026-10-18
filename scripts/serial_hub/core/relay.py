#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SerialHub：唯一持有串口的那个进程。

职责：独占串口（open/drop/重连）、selector 主循环、把串口字节广播给所有会话
（各会话用自己的 codec encode）、写方向仲裁（owner_cid 写锁）、掉线重连、日志落盘。
控制口本身在 core/control.py；命令实现（help/status/sessions/lock/proto/kill/reset）
留在这里的 `command()`，因为它要读 hub 状态。
"""
from __future__ import annotations


import os
import queue
import selectors
import socket
import sys
import threading
import time
from datetime import datetime

try:
    import serial
except Exception as exc:  # pragma: no cover
    print("需要 pyserial：pip install pyserial  （导入失败：%s）" % exc, file=sys.stderr)
    raise SystemExit(2)

from core.control import ControlServer
from core.events import EV_HUB, EV_RX, EV_TX, Event, SinkGroup
from core.logstore import esc, hexdump_text, sync
from core.session import Client
from core.sinks import LogSink, StreamSink
from core.util import human, ts
from protocols import CODECS

SEL_READ = selectors.EVENT_READ
SEL_WRITE = selectors.EVENT_WRITE


class SerialHub:
    def __init__(self, args):
        self.args = args
        self.ser = None
        self.ser_lock = threading.RLock()
        self.ser_ok = False
        self.last_open_try = 0.0
        self.reopen_count = 0
        self.clients: dict[int, Client] = {}
        self.next_cid = 1
        self.owner_cid = None       # 持有写权限的客户端（None = 谁都能写）
        self.tx: "queue.Queue[tuple[bytes, str]]" = queue.Queue(maxsize=args.tx_queue)
        self.running = True
        self.started = time.time()
        self.rx_bytes = 0
        self.tx_bytes = 0
        self.drop_locked = 0
        self.log_lock = threading.Lock()
        self.print_lock = threading.Lock()
        self.raw_f = None
        self.log_f = None
        self.log_stem = None
        self.sel = selectors.DefaultSelector()
        self.srv = None
        self.tsrv = None
        self.ctl = None
        self.drop_proto = 0
        self.prefix = args.control_prefix.encode() if args.control_prefix else b""
        # ---- 输出层：hub 只"发事件"，落盘 / 本窗口 / UI 都是 sink ----
        # ui=tui 时用 TuiApp 取代本窗口输出（日志 sink 照旧，协议层完全不受影响）
        self.tui = None
        sinks = [LogSink(self)]
        if getattr(args, "ui", "stream") == "tui":
            from tui.app import TuiApp                # 只有选了 TUI 才会 import

            self.tui = TuiApp(self, mode="hex" if getattr(args, "stdout", "rx") == "hex" else "text")
            sinks.append(self.tui)
        elif getattr(args, "ui", "stream") == "stream":
            sinks.append(StreamSink(self))
        self.sinks = SinkGroup(sinks)
        self._state_dirty = False

    # ---------------- 串口 ----------------
    def open_serial(self, quiet=False) -> bool:
        a = self.args
        try:
            ser = serial.Serial(
                port=a.com,
                baudrate=a.baud,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=a.read_timeout,
                write_timeout=a.write_timeout,   # 关键：没有它会永久阻塞（老脚本就栽在这）
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
        except Exception as exc:
            if not quiet:
                print("[hub] 打开 %s 失败：%s" % (a.com, exc), file=sys.stderr)
            return False
        if a.dtr_open != "keep":
            try:
                ser.dtr = (a.dtr_open == "high")
            except Exception:
                pass
        with self.ser_lock:
            self.ser = ser
            self.ser_ok = True
        self.log("[hub] 已独占 %s @ %d 8N1（write_timeout=%ss）" % (a.com, a.baud, a.write_timeout))
        return True

    def drop_serial(self, why: str) -> None:
        with self.ser_lock:
            ser, self.ser, self.ser_ok = self.ser, None, False
        if ser is not None:
            try:
                ser.close()
            except Exception:
                pass
            self.log("[hub] 串口已释放（%s）" % why)

    def try_reopen(self) -> None:
        if not self.args.reopen:
            return
        now = time.time()
        if now - self.last_open_try < self.args.reopen_delay:
            return
        self.last_open_try = now
        if self.open_serial(quiet=True):
            self.reopen_count += 1
            self.log("[hub] 串口重连成功（第 %d 次）" % self.reopen_count)
        else:
            self.log("[hub] 串口重连失败，%ss 后再试" % self.args.reopen_delay)

    def serial_error(self, exc: Exception) -> None:
        self.drop_serial("IO 异常 %s" % exc)
        self.last_open_try = time.time()

    # ---------------- 日志 ----------------
    def open_logs(self) -> None:
        if not self.args.log:
            return
        os.makedirs(self.args.log_dir, exist_ok=True)
        stem = os.path.join(self.args.log_dir,
                            "serial-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        # 二进制留档：用默认块缓冲 + 每段写完 flush，保证进程还在跑时也能 tail 到内容
        self.raw_f = open(stem + ".raw", "wb")
        self.log_f = open(stem + ".log", "w", encoding="utf-8", newline="")
        self.log_stem = stem
        self.log("[hub] 日志：%s.log / %s.raw" % (stem, stem))

    def log(self, text: str) -> None:
        """hub 自身消息：排版一次，交给 sink（落盘 / 条件打印本窗口）。"""
        self.emit(Event(kind=EV_HUB, msg=text, text="[%s] %s" % (ts(), text)))

    # ---------------- 事件出口（sink 实现见 core/sinks.py） ----------------
    def emit(self, ev: Event) -> None:
        self.sinks.emit(ev)

    def mark_state(self) -> None:
        """标记状态变了：下一次 tick 推送一次快照（无 UI 的 sink 会忽略）。"""
        self._state_dirty = True

    def emit_state(self) -> None:
        self.sinks.state(self.snapshot())

    def log_data(self, direction: str, who: str, data: bytes) -> None:
        """兼容旧调用点：等价于发一个方向事件（落盘由 LogSink 完成）。"""
        self.emit(Event(kind=EV_RX if direction == "RX" else EV_TX,
                        direction=direction, who=who, data=data))

    def out_console(self, direction: str, who: str, data: bytes) -> None:
        """兼容旧调用点：等价于发一个方向事件（窗口渲染由 StreamSink 完成）。"""
        self.emit(Event(kind=EV_RX if direction == "RX" else EV_TX,
                        direction=direction, who=who, data=data))

    # ---------------- 数据口 ----------------
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
            print("[hub] 数据口绑定 %s:%d 失败：%s" % (host, a.port, exc), file=sys.stderr)
            return False
        self.log("[hub] 数据口  %s:%d  raw%s"
                 % (a.host, a.port,
                    "（首字节 0xFF 自动切 telnet）" if a.sniff else "（不做嗅探）"))
        if a.telnet_port:
            try:
                self.tsrv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.tsrv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.tsrv.bind((host, a.telnet_port))
                self.tsrv.listen(16)
                self.tsrv.setblocking(False)
                self.sel.register(self.tsrv, SEL_READ, ("tsrv", None))
                self.log("[hub] telnet 口 %s:%d  （Telnet 前端）"
                         % (a.host, a.telnet_port))
            except OSError as exc:
                print("[hub] telnet 口绑定 %s:%d 失败（继续跑）：%s"
                      % (host, a.telnet_port, exc), file=sys.stderr)
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
        c = Client(conn, addr, self.next_cid,
                   proto=None if self.args.sniff else "raw",
                   locked=not self.args.sniff)
        self.next_cid += 1
        self.clients[c.cid] = c
        self.sel.register(conn, SEL_READ, ("data", c))
        self.log("[hub] 客户端接入 %s（当前 %d 个，协议=%s）"
                 % (c.name, len(self.clients), c.proto or "待嗅探"))
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
            self.log("[hub] %s 主动协商 %s（WILL ECHO / WILL SGA / DO SGA，未转发给串口）"
                     % (c.name, esc(greet)))
        self.log("[hub] 客户端接入 %s（当前 %d 个，telnet 口）"
                 % (c.name, len(self.clients)))
        self.mark_state()

    def drop_client(self, c: Client, why: str = "断开") -> None:
        if c.cid not in self.clients:
            return
        self.clients.pop(c.cid, None)
        try:
            self.sel.unregister(c.sock)
        except Exception:
            pass
        c.close()
        if self.owner_cid == c.cid:
            self.owner_cid = None
            self.log("[hub] 持有写锁的客户端 %s 已离开，自动解锁" % c.name)
        self.log("[hub] 客户端离开 %s（%s，收 %s 发 %s，剩余 %d 个）"
                 % (c.name, why, human(c.rx), human(c.tx), len(self.clients)))
        self.mark_state()

    def refresh_interest(self) -> None:
        for c in list(self.clients.values()):
            want = SEL_READ | (SEL_WRITE if c.has_out() else 0)
            try:
                self.sel.modify(c.sock, want, ("data", c))
            except Exception:
                pass

    def handle_client_read(self, c: Client) -> None:
        try:
            data = c.sock.recv(65536)
        except BlockingIOError:
            return
        except OSError as exc:
            self.drop_client(c, "读取失败 %s" % exc)
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
            self.log("[hub] %s 协商：%s" % (c.name, " | ".join(notes)))
            del notes[:]
        if reply:
            # telnet 协商应答：只回给提出协商的那条连接，绝不写进串口
            c.feed_raw(reply)
            self.log("[hub] %s 协议应答 %s（未转发给串口）" % (c.name, esc(reply)))
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
            why = "首字节 0x%02x" % first[0]
        c.flush_held_out()
        self.log("[hub] %s 协议判定 -> %s（%s）" % (c.name, c.proto, why))

    def decide_pending_protos(self) -> None:
        """迟迟不开口的连接不能一直等：超时按 raw。"""
        now = time.time()
        for c in list(self.clients.values()):
            if c.codec is None and (now - c.since) >= self.args.sniff_timeout:
                c.use_proto("raw")
                c.flush_held_out()
                self.log("[hub] %s %.1fs 没开口，按 raw 处理"
                         % (c.name, self.args.sniff_timeout))

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
            self.drop_client(c, "写入失败 %s" % exc)
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
                    self.push_tx(line + b"\r", c)   # 不是已知前缀就当普通数据放行
                    continue
                reply = self.command(cmd[len(self.args.control_prefix):].strip(),
                                     source="inline", client=c)
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
            self.log("[hub] 丢弃 %s 的 %d 字节（写锁在 %s 手上）"
                     % (who, len(data), self.owner_name()))
            return False
        try:
            self.tx.put_nowait((data, who))
            return True
        except queue.Full:
            self.log("[hub] 发送队列满，丢弃 %s 的 %d 字节" % (who, len(data)))
            return False

    def owner_name(self) -> str:
        """写锁持有者的人话名字；没人持锁时是「无」（不是「已离开」）。"""
        if not self.owner_cid:
            return "无"
        c = self.clients.get(self.owner_cid)
        return c.name if c else "(已离开)"

    # ---------------- 串口线程 ----------------
    def reader_loop(self) -> None:
        while self.running:
            with self.ser_lock:
                ser = self.ser
            if ser is None:
                self.try_reopen()
                time.sleep(0.1)
                continue
            try:
                data = ser.read(4096)
            except Exception as exc:
                self.serial_error(exc)
                continue
            if not data:
                continue
            self.rx_bytes += len(data)
            self.emit(Event(kind=EV_RX, direction="RX", who="board", data=data))
            for c in list(self.clients.values()):
                c.feed(data)

    def writer_loop(self) -> None:
        while self.running:
            try:
                data, who = self.tx.get(timeout=0.2)
            except queue.Empty:
                continue
            with self.ser_lock:
                ser = self.ser
            if ser is None:
                self.log("[hub] 串口不可用，丢弃 %s 的 %d 字节" % (who, len(data)))
                continue
            try:
                ser.write(data)
                self.tx_bytes += len(data)
                self.emit(Event(kind=EV_TX, direction="TX", who=who, data=data))
            except serial.SerialTimeoutException:
                self.log("[hub] 写超时（%ss），丢弃 %d 字节：目标可能在等流控或已停" 
                         % (self.args.write_timeout, len(data)))
            except Exception as exc:
                self.serial_error(exc)

    # ---------------- 控制命令（服务端在 core/control.py） ----------------
    def command(self, cmd: str, source: str, client: Client | None) -> str:
        a = self.args
        cmd = (cmd or "").strip()
        if not cmd:
            return ""
        parts = cmd.split()
        verb = parts[0].lower()
        rest = parts[1:]

        if verb in ("help", "?"):
            return ("# 命令：help | status | sessions(clients) | lock [cid] | unlock "
                    "| proto <cid> <raw|telnet> | kill <cid> | reset [dtr|rts|both] | "
                    "shutdown | ping     数据口内联：@@lock/@@unlock/@@proto/@@whoami")
        if verb == "ping":
            return "# pong"
        if verb == "status":
            up = time.time() - self.started
            return ("# 串口=%s@%d %s 运行=%s 重连=%d 会话=%d 写锁=%s "
                    "收=%s 发=%s 丢弃(锁)=%s 协议层吃掉=%s"
                    % (a.com, a.baud, "OK" if self.ser_ok else "断开", 
                       "%d秒" % int(up), self.reopen_count, len(self.clients),
                       self.owner_name(), human(self.rx_bytes), human(self.tx_bytes),
                       human(self.drop_locked), human(self.drop_proto)))
        if verb in ("clients", "sessions"):
            if not self.clients:
                return "# 暂无会话"
            rows = []
            now = time.time()
            for c in sorted(self.clients.values(), key=lambda x: x.cid):
                rows.append("# %d proto=%-6s %s 会话=%ds 收=%s 发=%s 协议层吃掉=%s%s"
                            % (c.cid, c.proto or "?", c.name, int(now - c.since),
                               human(c.rx), human(c.tx), human(c.drop_proto),
                               "  <=写锁" if c.cid == self.owner_cid else ""))
            return "\r\n".join(rows)
        if verb == "lock":
            if client is not None:
                target = client.cid
            elif rest:
                try:
                    target = int(rest[0])
                except ValueError:
                    return "# err: lock 参数要是客户端号（见 clients）"
            else:
                return "# err: 控制口 lock 需要 <cid>；数据口请用 @@lock"
            if target not in self.clients:
                return "# err: 没有客户端 %d" % target
            self.owner_cid = target
            self.mark_state()
            self.log("[hub] 写锁 -> %s" % self.clients[target].name)
            return "# ok: 写锁已给 %s" % self.clients[target].name
        if verb == "unlock":
            if self.owner_cid is None:
                return "# ok: 当前没有写锁"
            was = self.owner_name()
            self.owner_cid = None
            self.mark_state()
            self.log("[hub] 写锁解除（原持有者 %s）" % was)
            return "# ok: 写锁已解除（原持有者 %s）" % was
        if verb == "reset":
            mode = (rest[0].lower() if rest else a.reset_mode)
            if mode not in ("dtr", "rts", "both"):
                return "# err: reset 参数要是 dtr|rts|both"
            t = threading.Thread(target=self.do_reset, args=(mode,), daemon=True)
            t.start()
            return "# ok: 已按 %s 发复位脉冲（%s 秒）" % (mode, a.reset_pulse)
        if verb == "whoami":
            if client is None:
                return "# 控制口连接（不属于数据会话；用 sessions 看会话号）"
            return "# 我是 %s 协议=%s 会话=%ds" % (
                client.name, client.proto or "?", int(time.time() - client.since))
        if verb == "proto":
            if client is not None and len(rest) == 1:
                rest = [str(client.cid), rest[0]]      # 数据口 @@proto telnet
            if len(rest) < 2:
                return "# err: proto <cid> <raw|telnet>（数据口可省略 cid）"
            try:
                target = int(rest[0])
            except ValueError:
                return "# err: proto 第一个参数要是会话号（sessions）"
            name = rest[1].lower()
            if name not in CODECS:
                return "# err: 不支持的协议 %r（可选 %s）" % (name, "/".join(sorted(CODECS)))
            c = self.clients.get(target)
            if c is None:
                return "# err: 没有会话 %d" % target
            c.use_proto(name)
            c.flush_held_out()
            self.log("[hub] 会话 %s 协议切换 -> %s" % (c.name, name))
            return "# ok: %s 协议 = %s" % (c.name, name)
        if verb == "kill":
            if not rest:
                return "# err: kill <cid>（见 sessions）"
            try:
                target = int(rest[0])
            except ValueError:
                return "# err: kill 参数要是会话号"
            c = self.clients.get(target)
            if c is None:
                return "# err: 没有会话 %d" % target
            name = c.name
            self.drop_client(c, "被控制口踢出")
            return "# ok: 已断开 %s" % name
        if verb in ("shutdown", "quit", "exit"):
            if source != "control":
                return "# err: 只有控制口能 shutdown"
            self.log("[hub] 控制口要求退出")
            self.running = False
            return "# bye"
        return "# err: 未知命令 %r（help）" % verb

    def do_reset(self, mode: str) -> None:
        active_high = (self.args.reset_active == "high")
        with self.ser_lock:
            ser = self.ser
            if ser is None:
                return
            try:
                lines = []
                if mode in ("dtr", "both"):
                    lines.append(("DTR", ser.setDTR))
                if mode in ("rts", "both"):
                    lines.append(("RTS", ser.setRTS))
                for _, fn in lines:
                    fn(active_high)
                time.sleep(self.args.reset_pulse)
                for _, fn in lines:
                    fn(not active_high)
                self.log("[hub] 已发送 %s 复位脉冲（active=%s，%ss）"
                         % (mode, self.args.reset_active, self.args.reset_pulse))
            except Exception as exc:
                self.log("[hub] 复位失败：%s" % exc)

    # ---------------- 主循环 ----------------
    def tick(self, timeout: float = 0.05) -> None:
        """推进一次事件循环。

        无 UI 的 `run()` 用它；将来的 TUI 也用它 —— 每次 tick 之后就是一次
        「可以重绘」的时机，这样 UI 永远不会和串口侧抢线程。
        """
        if self._state_dirty:
            self._state_dirty = False
            self.emit_state()
        self.refresh_interest()
        self.decide_pending_protos()
        for key, mask in self.sel.select(timeout):
            tag, obj = key.data
            if tag == "srv":
                self.accept_data()
            elif tag == "tsrv":
                self.accept_telnet()
            else:
                c = obj
                if mask & SEL_READ:
                    self.handle_client_read(c)
                if mask & SEL_WRITE and c.cid in self.clients:
                    self.handle_client_write(c)

    def snapshot(self) -> dict:
        """只读快照：UI 渲染 / 自动化断言都吃这个，不直接摸内部结构。"""
        now = time.time()
        sessions = []
        for c in sorted(self.clients.values(), key=lambda x: x.cid):
            sessions.append({
                "cid": c.cid, "proto": c.proto or "?", "name": c.name,
                "addr": "%s:%s" % (c.addr[0], c.addr[1]),
                "since": c.since, "uptime": now - c.since,
                "rx": c.rx, "tx": c.tx, "drop_proto": c.drop_proto,
                "locked": c.cid == self.owner_cid,
            })
        return {
            "com": self.args.com, "baud": self.args.baud,
            "ser_ok": bool(self.ser_ok), "started": self.started,
            "uptime": now - self.started, "reopen": self.reopen_count,
            "clients": len(self.clients), "sessions": sessions,
            "owner": self.owner_name() if self.owner_cid else "",
            "owner_cid": self.owner_cid,
            "rx": self.rx_bytes, "tx": self.tx_bytes,
            "drop_locked": self.drop_locked, "drop_proto": self.drop_proto,
            "log": self.log_stem,
            "sinks": len(self.sinks.sinks), "sink_errors": self.sinks.errors,
        }

    def run(self) -> int:
        a = self.args
        self.open_logs()
        if not self.open_serial():
            if not a.reopen:
                return 2
            self.last_open_try = time.time()
        if not self.start_servers():
            return 2
        self.mark_state()
        self.log("[hub] 就绪。Raw 口 / %s / %d ；Telnet 口 / %s / %s ；控制口 %s"
                 % (a.host, a.port, a.host, a.telnet_port or "关闭",
                    a.control_port or "关闭"))
        threading.Thread(target=self.reader_loop, daemon=True).start()
        threading.Thread(target=self.writer_loop, daemon=True).start()
        try:
            if self.tui is not None:
                self.tui.loop(self)                    # UI 自己驱动 tick + 重画
            else:
                while self.running:
                    self.tick(0.05)
        except KeyboardInterrupt:
            self.log("[hub] Ctrl+C 退出")
        finally:
            self.running = False
            time.sleep(0.1)
            for c in list(self.clients.values()):
                c.close()
            if self.ctl:
                self.ctl.close()
            self.drop_serial("退出")
            self.log("[hub] 结束：收 %s / 发 %s，日志 %s"
                     % (human(self.rx_bytes), human(self.tx_bytes),
                        (self.log_stem or "(未开)")))
            if self.log_f:
                try:
                    self.log_f.close()
                except Exception:
                    pass
            if self.raw_f:
                try:
                    self.raw_f.close()
                except Exception:
                    pass
            self.sinks.close()
        return 0
