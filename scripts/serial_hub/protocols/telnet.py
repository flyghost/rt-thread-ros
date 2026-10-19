#!/usr/bin/env python3
"""telnet：最小 Telnet 服务端（协商只同意 ECHO / SGA，IAC 绝不转发给设备）。

给"只有 Telnet 会话类型、不会说 Raw"的终端用：它一连上会先发一串 IAC
（NAWS / TERMINAL-TYPE / DO ECHO ...），这些字节必须在这里被吃掉，否则设备把它们
回显回来、客户端又当协商解析，两边状态机打架 —— 表现就是满屏 "^M^M^M help ^M"。
"""

from __future__ import annotations

from .base import Codec


class TelnetCodec(Codec):
    """最小 Telnet 服务端。协商只同意两件事：ECHO 与 SGA。

        IAC DO   ECHO(1) -> IAC WILL ECHO(1)   服务器回显（finsh 本来就在回显）
        IAC DO   SGA(3)  -> IAC WILL SGA(3)    抑制 GA，全双工
        IAC WILL SGA(3)  -> IAC DO   SGA(3)    同上，双向
        IAC WILL ECHO(1) -> IAC DONT ECHO(1)   不要客户端自己回显（那会变成本地回显）
        其它 WILL x -> DONT x；DO x -> WONT x；WONT/DONT x -> 对等拒绝
        IAC SB ... IAC SE -> 整段丢弃；IAC IAC -> 字面 0xFF；其它 IAC 丢弃

    ★ 协商字节一律不回送给设备 —— 客户端满屏 ^M 就是协商被当成数据回显造成的。

    行尾规范化（NVT 要求 CR 后面必须是 LF 或 NUL）：
        客户端 -> 设备：CR LF / CR NUL 折叠成一个 CR；单独 LF 当 CR
        设备 -> 客户端：CR LF 原样；单独 CR -> CR NUL；单独 LF -> CR LF；
                       字面 0xFF 翻倍成 FF FF
    """

    name = "telnet"

    IAC = 255
    DONT = 254
    DO = 253
    WONT = 252
    WILL = 251
    SB = 250
    SE = 240
    ECHO = 1
    SGA = 3
    OPT_NAMES = {
        0: "BINARY",
        1: "ECHO",
        3: "SGA",
        5: "STATUS",
        24: "TTYPE",
        31: "NAWS",
        32: "TSPEED",
        34: "LINEMODE",
        39: "NEW-ENVIRON",
    }

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self._st = "data"  # data | iac | opt | sb | sb_iac
        self._cmd = 0
        self._last_cr = False  # 客户端方向：上一个字节是 CR
        self.notes = []  # 协商轨迹（人类可读），由 hub 打日志

    def decode(self, data: bytes) -> tuple[bytes, bytes]:
        out = bytearray()
        reply = bytearray()
        for b in data:
            st = self._st
            if st == "sb":
                if b == self.IAC:
                    self._st = "sb_iac"
                continue
            if st == "sb_iac":
                self._st = "data" if b == self.SE else "sb"
                continue
            if st == "iac":
                if b == self.IAC:  # IAC IAC = 字面 0xFF
                    self._st = "data"
                    out += bytes((b,))
                    continue
                if b in (self.WILL, self.WONT, self.DO, self.DONT):
                    self._cmd = b
                    self._st = "opt"
                    continue
                if b == self.SB:
                    self._st = "sb"
                    continue
                self._st = "data"  # NOP/DM/BRK/AYT/GA：丢掉
                continue
            if st == "opt":
                self._reply_opt(reply, self._cmd, b)
                self._st = "data"
                self._cmd = 0
                continue
            # 普通数据
            if b == self.IAC:
                self._st = "iac"
                self._last_cr = False
                continue
            if self._last_cr and b in (0x0A, 0x00):  # CR LF / CR NUL -> 一个 Enter
                self._last_cr = False
                continue
            self._last_cr = b == 0x0D
            out += bytes((b,))
        return bytes(out), bytes(reply)

    def encode(self, data: bytes) -> bytes:
        """串口 -> 客户端：转成 NVT 合法流（CR 后面必须有 LF 或 NUL）。

        注意不要"补 CR"：设备发的是 CR LF，原来那版会变成 CR CR LF，
        Telnet 客户端把多出来的那个裸 CR 显示成 ^M。
        """
        out = bytearray()
        i = 0
        n = len(data)
        while i < n:
            b = data[i]
            if b == 0x0D:
                if i + 1 < n and data[i + 1] == 0x0A:
                    out += b"\r\n"  # CR LF 原样（不重复补 CR）
                    i += 2
                else:
                    out += b"\r\x00"  # 单独 CR -> CR NUL（NVT 合法）
                    i += 1
            elif b == 0x0A:
                out += b"\r\n"  # 单独 LF -> CR LF
                i += 1
            elif b == 0xFF:
                out += b"\xff\xff"  # Telnet：字面 0xFF 要翻倍
                i += 1
            else:
                out += bytes((b,))
                i += 1
        return bytes(out)

    def greeting(self) -> bytes:
        """telnet 口一建立就把立场说清楚，别等客户端先问。"""
        return bytes(
            (self.IAC, self.WILL, self.ECHO, self.IAC, self.WILL, self.SGA, self.IAC, self.DO, self.SGA)
        )

    def _oname(self, opt: int) -> str:
        return self.OPT_NAMES.get(opt, "opt%d" % opt)

    def _send(self, reply: bytearray, cmd: int, opt: int) -> None:
        reply += bytes((self.IAC, cmd, opt))

    def _reply_opt(self, reply: bytearray, cmd: int, opt: int) -> None:
        if cmd == self.DO and opt == self.ECHO:
            self._send(reply, self.WILL, opt)
            note = "DO ECHO -> WILL ECHO（服务器回显）"
        elif cmd == self.DO and opt == self.SGA:
            self._send(reply, self.WILL, opt)
            note = "DO SGA -> WILL SGA（全双工）"
        elif cmd == self.WILL and opt == self.SGA:
            self._send(reply, self.DO, opt)
            note = "WILL SGA -> DO SGA（全双工）"
        elif cmd == self.WILL:
            self._send(reply, self.DONT, opt)
            note = f"WILL {self._oname(opt)} -> DONT"
        elif cmd == self.WONT:
            self._send(reply, self.DONT, opt)
            note = f"WONT {self._oname(opt)} -> DONT"
        elif cmd == self.DO:
            self._send(reply, self.WONT, opt)
            note = f"DO {self._oname(opt)} -> WONT"
        else:
            self._send(reply, self.WONT, opt)
            note = f"DONT {self._oname(opt)} -> WONT"
        self.notes.append(note)
