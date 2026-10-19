#!/usr/bin/env python3
"""离线自检：事件层 + 内置 sink 的行为（**不需要串口 / COM 口**）。

这是"把渲染搬进 sink"（TUI 第 1 步）的回归测试：直接构造 hub 的输出侧，
喂事件进去，断言 `.raw` / `.log` / 本窗口输出与重构前的格式一致。

跑法：python scripts/serial_hub/tests/sink_check.py
"""

# __pycache__ 统一写到仓库 out/pycache：仓库根由本文件位置直接推出（parents[3]），不做搜索
import sys as _sys
from pathlib import Path as _Path

_sys.pycache_prefix = str(_Path(__file__).resolve().parents[3] / "out" / "pycache")

import argparse  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from contextlib import redirect_stdout, suppress  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # scripts/serial_hub

from pathlib import Path  # noqa: E402

from core.events import EV_RX, EV_TX, Event  # noqa: E402
from core.relay import SerialHub  # noqa: E402
from core.util import repo_root  # noqa: E402

# 日志落在仓库内的 out/tmp（不碰系统临时目录：有些环境里它不可写）
_TMPROOT = os.path.join(repo_root(), "out", "tmp")
_TMPDIRS = []
_TMPSEQ = [0]
_HUBS = []


def _new_tmpdir():
    """建一个本次测试专用的日志目录。

    不能用 tempfile.mkdtemp()：它按 0o700 建目录，在本机（Windows + 沙箱 ACL）
    下会导致目录内 open(..., "wb") 报 PermissionError [Errno 13]。
    目录名带自增序号：同一秒内多个 hub 不能共用同一份日志文件。
    """
    _TMPSEQ[0] += 1
    d = os.path.join(_TMPROOT, f"sink-check-{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid():d}-{_TMPSEQ[0]:d}")
    os.makedirs(d, exist_ok=True)
    _TMPDIRS.append(d)
    return d


def make_args(log=True, stdout="rx", log_dir=None):
    os.makedirs(_TMPROOT, exist_ok=True)
    a = argparse.Namespace()
    a.com = "COM_TEST"
    a.baud = 115200
    a.host = "127.0.0.1"
    a.port = 5555
    a.telnet_port = 5557
    a.control_port = 5556
    a.sniff = True
    a.sniff_timeout = 0.5
    a.allow_lan = False
    a.stdout = stdout
    a.log = log
    if log_dir is None:
        log_dir = _new_tmpdir()
    a.log_dir = log_dir
    a.read_timeout = 0.05
    a.write_timeout = 1.0
    a.tx_queue = 512
    a.dtr_open = "keep"
    a.reset_mode = "dtr"
    a.reset_active = "low"
    a.reset_pulse = 0.1
    a.reopen = True
    a.reopen_delay = 2.0
    a.lock_writes = True
    a.control_prefix = "@@"
    a.prefer = []
    return a


def new_hub(stdout="rx", log=True):
    hub = SerialHub(make_args(log=log, stdout=stdout))
    hub.open_logs()
    _HUBS.append(hub)
    return hub


def read_bytes(path):
    with Path(path).open("rb") as f:
        return f.read()


class FakeSink:
    """只记录事件的假 sink —— 证明"换 UI"只需要实现这三个方法。"""

    def __init__(self):
        self.events = []
        self.states = []
        self.closed = False

    def on_event(self, ev):
        self.events.append(ev)

    def on_state(self, st):
        self.states.append(st)

    def close(self):
        self.closed = True


class Boom:
    """故意抛异常的 sink —— 证明它不会影响别人、也不会影响 hub。"""

    def on_event(self, ev):
        raise RuntimeError("boom")

    def on_state(self, st):
        raise RuntimeError("boom")

    def close(self):
        raise RuntimeError("boom")


def main():
    failed = []

    def check(name, got, want):
        good = got == want
        if not good:
            failed.append(name)
        print("  [{}] {}".format("OK  " if good else "FAIL", name))
        if not good:
            print(f"        got  = {got!r}")
            print(f"        want = {want!r}")

    # ---------------- 1. 落盘：.raw 只含 RX，.log 双向 + hub 消息 ----------------
    print("=== 1. LogSink：.raw / .log ===")
    hub = new_hub(stdout="none")
    with redirect_stdout(io.StringIO()):
        hub.log("[hub] 落盘测试")
        hub.emit(Event(kind=EV_RX, direction="RX", who="board", data=b"hello\r\n"))
        hub.emit(Event(kind=EV_TX, direction="TX", who="#1 raw", data=b"version\r"))
    log_text = read_bytes(hub.log_stem + ".log").decode("utf-8")
    check(".raw 只含 设备->PC 的字节", read_bytes(hub.log_stem + ".raw"), b"hello\r\n")
    check(".log 含 RX 行", "RX board hello\\r" in log_text, True)
    check(".log 含 TX 行", "TX #1 raw version\\r" in log_text, True)
    check(".log 含 hub 消息", "[hub] 落盘测试" in log_text, True)
    # esc() 只转义 \r，真换行保留成多行（每行带时间戳），所以多行数据 = 多行日志
    with redirect_stdout(io.StringIO()):
        hub.emit(Event(kind=EV_RX, direction="RX", who="board", data=b"a\r\nb\r\n"))
    lines = [ln for ln in read_bytes(hub.log_stem + ".log").decode("utf-8").splitlines() if "RX board" in ln]
    check(".log 按行切分（两行数据 -> 三行日志）", len(lines), 3)

    # ---------------- 2. --no-log：什么都不写 ----------------
    print("=== 2. --no-log ===")
    hub2 = new_hub(stdout="none", log=False)
    with redirect_stdout(io.StringIO()):
        hub2.log("[hub] 不落盘")
        hub2.emit(Event(kind=EV_RX, direction="RX", who="board", data=b"x"))
    check("--no-log 时 log_f 为 None", hub2.log_f, None)
    check("--no-log 时 raw_f 为 None", hub2.raw_f, None)

    # ---------------- 3. --stdout 四种语义 ----------------
    print("=== 3. StreamSink：--stdout rx / rxtx / hex / none ===")
    hub = new_hub(stdout="rx")
    buf = io.StringIO()
    with redirect_stdout(buf):
        hub.emit(Event(kind=EV_RX, direction="RX", who="board", data=b"hello\r\n"))
        hub.emit(Event(kind=EV_TX, direction="TX", who="#1", data=b"version\r"))
    out = buf.getvalue()
    check("rx：RX 文本被打印", "hello" in out, True)
    check("rx：TX 不打印", "version" in out, False)

    hub = new_hub(stdout="rxtx")
    buf = io.StringIO()
    with redirect_stdout(buf):
        hub.emit(Event(kind=EV_RX, direction="RX", who="board", data=b"hello\r\n"))
        hub.emit(Event(kind=EV_TX, direction="TX", who="#1", data=b"version\r"))
    out = buf.getvalue()
    check("rxtx：RX 文本被打印", "hello" in out, True)
    check("rxtx：TX 带 >>> 前缀", ">>> version" in out, True)

    hub = new_hub(stdout="hex")
    buf = io.StringIO()
    with redirect_stdout(buf):
        hub.emit(Event(kind=EV_RX, direction="RX", who="board", data=b"0123456789"))
        hub.emit(Event(kind=EV_TX, direction="TX", who="#1", data=b"version\r"))
    out = buf.getvalue()
    check("hex：RX 出 hex（含 8 字节空档）", "30 31 32 33 34 35 36 37  38 39" in out, True)
    check("hex：TX 不进 hex 视图", "76 65 72" in out, False)

    hub = new_hub(stdout="none")
    buf = io.StringIO()
    with redirect_stdout(buf):
        hub.emit(Event(kind=EV_RX, direction="RX", who="board", data=b"hello"))
        hub.emit(Event(kind=EV_TX, direction="TX", who="#1", data=b"version"))
    check("none：数据一律不打印", buf.getvalue(), "")

    hub = new_hub(stdout="none")
    buf = io.StringIO()
    with redirect_stdout(buf):
        hub.log("[hub] 关键消息")
        hub.log("[client] 普通消息")
    out = buf.getvalue()
    check("none：仍打 [hub] 开头消息", "[hub] 关键消息" in out, True)
    check("none：非 [hub] 消息不打", "[client] 普通消息" in out, False)

    # ---------------- 4. 多 sink / 出错隔离 / 状态推送 ----------------
    print("=== 4. SinkGroup：多 sink、出错隔离、状态推送 ===")
    hub = new_hub(stdout="none")
    fake = FakeSink()
    hub.sinks.add(fake)
    hub.sinks.add(Boom())
    with redirect_stdout(io.StringIO()):
        hub.emit(Event(kind=EV_RX, direction="RX", who="board", data=b"abc"))
    check("假 sink 收到事件（= 换 UI 只需三个方法）", len(fake.events), 1)
    check("假 sink 收到的 data 与 hub 广播的原始字节一致", fake.events[0].data, b"abc")
    check("坏 sink 只累加错误计数", hub.sinks.errors >= 1, True)

    hub2 = new_hub(stdout="none")
    fake2 = FakeSink()
    hub2.sinks.add(fake2)
    with redirect_stdout(io.StringIO()):
        hub2.mark_state()
        check("mark_state 只置脏、不立即推送", len(fake2.states), 0)
        hub2.emit_state()
    st = fake2.states[0]
    check("快照含串口/计数/会话", (st["com"], st["baud"], st["sessions"]), ("COM_TEST", 115200, []))

    hub.sinks.close()
    check("SinkGroup.close 逐个调用（坏 sink 不致命）", hub.sinks.errors >= 1, True)

    print()
    if failed:
        print(f"FAILED({len(failed):d})：{', '.join(failed)}")
        return 1
    print("全部通过（事件层 + 两个 sink 的行为与重构前一致）")
    return 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        for h in _HUBS:  # 先关掉日志句柄（Windows 上不关就删不掉目录）
            with suppress(Exception):
                h.sinks.close()
            for f in (getattr(h, "log_f", None), getattr(h, "raw_f", None)):
                try:
                    if f:
                        f.close()
                except Exception:
                    pass
        for d in _TMPDIRS:  # 再清掉本次的临时日志目录
            shutil.rmtree(d, ignore_errors=True)
    sys.exit(code)
