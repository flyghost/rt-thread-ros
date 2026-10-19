"""串口生命周期与两个 IO 线程。

拆自 core/relay.py 的 SerialHub（逻辑未改，只换容器）。
"""

from __future__ import annotations

import os
import queue
import sys
import time
from datetime import datetime

try:
    import serial
except Exception as exc:  # pragma: no cover
    print(f"需要 pyserial：pip install pyserial  （导入失败：{exc}）", file=sys.stderr)
    raise SystemExit(2) from exc  # 缺依赖属于部署错误，保留原因链

import contextlib
from pathlib import Path

from core.events import EV_RX, EV_TX, Event
from core.hub_base import HubBase


class SerialMixin(HubBase):
    """串口生命周期与两个 IO 线程。"""

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
                write_timeout=a.write_timeout,  # 关键：没有它会永久阻塞（老脚本就栽在这）
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
        except Exception as exc:
            if not quiet:
                print(f"[hub] 打开 {a.com} 失败：{exc}", file=sys.stderr)
            return False
        if a.dtr_open != "keep":
            with contextlib.suppress(Exception):
                ser.dtr = a.dtr_open == "high"
        with self.ser_lock:
            self.ser = ser
            self.ser_ok = True
        self.log("[hub] 已独占 %s @ %d 8N1（write_timeout=%ss）" % (a.com, a.baud, a.write_timeout))
        return True

    def drop_serial(self, why: str) -> None:
        with self.ser_lock:
            ser, self.ser, self.ser_ok = self.ser, None, False
        if ser is not None:
            with contextlib.suppress(Exception):
                ser.close()
            self.log(f"[hub] 串口已释放（{why}）")

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
            self.log(f"[hub] 串口重连失败，{self.args.reopen_delay}s 后再试")

    def serial_error(self, exc: Exception) -> None:
        self.drop_serial(f"IO 异常 {exc}")
        self.last_open_try = time.time()

    def open_logs(self) -> None:
        if not self.args.log:
            return
        os.makedirs(self.args.log_dir, exist_ok=True)
        stem = os.path.join(self.args.log_dir, "serial-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
        # 二进制留档：用默认块缓冲 + 每段写完 flush，保证进程还在跑时也能 tail 到内容
        self.raw_f = Path(stem + ".raw").open("wb")  # noqa: SIM115 - 长驻句柄，由 close_logs() 关闭
        self.log_f = Path(stem + ".log").open("w", encoding="utf-8", newline="")  # noqa: SIM115
        self.log_stem = stem
        self.log(f"[hub] 日志：{stem}.log / {stem}.raw")

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
                self.log(
                    "[hub] 写超时（%ss），丢弃 %d 字节：目标可能在等流控或已停"
                    % (self.args.write_timeout, len(data))
                )
            except Exception as exc:
                self.serial_error(exc)

    def do_reset(self, mode: str) -> None:
        active_high = self.args.reset_active == "high"
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
                self.log(
                    f"[hub] 已发送 {mode} 复位脉冲（active={self.args.reset_active}，{self.args.reset_pulse}s）"
                )
            except Exception as exc:
                self.log(f"[hub] 复位失败：{exc}")
