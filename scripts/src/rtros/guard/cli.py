"""守卫的会话侧命令：`--status` / `--list` / `--request` / `--tasks`。

这些命令在**沙箱内**执行（只读写信箱文件），真正的执行发生在沙箱外的守卫进程里。
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from rtros.guard.config import (
    DEFAULT_EXPIRES,
    DEFAULT_TARGET,
    DEFAULT_WAIT,
    MAILBOX_DEFAULT,
    PROTOCOL,
    REPO,
    STALL_SECONDS,
    TASKS,
    TASKS_FILE,
)
from rtros.guard.executor import Guard
from rtros.guard.mailbox import Mailbox, _atomic_write_json, _pid_alive, _read_json
from rtros.guard.request import validate_request


def cmd_status(mb: Mailbox) -> int:
    hb = _read_json(mb.heartbeat) or {}
    lock = _read_json(mb.lock) or {}
    pid = hb.get("pid") or lock.get("pid")
    alive = bool(pid) and _pid_alive(int(pid or 0))
    beat_at = hb.get("beatAt")
    age = None
    if beat_at:
        try:
            age = int(time.time() - datetime.fromisoformat(beat_at).timestamp())
        except Exception:
            age = None

    print(f"信箱      : {mb.root}")
    if not pid:
        print("守卫      : 没起过（没有 lock / heartbeat）")
        print("            → 在沙箱之外的终端里双击仓根 ai_services.bat")
        return 3
    if not alive:
        print(f"守卫      : 不在跑（pid={pid} 已退出）")
        print("            → 重新双击仓根 ai_services.bat；残留锁会被新守卫按 pid 自动接管")
        return 3
    print(f"守卫      : 在跑（pid={pid}，启动于 {hb.get('startedAt') or lock.get('startedAt')}）")
    if hb.get("stopped"):
        print("            !! 心跳里带 stopped=true：上一任已收尾，可能锁还没清")
    print(f"心跳      : {beat_at or '?'}（{age if age is not None else '?'}s 前）")
    run = hb.get("running")
    if run:
        print(
            f"正在执行  : req_{run.get('id'):04d} {run.get('action')} —— 已跑 {run.get('elapsedSeconds')}s，日志 {run.get('logBytes')} 字节"
        )
    else:
        print("正在执行  : 没有")
    p = mb.pending()
    print(f"待处理    : {p if p else '无'}")
    return 0


def cmd_list(mb: Mailbox) -> int:
    ids = mb.ids()
    if not ids:
        print(f"{mb.root} 里还没有任何请求")
        return 0
    print(f"{'id':>5}  {'动作':<12} {'状态':<9} {'退出码':>6}  说明")
    for n in ids:
        req = _read_json(mb.req(n)) or {}
        rep = _read_json(mb.rep(n))
        if rep is None:
            print(
                f"{n:>5}  {req.get('action', '?'):<12} {'排队中':<9} {'-':>6}  写于 {(req.get('createdAt') and datetime.fromtimestamp(req['createdAt']).strftime('%m-%d %H:%M:%S')) or '?'}"
            )
            continue
        ec = rep.get("exitCode")
        print(
            f"{n:>5}  {req.get('action', '?'):<12} {rep.get('status', '?'):<9} {('-' if ec is None else ec):>6}  {rep.get('message', '')}"
        )
    return 0


def cmd_request(
    mb: Mailbox,
    action: str,
    target: str | None,
    binrel: str | None,
    note: str,
    expires: int,
    wait: bool,
    wait_timeout: float,
) -> int:
    args: dict = {}
    if target:
        args["target"] = target
    if binrel:
        args["bin"] = binrel
    if note:
        args["note"] = note
    req = {
        "protocol": PROTOCOL,
        "action": action,
        "args": args,
        "createdAt": time.time(),
        "expiresIn": expires,
        "note": note,
    }
    valid, why = validate_request(req)
    if valid is None:
        print(f"参数不合法，请求没写进信箱：{why}", file=sys.stderr)
        return 2

    mb.ensure()
    n = mb.next_id()
    _atomic_write_json(mb.req(n), req)
    print(f"已下请求 req_{n:04d}：{action} {args if args else ''}")

    hb = _read_json(mb.heartbeat) or {}
    pid = hb.get("pid") or (_read_json(mb.lock) or {}).get("pid")
    if not (pid and _pid_alive(int(pid))):
        print("!! 守卫不在跑 —— 请求会一直躺着。请在沙箱之外的终端里双击仓根 ai_services.bat")
        if wait:
            return 3

    if not wait:
        print(f"不等待。稍后：--list 看结果，或读 {mb.log(n)}")
        return 0

    deadline = time.time() + wait_timeout
    while time.time() < deadline:
        rep = _read_json(mb.rep(n))
        if rep is not None:
            print("-" * 70)
            print(f"应答 rep_{n:04d}：status={rep.get('status')} exitCode={rep.get('exitCode')}")
            print(f"说明：{rep.get('message')}")
            print(f"日志：{rep.get('log')}")
            tail = rep.get("tail") or []
            if tail:
                print("-" * 70)
                for line in tail:
                    print(f"  {line}")
            return 0 if rep.get("status") == "ok" else 1
        time.sleep(0.5)
    print(f"等待超时（{int(wait_timeout)}s）——任务可能还在守卫里跑。不会杀掉它：事后 --list 或读 {mb.log(n)}")
    return 2


def cmd_tasks() -> int:
    """列出 tasks.toml 允许的任务（--tasks）。"""
    print(f"任务表：{TASKS_FILE}")
    print(f"{'id':<12} {'上限':>6}   {'允许参数':<14} 说明")
    for tid, task in TASKS.items():
        allow = ",".join(task.allow) or "-"
        print(f"{tid:<12} {int(task.timeout):>5}s   {allow:<14} {task.title}")
    print("\n用 --request <id> 下请求；不带参数启动守卫 = 常驻。")
    return 0


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        # TextIO 才有 reconfigure；用 getattr 探测，免得为类型标注加 ignore。
        reconfigure = getattr(s, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            # 真控制台上保持默认（Windows 走 WriteConsoleW，中文正常）；
            # 被重定向到管道/文件时强制 UTF-8，否则会被按 cp936 写出去、下游按 UTF-8 读成乱码。
            if not s.isatty():
                reconfigure(encoding="utf-8", errors="replace")
            else:
                reconfigure(errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(
        description="rt-thread-ros 守卫：任务表驱动的沙箱外执行器（烧录 / 编译 / 探针），文件信箱协议",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--mailbox", default=None, help=f"信箱目录（默认 <仓库>/{MAILBOX_DEFAULT}）")
    ap.add_argument("--status", action="store_true", help="守卫生不活着 ＋ 积压一览")
    ap.add_argument("--list", action="store_true", help="已处理请求一览")
    ap.add_argument("--tasks", action="store_true", help="列出 tasks.toml 允许的任务")
    ap.add_argument("--request", metavar="TASK", help=f"下请求：{', '.join(TASKS)}")
    ap.add_argument("--target", default=None, help=f"芯片型号（默认 {DEFAULT_TARGET}）")
    ap.add_argument(
        "--bin",
        dest="binrel",
        default=None,
        help="要烧的固件（仓内相对路径，默认 tasks.toml 的 default_bin）",
    )
    ap.add_argument("--note", default="", help="备注，最长 200 字符")
    ap.add_argument(
        "--expires", type=int, default=DEFAULT_EXPIRES, help=f"请求有效期秒数（默认 {DEFAULT_EXPIRES}）"
    )
    ap.add_argument("--wait", action="store_true", help="等到应答并回显日志尾")
    ap.add_argument(
        "--wait-timeout",
        type=float,
        default=DEFAULT_WAIT,
        help=f"会话侧等待上限秒（默认 {DEFAULT_WAIT:.0f}）",
    )
    ap.add_argument("--once", action="store_true", help="守卫模式：处理完积压就退")
    ap.add_argument("--timeout", type=float, default=None, help="守卫模式：覆盖单次执行上限秒")
    ap.add_argument(
        "--stall",
        type=float,
        default=STALL_SECONDS,
        help=f"守卫模式：停滞判据秒（0=关闭，默认 {int(STALL_SECONDS)}）",
    )
    ns = ap.parse_args(argv)

    mb = Mailbox(Path(ns.mailbox).resolve() if ns.mailbox else (REPO / MAILBOX_DEFAULT))

    if ns.status:
        return cmd_status(mb)
    if ns.list:
        return cmd_list(mb)
    if ns.tasks:
        return cmd_tasks()
    if ns.request:
        return cmd_request(
            mb, ns.request, ns.target, ns.binrel, ns.note, ns.expires, ns.wait, ns.wait_timeout
        )
    return Guard(mb, ns.once, ns.timeout, ns.stall).loop()
