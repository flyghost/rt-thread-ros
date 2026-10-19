#!/usr/bin/env python3
"""
serial_hub.py —— 串口中继：一个进程独占串口，多个客户端同时收发

为什么要它
----------
Windows 的 COM 口默认是【独占】的：一个终端打开后自动化脚本再打开会得到
"Access denied"；如果靠 FILE_SHARE_* 强行共享，读方向会被两个读者【瓜分】
（谁先读走谁拿到），两边都会随机丢字节。所以正确做法只有一个：
    **让一个进程独占串口，其他人连它。**

对外接口（按【接入协议 frontend】分端口，一个连接一个 codec）
------------------------------------------------------------
1) `--port`（默认 127.0.0.1:5555）—— raw，且带【首字节嗅探】：
      第一个字节是 0xFF（Telnet IAC）就自动切 telnet，否则 raw。
      通用终端的 Raw 模式连这里；自动化脚本、其它工具也连这里。
2) `--telnet-port`（默认 127.0.0.1:5557，0=关闭）—— 强制 telnet：
      最小 Telnet 服务端（默认拒绝一切选项、过滤 IAC、CRLF 规范化），
      给"只有 Telnet 会话类型、不会说 Raw"的终端用。
3) `--control-port`（默认 127.0.0.1:5556）—— 行命令，便于脚本编排
     help / status / sessions / lock <cid> / unlock / proto <cid> <raw|telnet>
     / kill <cid> / reset [dtr|rts|both] / shutdown
4) 内联控制（数据口里以 "@@" 开头的行）—— 给自动化脚本用
     @@lock / @@unlock / @@status / @@whoami / @@proto <raw|telnet> / @@help
     好处：锁直接绑定到"它自己那条数据连接"，不需要另一条连接、也不怕控制口断开

广播语义（加协议层后最容易踩的坑）
----------------------------------
串口 -> PC 的字节必须在【原始字节】上广播，再由【每个会话用自己的 codec】编码后发出：
    raw    原样
    telnet 补 CRLF、把字面 0xFF 翻倍成 FF FF
所以推送路径是 "原始字节 -> 逐会话 encode -> 各自的 out 缓冲"，不能广播"已编码"的字节。
反方向则是 "客户端字节 -> 该会话 decode -> 串口"，且 decode 出的控制事件（telnet 协商
应答等）只回给该客户端，**绝不写进串口**。

落盘（默认 out/log/）
--------------------
    serial-<时间>.raw  串口 -> PC 的**字节精确**流（不含 PC -> 串口方向，便于离线逐字节对账）
    serial-<时间>.log  双向、带时间戳/方向/客户端号，非可见字符转义（给人看、给 AI grep）

客户端怎么配
------------
    Raw 终端    ：协议 Raw / 地址 127.0.0.1 / 端口 5555
    Telnet 终端 ：协议 Telnet / 地址 127.0.0.1 / 端口 5557（给不会说 Raw 的终端）
    Telnet 终端一连上会先发一串 IAC 协商（NAWS/TERMINAL-TYPE/DO ECHO...），
    hub 会逐条回 DONT/WONT 并把这些字节**吃掉**，不会灌进设备 —— 这正是不加
    telnet 前端时会满屏 "^M^M^M help ^M" 的原因（设备把协商回显给客户端，
    客户端又当协商解析，两边状态机打架）。
    具体客户端（哪一款、点哪个选项）见 README.md 的"客户端怎么连"。

典型用法
--------
    python scripts/run_rtros.py hub                    # 按探测规则自动选串口，监听 5555/5556/5557
    python scripts/run_rtros.py hub --com COM46 --baud 115200
    python scripts/run_rtros.py hub --list             # 只列出候选串口后退出
    python scripts/run_rtros.py hub --stdout rxtx      # 本地窗口里连 PC->串口 的内容也打出来
    python scripts/run_rtros.py hub --stdout hex       # 本地窗口按 hex+ASCII 两栏实时显示（看设备->PC 的字节）
    python scripts/run_rtros.py hub --ui tui           # 全屏面板：状态行 + 数据面板 + 输入行（Ctrl-Q 退出）
    python scripts/run_rtros.py hub --ui none          # 不打窗口（后台只落日志）
    python scripts/run_rtros.py hub --list             # 列出候选串口 + 当前探测规则
    python scripts/run_rtros.py hub --prefer name:COM7 # 临时加一条探测规则（可重复）

自动化脚本侧的写法（示例）
--------------------------
    import socket, time
    s = socket.create_connection(("127.0.0.1", 5555))
    s.sendall(b"@@lock\\r\\n")            # 大批量传输期间冻结其他客户端（比如人开的终端）
    s.sendall(b"some_cmd\\r\\n")
    ...  # 收二进制数据
    s.sendall(b"@@unlock\\r\\n")

退出码：0 正常；2 参数/串口问题。

目录结构（2026-10 重排，代码按职责分开）
----------------------------------------
    serial_hub.py        入口：命令行参数 + 装配（本文件）
    core/relay.py        SerialHub：独占串口、selector 主循环、广播、写仲裁、重连、命令实现
    core/session.py      Client：一条连接 = 一个会话（codec / 待发缓冲 / 写锁）
    core/control.py      控制口 5556 的服务端（每连接一个线程）
    core/logstore.py     esc() / hexdump_text() / sync()（日志格式与落盘原语）
    core/ports.py        串口枚举 + 首选端口编排（--list）
    core/util.py         时间戳 / 字节数 / 仓库根
    discovery/           端口探测规则（一个芯片家族一个文件）+ base(PortInfo/PortRule/parse_rule_spec)
    protocols/           接入协议：base(Codec) / raw / telnet，CODECS 注册表
    tui/                 全屏面板前端：ansi(终端转义/宽度) / keys(键盘) / view(纯渲染) / app(sink+主循环)
    tests/               离线自检（codec_check.py / sink_check.py / tui_check.py）与双客户端测试
"""

from __future__ import annotations

import contextlib

# __pycache__ 统一写到仓库 out/pycache：仓库根由本文件位置直接推出（parents[2]），不做搜索
import sys as _sys
from pathlib import Path as _Path

_sys.pycache_prefix = str(_Path(__file__).resolve().parents[2] / "out" / "pycache")


import argparse  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

# 让 `python scripts/run_rtros.py hub` 直接跑（把包目录加进 sys.path）
_HERE = os.path.dirname(os.path.abspath(__file__))

from rtros.serial_hub.core.ports import autodetect_port, print_ports  # noqa: E402
from rtros.serial_hub.core.relay import SerialHub  # noqa: E402
from rtros.serial_hub.core.util import repo_root  # noqa: E402
from rtros.serial_hub.discovery import print_rules  # noqa: E402
from rtros.serial_hub.discovery.base import parse_rule_spec  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="串口中继：一个进程独占串口，多个客户端（终端/脚本）同时收发",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Raw 终端    ：127.0.0.1:5555（首字节 0xFF 自动切 telnet）\n"
        "Telnet 终端 ：127.0.0.1:5557（--telnet-port 0 可关）\n"
        "脚本        ：连 5555 收发；@@lock / @@unlock / @@proto 切换协议\n"
        "控制口 5556 ：sessions / lock / proto / kill / status / reset\n"
        "客户端示例、探测规则见 README.md",
    )
    p.add_argument("--com", help="串口名（如 COM7；省略则按探测规则自动选）")
    p.add_argument(
        "--prefer",
        action="append",
        default=[],
        metavar="SPEC",
        help="临时探测规则，可重复：1A86:7523 / name:COM7 / desc:ch340 / hwid:USB",
    )
    p.add_argument("--baud", type=int, default=115200, help="波特率（默认 115200）")
    p.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    p.add_argument("--port", type=int, default=5555, help="数据口（raw/嗅探，默认 5555）")
    p.add_argument(
        "--telnet-port",
        type=int,
        default=5557,
        help="telnet 接入口（给不会说 Raw 的终端；0=关闭，默认 5557）",
    )
    p.add_argument(
        "--sniff",
        dest="sniff",
        action="store_true",
        default=True,
        help="数据口按首字节自动判定协议（0xFF=Telnet IAC，默认开）",
    )
    p.add_argument("--no-sniff", dest="sniff", action="store_false", help="数据口一律 raw，不做嗅探")
    p.add_argument(
        "--sniff-timeout", type=float, default=0.5, help="连接后迟迟不开口则按 raw 处理（秒，默认 0.5）"
    )
    p.add_argument("--control-port", type=int, default=5556, help="控制口（0=关闭，默认 5556）")
    p.add_argument("--allow-lan", action="store_true", help="监听 0.0.0.0（默认只听本机）")
    p.add_argument("--list", action="store_true", help="列出候选串口后退出")
    p.add_argument(
        "--stdout", choices=["rx", "rxtx", "hex", "none"], default="rx", help="本窗口打印什么（默认 rx）"
    )
    p.add_argument(
        "--ui",
        choices=["stream", "tui", "none"],
        default="stream",
        help="本窗口怎么显示：stream=逐行打印（默认，与以前逐字节相同）；"
        "tui=全屏面板（状态行/数据面板/输入行）；none=不打窗口，只落日志",
    )
    p.add_argument("--log", dest="log", action="store_true", default=True, help="落盘日志（默认开）")
    p.add_argument("--no-log", dest="log", action="store_false", help="不落盘")
    p.add_argument(
        "--log-dir", default=os.path.join(repo_root(), "out", "log"), help="日志目录（默认 out/log）"
    )
    p.add_argument("--read-timeout", type=float, default=0.05, help="串口读超时（默认 0.05s）")
    p.add_argument(
        "--write-timeout", type=float, default=1.0, help="串口写超时（默认 1.0s；没有它会永久阻塞）"
    )
    p.add_argument("--tx-queue", type=int, default=512, help="待发队列长度（默认 512 块）")
    p.add_argument(
        "--dtr-open",
        choices=["keep", "high", "low"],
        default="keep",
        help="打开串口时是否动 DTR（默认 keep=不动，避免误扰动设备）",
    )
    p.add_argument(
        "--reset-mode", choices=["dtr", "rts", "both"], default="dtr", help="reset 命令默认用哪根线"
    )
    p.add_argument(
        "--reset-active", choices=["low", "high"], default="low", help="复位脉冲的有效电平（默认 low）"
    )
    p.add_argument("--reset-pulse", type=float, default=0.1, help="复位脉冲宽度秒（默认 0.1）")
    p.add_argument(
        "--reopen", dest="reopen", action="store_true", default=True, help="串口掉了自动重连（默认开）"
    )
    p.add_argument("--no-reopen", dest="reopen", action="store_false", help="不自动重连")
    p.add_argument("--reopen-delay", type=float, default=2.0, help="重连间隔秒（默认 2.0）")
    p.add_argument(
        "--lock-writes",
        dest="lock_writes",
        action="store_true",
        default=True,
        help="@@lock 后冻结其他客户端的写入（默认开）",
    )
    p.add_argument("--no-lock-writes", dest="lock_writes", action="store_false", help="lock 只作标记，不冻结")
    p.add_argument("--control-prefix", default="@@", help="数据口内联控制前缀（默认 @@，空串=关闭）")
    return p


def setup_console() -> None:
    """让中文在 Windows 控制台里正常显示（否则控制台按 GBK 解 UTF-8 输出，全是乱码）。"""
    if os.name != "nt":
        return
    try:
        if sys.stdout is not None and sys.stdout.isatty():
            os.system("chcp 65001 >nul 2>&1")
    except Exception:
        pass
    for name in ("stdout", "stderr"):
        stream = getattr(sys, name, None)
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


def main(argv=None) -> int:
    setup_console()
    args = build_parser().parse_args(argv)
    if args.ui == "tui" and not (sys.stdout and sys.stdout.isatty() and sys.stdin and sys.stdin.isatty()):
        print("[hub] --ui tui 需要交互式终端（stdout/stdin 都是 tty），已回退到 --ui stream", file=sys.stderr)
        args.ui = "stream"
    try:
        rules = tuple(parse_rule_spec(spec) for spec in (args.prefer or ()))
    except ValueError as exc:
        print(f"[hub] --prefer 规则无效：{exc}", file=sys.stderr)
        return 2
    if args.list:
        print_ports(rules)
        print()
        print_rules(rules)
        return 0
    if not args.com:
        args.com = autodetect_port(rules)
        if not args.com:
            print("[hub] 没能自动确定串口，请用 --com 指定。候选：", file=sys.stderr)
            print_ports(rules)
            return 2
    hub = SerialHub(args)
    return hub.run()


if __name__ == "__main__":
    sys.exit(main())
