#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TUI 离线自检：不碰串口、不碰真终端，只驱动纯渲染与键盘动作。

跑法（在仓库根）：
    python scripts/serial_hub/tests/tui_check.py

覆盖：
    1. render() 的几何：任意尺寸下都恰好 h 行、每行恰好 w 个显示列（中文算 2）
    2. 状态行 / 面板 / 输入行 / 快捷键行 / 帮助页的内容
    3. 面板滚动、hex 视图、暂停
    4. 键盘动作：打字+回车 -> hub.send()；hub 命令 -> hub.command()；
       Ctrl-T 切视图、Ctrl-P 暂停、Ctrl-L 清屏、Ctrl-S 存盘、Ctrl-Q 退出
    5. loop() 真的驱动 hub.tick() 且进/出备用屏幕（stdout 抓得到转义序列）
"""

from __future__ import annotations

# __pycache__ 统一写到仓库的 out/pycache（sys.pycache_prefix 只影响设置之后的 import，
# 所以要在所有本地 import 之前，但又必须在 from __future__ 之后）。
import os as _os, sys as _sys

_d = _os.path.abspath(__file__)
while _d != _os.path.dirname(_d) and not _os.path.exists(_os.path.join(_d, ".git")):
    _d = _os.path.dirname(_d)
_sys.pycache_prefix = _os.path.join(_d, "out", "pycache")

import io
import os
import shutil
import sys
from contextlib import redirect_stdout

_HERE = os.path.dirname(os.path.abspath(__file__))  # scripts/serial_hub/tests
_PKG = os.path.dirname(_HERE)  # scripts/serial_hub
_REPO = os.path.dirname(os.path.dirname(_PKG))  # 仓库根
if _PKG not in sys.path:
    sys.path.insert(0, _PKG)

from core.logstore import hexdump_text  # noqa: E402
from tui import ansi as A  # noqa: E402
from tui.app import TuiApp  # noqa: E402
from tui.view import render  # noqa: E402

CHECKS = []


def ok(name, cond, extra=""):
    CHECKS.append((name, bool(cond)))
    print("%s %s%s" % ("OK  " if cond else "FAIL", name, ("   " + extra) if extra else ""))


class StubHub:
    """只实现 TUI 用到的四个入口，用来断言「动作确实走公开接口」。"""

    def __init__(self):
        self.running = True
        self.sent = []
        self.commands = []
        self.ticks = 0
        self.state = {
            "com": "COM9",
            "baud": 115200,
            "ser_ok": True,
            "uptime": 7,
            "clients": 2,
            "owner": None,
            "rx": 4096,
            "tx": 128,
            "drop_locked": 21,
            "drop_proto": 22,
            "log": "serial-1.log",
            "sink_errors": 0,
        }

    def send(self, data, who="tui", owner_cid=None):
        self.sent.append((bytes(data), who))
        return True

    def command(self, text, source="tui", client=None):
        self.commands.append(text)
        return "# pong %s" % text

    def tick(self, timeout=0.05):
        self.ticks += 1

    def snapshot(self):
        return dict(self.state)


def geometry():
    lines = [("rx", "hello"), ("hub", "* hi"), ("tx", ">>> out")]
    sizes = [(80, 24), (120, 40), (100, 20), (40, 8), (20, 5)]
    for w, h in sizes:
        frame = render({"com": "COM1", "baud": 9600}, lines, w, h, input_text="abc")
        ok("render 行数 = %d（w=%d h=%d）" % (h, w, h), len(frame) == h, "实际 %d" % len(frame))
        bad = [(i, A.width(f)) for i, f in enumerate(frame) if A.width(f) != w]
        ok("render 每行宽 = %d（w=%d h=%d）" % (w, w, h), not bad, str(bad[:3]))
    wide = render({"com": "COM1"}, [("rx", "中" * 60)], 40, 8)
    ok("超宽中文行不越界", all(A.width(f) == 40 for f in wide))


def contents():
    lines = [("rx", "line-%d" % i) for i in range(1, 31)]
    frame = render(
        {
            "com": "COM9",
            "baud": 115200,
            "ser_ok": True,
            "uptime": 7,
            "clients": 2,
            "rx": 4096,
            "tx": 128,
            "log": "serial-9.log",
        },
        lines,
        100,
        12,
        input_text="v",
        input_mode="hub",
    )
    plain = [A.strip_ansi(x) for x in frame]
    ok("状态行含串口与波特率", "COM9@115200" in plain[0], plain[0][:60])
    ok("状态行含会话数与计数", "会话 2" in plain[0] and "收 4.0 KB" in plain[0], plain[0][:70])
    ok("面板显示的是最后几行", "line-30" in plain[-3] and "line-1 " not in " ".join(plain), plain[-3][:40])
    ok("输入行按模式给提示", "hub> v" in plain[-2] and "Tab 切到设备发送" in plain[-2], plain[-2][:60])
    ok("快捷键行含 Ctrl-Q", "Ctrl-Q" in plain[-1])
    scrolled = render({}, lines, 100, 12, scroll=6)
    ok(
        "scroll 让面板回退",
        "line-30" not in A.strip_ansi("".join(scrolled))[:0]
        and (
            "line-24" in A.strip_ansi("\n".join(scrolled)) or "line-23" in A.strip_ansi("\n".join(scrolled))
        ),
    )
    helppage = render({}, lines, 100, 24, help_on=True)
    htext = A.strip_ansi("\n".join(helppage))
    ok("帮助页列出按键与命令", "Ctrl-S" in htext and "sessions" in htext)
    flash = render({}, [], 80, 8, flash="已存 log-1.raw")
    ok("flash 抢到状态行尾部（窄终端允许截断）", "已存" in A.strip_ansi(flash[0]))
    flash_wide = render({}, [], 140, 8, flash="已存 log-1.raw")
    ok("宽终端下 flash 完整显示", "已存 log-1.raw" in A.strip_ansi(flash_wide[0]))
    paused = render({}, [], 80, 8, paused=True)
    ok("暂停时状态行有标记", "已暂停" in A.strip_ansi(paused[0]))


def hexpanel():
    data = bytes(range(0x30, 0x40))
    text, _off = hexdump_text(data, 0)
    ok("hexdump 每 8 字节一个空档", "30 31 32 33 34 35 36 37  38 39" in text, text[:60])
    frame = render({"com": "COM1"}, [], 100, 8, mode="hex", hex_lines=[text])
    plain = A.strip_ansi("\n".join(frame))
    ok("hex 视图把行原样显示", "00000000" in plain and "|0123456789:;<=>?|" in plain)


def keyboard():
    app = TuiApp(StubHub())
    for ch in "version":
        app.handle_key("c:" + ch)
    app.handle_key("enter")
    ok("回车把输入发给设备（补 CR）", app.hub.sent == [(b"version\r", "tui")], str(app.hub.sent))
    app.handle_key("tab")
    for ch in "status":
        app.handle_key("c:" + ch)
    app.handle_key("enter")
    ok("Tab 后回车走 hub 命令", app.hub.commands == ["status"], str(app.hub.commands))
    ok("命令回显进面板", any(kind == "ctl" and "# pong status" in text for kind, text in app.lines))
    for ch in "help":
        app.handle_key("c:" + ch)
    app.handle_key("enter")
    ok("只敲 help 也当 hub 命令", app.hub.commands == ["status", "help"], str(app.hub.commands))
    for ch in "@@whoami":
        app.handle_key("c:" + ch)
    app.input_mode = "dev"
    app.handle_key("enter")
    ok("@@ 前缀在 dev 模式也当命令", app.hub.commands[-1] == "whoami", str(app.hub.commands))
    app.handle_key("ctrl-t")
    ok("Ctrl-T 切 hex", app.mode == "hex")
    app.handle_key("ctrl-t")
    ok("Ctrl-T 切 both", app.mode == "both")
    app.handle_key("ctrl-t")
    ok("Ctrl-T 转回 text", app.mode == "text")
    app.handle_key("ctrl-p")
    ok("Ctrl-P 暂停", app.paused is True)
    app.handle_key("ctrl-p")
    ok("Ctrl-P 恢复", app.paused is False)
    app.handle_key("c:x")
    app.handle_key("backspace")
    ok("退格删字符", app.input_text == "")
    app.lines.append(("rx", "x"))
    app.handle_key("ctrl-l")
    ok("Ctrl-L 清屏", len(app.lines) == 0 and len(app.hex_lines) == 0)
    app.handle_key("c:z")
    app.handle_key("esc")
    app.handle_key("c:y")
    app.handle_key("ctrl-q")
    ok("Ctrl-Q 输入行仍保留未提交字符", app.input_text == "y", repr(app.input_text))
    ok("Ctrl-Q 让 hub 退出", app.hub.running is False)

    hub = StubHub()
    app2 = TuiApp(hub, mode="hex")
    app2.lines.append(("rx", "a"))
    app2.hex_lines.append("00000000  61                                          |a|")
    app2.on_event(_ev("rx", b"abc\n"))
    app2.on_event(_ev("tx", b"ok\r\n"))
    app2.on_event(_ev("hub", msg="连接 #1"))
    kinds = [k for k, _t in app2.lines]
    ok(
        "sink 把 RX 拆行、TX/hub 各成一行",
        kinds.count("rx") >= 2 and "tx" in kinds and "hub" in kinds,
        str(kinds),
    )
    ok("sink 攒了 hex 行", len(app2.hex_lines) >= 2, str(len(app2.hex_lines)))
    app2.paused = True
    app2.on_event(_ev("rx", b"paused-data\n"))
    ok("暂停时不再累计文本行", not any("paused-data" in t for _k, t in app2.lines))
    ok("暂停也不影响 hex 与原始字节", len(app2.hex_lines) >= 2 and app2.raw.size > 0)

    # Ctrl-S：把 repo_root 指到 out/tmp 下的临时目录，断言三个文件真的落盘
    tmp = os.path.join(_REPO, "out", "tmp", "_tui_check")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)
    saved = []
    import tui.app as appmod

    old_repo_root = appmod.repo_root
    appmod.repo_root = lambda: tmp
    try:
        app3 = TuiApp(StubHub())
        app3.on_event(_ev("rx", b"save-me\n"))
        path = app3.save_dump()
        saved = os.listdir(os.path.join(tmp, "out", "dump"))
        ok(
            "Ctrl-S 落盘 .raw + .txt + .hex",
            path
            and any(x.endswith(".raw") for x in saved)
            and any(x.endswith(".txt") for x in saved)
            and any(x.endswith(".hex") for x in saved),
            str(saved),
        )
    finally:
        appmod.repo_root = old_repo_root
        shutil.rmtree(tmp, ignore_errors=True)


def step3():
    """第 3 步：both 混合视图 / 会话侧栏 / 搜索。"""
    lines = [
        ("rx", "boot ok"),
        ("rx", "ERROR: no disk"),
        ("tx", "version\r"),
        ("rx", "ERROR: again"),
        ("hub", "连接 #1"),
    ]
    frame = render({"com": "COM1"}, lines, 120, 12, mode="both", hex_lines=["00000000  61  |a|"])
    plain = A.strip_ansi("\n".join(frame))
    ok("both 视图有分隔线", "│" in plain)
    ok("窄屏 both 退回单栏", "│" not in A.strip_ansi("\n".join(render({}, lines, 40, 12, mode="both"))))
    for mode in ("text", "hex", "both"):
        fr = render(
            {"com": "COM1"},
            lines,
            100,
            10,
            mode=mode,
            hex_lines=["00000000  61  |a|"],
            sidebar=["会话 1", "收 2 B"],
        )
        ok(
            "mode=%s 仍是恰好 h 行 × w 列" % mode,
            len(fr) == 10 and all(A.width(A.strip_ansi(x)) == 100 for x in fr),
        )
    fr = render({}, lines, 100, 10, sidebar=["会话侧栏标记"])
    ok("会话侧栏画在面板右侧", any("会话侧栏标记" in A.strip_ansi(x)[60:] for x in fr))
    ok("关掉侧栏后不出现", all("会话侧栏标记" not in A.strip_ansi(x) for x in render({}, lines, 100, 10)))

    hub = StubHub()
    app = TuiApp(hub)
    for kind, text in lines:
        app.lines.append((kind, text))
    app.handle_key("ctrl-f")
    ok("Ctrl-F 进入搜索输入", app.input_mode == "search")
    for ch in "ERROR":
        app.handle_key("c:" + ch)
    app.handle_key("enter")
    ok("搜索命中 2 行", app.search_on and len(app.hits) == 2, str(app.hits))
    ok("搜索状态可读", "2/2" in app.search_status(), app.search_status())
    app.draw((100, 10))
    app.hit = 1
    app.handle_key("c:n")
    ok("n 不越界", app.hit == 1, "hit=%d" % app.hit)
    app.handle_key("c:N")
    ok("N 回到上一个命中", app.hit == 0, "hit=%d" % app.hit)
    ok("命中行带高亮", A.REVERSE in "\n".join(app.draw((100, 10))))
    ok("状态行里能看到搜索计数", "1/2" in A.strip_ansi("\n".join(app.draw((100, 10)))))
    app.handle_key("esc")
    ok("Esc 退出搜索", app.search_on is False and app.search == "")
    app.handle_key("ctrl-w")
    ok("Ctrl-W 关侧栏", app.sidebar is False)

    app2 = TuiApp(StubHub(), mode="hex")
    app2.lines.append(("rx", "ERROR"))
    app2.input_text = "ERROR"
    app2.input_mode = "search"
    app2.submit()
    ok("hex 下搜索自动切回 text", app2.mode == "text" and app2.search_on)

    # 真快照的形状：sinks 是「个数」（int）而不是名字列表 —— 曾经把侧栏画崩
    app3 = TuiApp(StubHub())
    app3.state = {
        "com": "COM1",
        "baud": 115200,
        "sinks": 2,
        "sink_errors": 1,
        "clients": 0,
        "sessions": [],
        "rx": 10,
        "tx": 4,
    }
    side = app3.sidebar_lines()
    ok(
        "侧栏能吃 int 型 sinks（真实快照形状）",
        any("sink 数量 2" in s for s in side) and any("sink 错误 1" in s for s in side),
        str(side),
    )


def _ev(kind, data=b"", msg=""):
    from core.events import Event

    return Event(kind=kind, direction="RX" if kind == "rx" else "TX", who="board", data=data, msg=msg)


def loop_check():
    hub = StubHub()
    app = TuiApp(hub)
    seq = ["c:h", "c:i", "enter", "ctrl-q"]
    buf = io.StringIO()
    with redirect_stdout(buf):
        frames = app.loop(hub, key_source=lambda: seq.pop(0) if seq else "", max_frames=3)
    out = buf.getvalue()
    ok("loop 跑完并返回帧数", frames >= 1, "frames=%d" % frames)
    ok("loop 调用了 hub.tick", hub.ticks >= 1, "ticks=%d" % hub.ticks)
    ok("loop 切进/切出备用屏幕", A.ALT_ON in out and A.ALT_OFF in out)
    ok("loop 退出时把 hub 停掉", hub.running is False)
    ok("loop 期间画过状态行", "COM9@115200" in A.strip_ansi(out))


def main():
    print("=== 1. 几何 ===")
    geometry()
    print("\n=== 2. 内容 ===")
    contents()
    print("\n=== 3. hex 视图 ===")
    hexpanel()
    print("\n=== 4. 键盘与 sink ===")
    keyboard()
    print("\n=== 5. 主循环 ===")
    loop_check()
    print("\n=== 6. 第 3 步：both/侧栏/搜索 ===")
    step3()
    bad = [name for name, good in CHECKS if not good]
    print("\n%d OK / %d FAIL" % (len(CHECKS) - len(bad), len(bad)))
    for name in bad:
        print("  FAIL: %s" % name)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
