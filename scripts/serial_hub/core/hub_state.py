"""状态快照与周期性 tick（心跳、统计、UI 刷新）。

拆自 core/relay.py 的 SerialHub（逻辑未改，只换容器）。
"""

from __future__ import annotations

import sys
import time

try:
    pass
except Exception as exc:  # pragma: no cover
    print(f"需要 pyserial：pip install pyserial  （导入失败：{exc}）", file=sys.stderr)
    raise SystemExit(2) from exc  # 缺依赖属于部署错误，保留原因链


from core.hub_base import SEL_READ, SEL_WRITE, HubBase


class StateMixin(HubBase):
    """状态快照与周期性 tick（心跳、统计、UI 刷新）。"""

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
            sessions.append(
                {
                    "cid": c.cid,
                    "proto": c.proto or "?",
                    "name": c.name,
                    "addr": f"{c.addr[0]}:{c.addr[1]}",
                    "since": c.since,
                    "uptime": now - c.since,
                    "rx": c.rx,
                    "tx": c.tx,
                    "drop_proto": c.drop_proto,
                    "locked": c.cid == self.owner_cid,
                }
            )
        return {
            "com": self.args.com,
            "baud": self.args.baud,
            "ser_ok": bool(self.ser_ok),
            "started": self.started,
            "uptime": now - self.started,
            "reopen": self.reopen_count,
            "clients": len(self.clients),
            "sessions": sessions,
            "owner": self.owner_name() if self.owner_cid else "",
            "owner_cid": self.owner_cid,
            "rx": self.rx_bytes,
            "tx": self.tx_bytes,
            "drop_locked": self.drop_locked,
            "drop_proto": self.drop_proto,
            "log": self.log_stem,
            "sinks": len(self.sinks.sinks),
            "sink_errors": self.sinks.errors,
        }
