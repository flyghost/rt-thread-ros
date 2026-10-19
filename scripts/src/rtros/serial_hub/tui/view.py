#!/usr/bin/env python3
"""纯渲染：把「状态 + 行缓冲」画成固定 w×h 的字符帧。

这里**只做字符串**：不读键盘、不碰串口、不写文件，所以能离线断言
（tests/tui_check.py 就是按显示宽度逐行量它的产物）。

布局（共 h 行）：
    row 0            状态行（反色）
    row 1 .. h-3     数据面板（text / hex / both）+ 可选会话侧栏
    row h-2          输入行
    row h-1          快捷键行（暗色）

视图三态（由 app 传 mode）：
    text —— 只画文本行
    hex  —— 只画 hex 行
    both —— 左文本 / 右 hex，各占一半宽，中间一条竖线

搜索高亮**不在这里做**：app 把命中的行预先插好 ANSI（`fit()` 按显示宽度量），
view 只负责画 —— 保持「纯函数、可离线断言」。
"""

from __future__ import annotations

from rtros.serial_hub.core.util import human
from rtros.serial_hub.tui import ansi as A

STATUS_ROWS = 1
FOOT_ROWS = 1
INPUT_ROWS = 1

SIDE_W = 28  # 会话侧栏目标宽度
SIDE_MIN_W = 64  # 终端窄于这个就不画侧栏（宽度让给数据）
BOTH_MIN_W = 48  # 终端窄于这个就不切 both（两栏各自太窄没法看）
DIVIDER = "│"  # 全角宽度 1 的竖线

HELP_LINES = [
    ("", "serial_hub TUI —— 按键"),
    ("", ""),
    ("Ctrl-Q", "退出（等价 Ctrl-C）"),
    ("Ctrl-T", "视图循环 text -> hex -> both（both = 左文本 / 右 hex）"),
    ("Ctrl-W", "显示/隐藏右侧会话侧栏"),
    ("Ctrl-F", "搜索：输入关键字后回车；n / N 或 ↑↓ 跳命中；Esc 退出搜索"),
    ("Ctrl-L", "清空面板（不动日志文件）"),
    ("Ctrl-S", "存盘：out/dump/log-<时间> 的 .raw + .txt + .hex"),
    ("Ctrl-P", "暂停/继续面板刷新（串口与日志照常）"),
    ("Ctrl-E", "切换是否回显自己发出的字节（>>> 行）"),
    ("F1 / Esc", "打开/关闭本帮助"),
    ("Tab", "输入目标：设备  <->  hub 命令"),
    ("↑ ↓", "面板上下滚动一行（搜索中 = 上/下一个命中）"),
    ("PgUp/PgDn", "翻页（搜索中 = 前后跳 10 个命中）"),
    ("End", "回到实时（跟随最新数据）"),
    ("Enter", "发送输入行（设备：补 CR；hub：当控制命令；搜索：执行搜索）"),
    ("", ""),
    (
        "hub 命令",
        "help / status / sessions / lock <cid> / unlock / "
        "proto <cid> <raw|telnet> / kill <cid> / reset [dtr|rts|both] / shutdown",
    ),
]

FOOTER = (
    "Ctrl-Q 退出  Ctrl-T 视图  Ctrl-W 侧栏  Ctrl-F 搜索  Ctrl-L 清屏  Ctrl-S 存盘  "
    "Ctrl-P 暂停  Ctrl-E 回显  F1 帮助 | Tab 切目标 | ↑↓/PgUp/PgDn 滚动  End 跟随"
)

_EMPTY = ("", "")


def _status(state, w, *, paused, flash, mode, sidebar, extra_status):
    st = state or {}
    parts = [
        "{}@{}".format(st.get("com") or "?", st.get("baud") or "?"),
        "OK" if st.get("ser_ok") else "断开",
    ]
    if extra_status:
        parts.append(extra_status)  # 搜索反馈放前面，保证不被右端的截断吃掉
    parts += [
        f"运行 {int(st.get('uptime') or 0):d}s",
        f"会话 {int(st.get('clients') or 0):d}",
        "写锁 %s" % (st.get("owner") or "无"),
        "收 {}".format(human(int(st.get("rx") or 0))),
        "发 {}".format(human(int(st.get("tx") or 0))),
    ]
    if st.get("drop_locked"):
        parts.append("丢(锁) {}".format(human(int(st["drop_locked"]))))
    if st.get("drop_proto"):
        parts.append("协议吃掉 {}".format(human(int(st["drop_proto"]))))
    parts.append("视图 {}{}".format(mode, "+侧栏" if sidebar else ""))
    if paused:
        parts.append("已暂停")
    if int(st.get("sink_errors") or 0):
        parts.append(f"sink错误 {int(st['sink_errors']):d}")
    tail = ""
    if flash:
        tail = "  " + flash
    elif st.get("log"):
        tail = "  日志 " + str(st["log"]).replace("\\", "/").split("/")[-1]
    text = " " + " | ".join(parts)
    if tail:
        # 有 flash 时优先显示它（宁可截断日志名/提示，也不让它整个消失）
        room = w - A.width(text) - 1
        if room > 4:
            text += A.truncate(tail, room)
    return A.REVERSE + A.BOLD + A.fit(text, w) + A.RESET


_KIND_COLOR = {
    "tx": A.FG_CYAN,
    "hub": A.FG_GREY,
    "ctl": A.FG_YELLOW,
    "hex": A.FG_GREEN,
    "info": A.FG_GREEN,
}


def kind_color(kind):
    """某类行的前景色（app 做搜索高亮时要把它重新贴回去）。"""
    return _KIND_COLOR.get(kind, "")


def _panel_line(kind, text, w):
    body = A.fit(text, w)
    color = _KIND_COLOR.get(kind)
    return color + body + A.RESET if color else body


def _slice_lines(src, rows, scroll):
    """按 scroll（0 = 跟随最新）取 rows 行；不足的在上面补空行。"""
    src = list(src or [])
    if scroll > 0:
        end = max(0, len(src) - scroll)
        out = src[max(0, end - rows) : end]
    else:
        out = src[-rows:]
    out = list(out)
    while len(out) < rows:
        out.insert(0, _EMPTY)
    return out[-rows:]


def _input_line(text, mode, w):
    prompt = {"hub": "hub> ", "search": "搜>  "}.get(mode, "发>  ")
    hint = {
        "hub": "  (Tab 切到设备发送)",
        "search": "  (回车开始搜索，Esc 取消)",
        "dev": "  (Tab 切到 hub 命令)",
    }.get(mode, "")
    rest = text + A.REVERSE + " " + A.RESET
    room = w - A.width(prompt) - A.width(text) - 1
    if room > A.width(hint):
        rest += A.DIM + hint + A.RESET
    return A.FG_BLUE + A.BOLD + prompt + A.RESET + A.fit(rest, w - A.width(prompt))


def _footer_line(w):
    return A.DIM + A.fit(" " + FOOTER, w) + A.RESET


def _help_panel(w, rows):
    out = []
    for key, desc in HELP_LINES[:rows]:
        if not key and not desc:
            out.append("")
        else:
            out.append(f"   {key:<12s} {desc}")
    while len(out) < rows:
        out.append("")
    return [("info", line) for line in out]


def render(
    state,
    lines,
    w,
    h,
    *,
    input_text="",
    input_mode="dev",
    mode="text",
    scroll=0,
    paused=False,
    flash="",
    help_on=False,
    hex_lines=(),
    sidebar=(),
    extra_status="",
):
    """返回 h 行、每行**恰好 w 个显示列**（含 ANSI 颜色）的帧。"""
    panel_rows = max(1, h - STATUS_ROWS - INPUT_ROWS - FOOT_ROWS)
    side = list(sidebar or [])
    if side and w >= SIDE_MIN_W:
        side_w = min(SIDE_W, max(16, w // 3))
        main_w = max(20, w - side_w - 1)
    else:
        side_w = 0
        main_w = w

    right_panel = None
    if help_on:
        left_panel = _help_panel(main_w, panel_rows)
    elif mode == "both" and main_w >= BOTH_MIN_W:
        left_panel = _slice_lines(lines, panel_rows, scroll)
        right_panel = _slice_lines([("hex", t) for t in (hex_lines or [])], panel_rows, 0)
    elif mode == "hex":
        left_panel = _slice_lines([("hex", t) for t in (hex_lines or [])], panel_rows, scroll)
    else:
        left_panel = _slice_lines(lines, panel_rows, scroll)

    frame = [
        _status(
            state, w, paused=paused, flash=flash, mode=mode, sidebar=bool(side_w), extra_status=extra_status
        )
    ]
    for i in range(panel_rows):
        kind, text = left_panel[i]
        if right_panel is None:
            body = _panel_line(kind, text, main_w) if kind else A.fit(text, main_w)
        else:
            lw = max(1, (main_w - 1) // 2)
            rw = max(1, main_w - lw - 1)
            kind_r, text_r = right_panel[i]
            body = _panel_line(kind, text, lw) if kind else A.fit(text, lw)
            body += A.DIM + DIVIDER + A.RESET
            body += _panel_line(kind_r, text_r, rw) if kind_r else A.fit(text_r, rw)
        if side_w:
            s = side[i] if i < len(side) else ""
            body += A.DIM + DIVIDER + A.RESET + A.FG_GREY + A.fit(s, side_w) + A.RESET
        frame.append(A.fit(body, w))
    frame.append(_input_line(input_text, input_mode, w))
    frame.append(_footer_line(w))
    return frame[:h]
