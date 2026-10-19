"""控制口命令实现（读 hub 状态，所以需要整块访问）。

拆自 core/relay.py 的 SerialHub（逻辑未改，只换容器）。
"""

from __future__ import annotations

import sys
import threading
import time

try:
    pass
except Exception as exc:  # pragma: no cover
    print(f"需要 pyserial：pip install pyserial  （导入失败：{exc}）", file=sys.stderr)
    raise SystemExit(2) from exc  # 缺依赖属于部署错误，保留原因链


from protocols import CODECS

from core.hub_base import HubBase
from core.session import Client
from core.util import human


class CommandsMixin(HubBase):
    """控制口命令实现（读 hub 状态，所以需要整块访问）。"""

    def command(self, cmd: str, source: str, client: Client | None) -> str:
        a = self.args
        cmd = (cmd or "").strip()
        if not cmd:
            return ""
        parts = cmd.split()
        verb = parts[0].lower()
        rest = parts[1:]

        if verb in ("help", "?"):
            return (
                "# 命令：help | status | sessions(clients) | lock [cid] | unlock "
                "| proto <cid> <raw|telnet> | kill <cid> | reset [dtr|rts|both] | "
                "shutdown | ping     数据口内联：@@lock/@@unlock/@@proto/@@whoami"
            )
        if verb == "ping":
            return "# pong"
        if verb == "status":
            up = time.time() - self.started
            return "# 串口=%s@%d %s 运行=%s 重连=%d 会话=%d 写锁=%s 收=%s 发=%s 丢弃(锁)=%s 协议层吃掉=%s" % (  # noqa: UP031
                a.com,
                a.baud,
                "OK" if self.ser_ok else "断开",
                f"{int(up):d}秒",
                self.reopen_count,
                len(self.clients),
                self.owner_name(),
                human(self.rx_bytes),
                human(self.tx_bytes),
                human(self.drop_locked),
                human(self.drop_proto),
            )
        if verb in ("clients", "sessions"):
            if not self.clients:
                return "# 暂无会话"
            rows = []
            now = time.time()
            for c in sorted(self.clients.values(), key=lambda x: x.cid):
                rows.append(
                    "# %d proto=%-6s %s 会话=%ds 收=%s 发=%s 协议层吃掉=%s%s"  # noqa: UP031
                    % (
                        c.cid,
                        c.proto or "?",
                        c.name,
                        int(now - c.since),
                        human(c.rx),
                        human(c.tx),
                        human(c.drop_proto),
                        "  <=写锁" if c.cid == self.owner_cid else "",
                    )
                )
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
                return f"# err: 没有客户端 {target:d}"
            self.owner_cid = target
            self.mark_state()
            self.log(f"[hub] 写锁 -> {self.clients[target].name}")
            return f"# ok: 写锁已给 {self.clients[target].name}"
        if verb == "unlock":
            if self.owner_cid is None:
                return "# ok: 当前没有写锁"
            was = self.owner_name()
            self.owner_cid = None
            self.mark_state()
            self.log(f"[hub] 写锁解除（原持有者 {was}）")
            return f"# ok: 写锁已解除（原持有者 {was}）"
        if verb == "reset":
            mode = rest[0].lower() if rest else a.reset_mode
            if mode not in ("dtr", "rts", "both"):
                return "# err: reset 参数要是 dtr|rts|both"
            t = threading.Thread(target=self.do_reset, args=(mode,), daemon=True)
            t.start()
            return f"# ok: 已按 {mode} 发复位脉冲（{a.reset_pulse} 秒）"
        if verb == "whoami":
            if client is None:
                return "# 控制口连接（不属于数据会话；用 sessions 看会话号）"
            return "# 我是 %s 协议=%s 会话=%ds" % (  # noqa: UP031
                client.name,
                client.proto or "?",
                int(time.time() - client.since),
            )
        if verb == "proto":
            if client is not None and len(rest) == 1:
                rest = [str(client.cid), rest[0]]  # 数据口 @@proto telnet
            if len(rest) < 2:
                return "# err: proto <cid> <raw|telnet>（数据口可省略 cid）"
            try:
                target = int(rest[0])
            except ValueError:
                return "# err: proto 第一个参数要是会话号（sessions）"
            name = rest[1].lower()
            if name not in CODECS:
                return "# err: 不支持的协议 {!r}（可选 {}）".format(name, "/".join(sorted(CODECS)))
            c = self.clients.get(target)
            if c is None:
                return f"# err: 没有会话 {target:d}"
            c.use_proto(name)
            c.flush_held_out()
            self.log(f"[hub] 会话 {c.name} 协议切换 -> {name}")
            return f"# ok: {c.name} 协议 = {name}"
        if verb == "kill":
            if not rest:
                return "# err: kill <cid>（见 sessions）"
            try:
                target = int(rest[0])
            except ValueError:
                return "# err: kill 参数要是会话号"
            c = self.clients.get(target)
            if c is None:
                return f"# err: 没有会话 {target:d}"
            name = c.name
            self.drop_client(c, "被控制口踢出")
            return f"# ok: 已断开 {name}"
        if verb in ("shutdown", "quit", "exit"):
            if source != "control":
                return "# err: 只有控制口能 shutdown"
            self.log("[hub] 控制口要求退出")
            self.running = False
            return "# bye"
        return f"# err: 未知命令 {verb!r}（help）"
