#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TUI 前端（零依赖 ANSI）。

    ansi.py    终端转义/宽度/剪裁（唯一碰 ANSI 的地方）
    keys.py    键盘 -> token（Windows msvcrt / POSIX termios 都支持）
    view.py    纯渲染：状态 + 行缓冲 -> w×h 字符帧（可离线断言）
    app.py     TuiApp：sink + 键盘 + 主循环；动作只走 hub.send()/hub.command()

换 UI（Textual / Web / 独立进程）时整目录替换，core/ 不用动。
"""
