"""执行层：信箱、心跳、单任务运行与超时/停滞判定。

进程模型：
- 守卫是**长驻进程**（人的窗口里跑），每 2s 轮询信箱；
- 每个请求在**独立子进程**里执行，输出逐行泵进日志文件；
- 日志 180s 无增长判停滞，总时长超该任务 `timeout` 即连进程树杀掉。
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from guard.config import (
    CHILD_TMP,
    DEFAULT_BIN,
    DEFAULT_EXPIRES,
    HEARTBEAT_SECONDS,
    POLL_SECONDS,
    PROTOCOL,
    PYOCD_PKG_DIR,
    REPO,
    RUNNING_SECONDS,
    TAIL_LINES,
    TASKS,
    TASKS_FILE,
)
from guard.mailbox import (
    Mailbox,
    _atomic_write_json,
    _now_iso,
    _pid_alive,
    _read_json,
    _say,
    _stamp,
)
from guard.procenv import child_env, cmd_label, max_mtime
from guard.request import build_argv, validate_request
from runtime.errors import ToolMissingError
from runtime.proc import TimeoutExpired, popen
from runtime.proc import run as run_cmd


class Guard:
    """守卫主循环：认领请求 → 白名单执行 → 写回结果。"""

    def __init__(self, mailbox: Mailbox, once: bool, timeout_override: float | None, stall: float) -> None:
        self.mb = mailbox
        self.once = once
        self.timeout_override = timeout_override
        self.stall = stall
        self.pid = os.getpid()
        self.started = _now_iso()
        self._stop = False
        self._last_beat = 0.0
        self._running_info: dict | None = None

    # -- 锁 --
    def acquire(self) -> bool:
        self.mb.ensure()
        cur = _read_json(self.mb.lock)
        if cur and isinstance(cur.get("pid"), int) and _pid_alive(cur["pid"]) and cur["pid"] != self.pid:
            _say(f"[{_stamp()}] 已有守卫在跑（pid={cur['pid']}，启动于 {cur.get('startedAt')}）→ 本进程退出")
            return False
        _atomic_write_json(self.mb.lock, {"pid": self.pid, "startedAt": self.started, "host": "windows"})
        return True

    def release(self) -> None:
        for p in (self.mb.running, self.mb.lock):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
        _atomic_write_json(self.mb.heartbeat, {"stopped": True, "pid": self.pid, "stoppedAt": _now_iso()})

    # -- 心跳 --
    def beat(self) -> None:
        now = time.time()
        if now - self._last_beat < HEARTBEAT_SECONDS:
            return
        self._last_beat = now
        _atomic_write_json(
            self.mb.heartbeat,
            {
                "pid": self.pid,
                "startedAt": self.started,
                "beatAt": _now_iso(),
                "mailbox": str(self.mb.root),
                "tasks": {k: task.timeout for k, task in TASKS.items()},
                "pending": len(self.mb.pending()),
                "running": self._running_info,
            },
        )

    # -- 执行一条请求 --
    def run_one(self, n: int) -> None:
        req = _read_json(self.mb.req(n))
        rep_path = self.mb.rep(n)
        log_path = self.mb.log(n)

        def finish(
            status: str,
            exit_code: int | None,
            message: str,
            started: str | None,
            queued: int | None,
            tail: list[str],
        ) -> None:
            _atomic_write_json(
                rep_path,
                {
                    "protocol": PROTOCOL,
                    "id": n,
                    "status": status,
                    "exitCode": exit_code,
                    "message": message,
                    "startedAt": started,
                    "finishedAt": _now_iso(),
                    "queuedSeconds": queued,
                    "log": str(log_path.relative_to(REPO))
                    if log_path.is_relative_to(REPO)
                    else str(log_path),
                    "tail": tail,
                },
            )

        if req is None:
            finish("rejected", None, "请求文件读不出来（不是合法 JSON）", None, None, [])
            return

        args, why = validate_request(req)
        if args is None:
            _say(f"[{_stamp()}] req_{n:04d} → rejected：{why}")
            finish("rejected", None, why, None, None, [])
            return

        expires = req.get("expiresIn", DEFAULT_EXPIRES)
        created = req.get("createdAt", 0)
        queued = int(time.time() - created) if isinstance(created, (int, float)) and created else None
        if isinstance(expires, (int, float)) and created and time.time() - created > expires:
            _say(f"[{_stamp()}] req_{n:04d} → expired（已排队 {queued}s > {expires}s）")
            finish("expired", None, f"请求已过期：排队 {queued}s，上限 {expires}s", None, queued, [])
            return

        cmds, cwd = build_argv(req["action"], args)
        total_to = self.timeout_override or TASKS[req["action"]].timeout
        started = _now_iso()
        _say(f"[{_stamp()}] req_{n:04d} 开始：{req['action']}（上限 {int(total_to)}s，cwd={cwd}）")

        tail: list[str] = []
        exit_code: int | None = 0
        status = "ok"
        message = "完成"
        env = child_env()
        if req["action"] == "usb" or any("pyocd" in argv for argv in cmds):
            # pyocd 与它的依赖都装在 tools/pyocd/pkg，用 PYTHONPATH 让它可见。
            old = env.get("PYTHONPATH")
            env["PYTHONPATH"] = str(PYOCD_PKG_DIR) + ((os.pathsep + old) if old else "")
            if req["action"] == "usb":
                env["LIBUSB_DEBUG"] = "4"  # 让 libusb 自己说清楚「为什么没看见某个设备」

        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            for phase, argv in enumerate(cmds, 1):
                head = f"$ {' '.join(argv)}"
                log.write(head + "\n")
                log.flush()
                _say(
                    f"[{_stamp()}]   phase {phase}/{len(cmds)}: {cmd_label(argv)} …（上限 {int(total_to)}s）"
                )

                try:
                    proc = popen(argv, cwd=cwd, env=env)
                except ToolMissingError as exc:
                    status, message = "failed", f"可执行文件不存在：{exc.message}"
                    log.write(f"!! {message}\n")
                    exit_code = None
                    break
                except OSError as exc:
                    status, message = "failed", f"起不来：{exc}"
                    log.write(f"!! {message}\n")
                    exit_code = None
                    break

                t0 = time.time()
                last_growth = t0
                log_bytes = 0
                self._running_info = {
                    "id": n,
                    "action": req["action"],
                    "phase": phase,
                    "startedAt": started,
                    "elapsedSeconds": 0,
                    "logBytes": 0,
                    "lastGrowthAt": _now_iso(),
                }
                _atomic_write_json(self.mb.running, self._running_info)

                killer = {"why": ""}

                stdout = proc.stdout
                assert stdout is not None

                def pump(out: Iterable[str] | None = None) -> None:
                    nonlocal log_bytes, last_growth
                    for line in out or ():
                        log.write(line)
                        log.flush()
                        log_bytes += len(line)
                        last_growth = time.time()
                        tail.append(line.rstrip("\n"))
                        if len(tail) > TAIL_LINES:
                            del tail[0]

                th = threading.Thread(target=pump, args=(stdout,), daemon=True)
                th.start()

                while True:
                    if self._stop:
                        killer["why"] = "守卫收到停止信号"
                        break
                    rc = proc.poll()
                    if rc is not None:
                        break
                    now = time.time()
                    if total_to and now - t0 > total_to:
                        killer["why"] = f"超过单次执行上限 {int(total_to)}s"
                        break
                    if self.stall and now - last_growth > self.stall:
                        killer["why"] = f"卡住了：日志连续 {int(now - last_growth)}s 没有新字节"
                        break
                    if now - self._last_beat > RUNNING_SECONDS:
                        self._running_info.update(
                            {
                                "elapsedSeconds": int(now - t0),
                                "logBytes": log_bytes,
                                "lastGrowthAt": datetime.fromtimestamp(last_growth).isoformat(
                                    timespec="seconds"
                                ),
                            }
                        )
                        _atomic_write_json(self.mb.running, self._running_info)
                        self._last_beat = now
                    time.sleep(0.2)

                if killer["why"]:
                    status, message = "timeout", killer["why"]
                    log.write(f"\n!! {message} → 杀进程树 pid={proc.pid}\n")
                    log.flush()
                    self._kill_tree(proc.pid)
                    with contextlib.suppress(TimeoutExpired):
                        proc.wait(timeout=10)
                    exit_code = None
                    th.join(timeout=2)
                    break

                exit_code = proc.wait()
                th.join(timeout=5)
                log.write(f"-- phase {phase} 退出码 {exit_code}\n")
                log.flush()
                tail.append(f"-- phase {phase} 退出码 {exit_code}")
                if exit_code != 0:
                    status, message = "failed", f"phase {phase} 退出码 {exit_code}"
                    break

        self._running_info = None
        with contextlib.suppress(OSError):
            self.mb.running.unlink()
        finish(status, exit_code, message, started, queued, tail[-TAIL_LINES:])
        mark = "OK " if status == "ok" else "FAIL"
        _say(f"[{_stamp()}] req_{n:04d} 结束：[{mark}] {status} / {message}")

    @staticmethod
    def _kill_tree(pid: int) -> None:
        with contextlib.suppress(Exception):
            run_cmd(["taskkill", "/F", "/T", "/PID", str(pid)], timeout=20)

    # -- 主循环 --
    def loop(self) -> int:
        if not self.acquire():
            return 3
        self.mb.ensure()
        with contextlib.suppress(OSError):
            self.mb.running.unlink()

        _say("=" * 78)
        _say(" rt-thread-ros 守卫 —— 在沙箱外替你跑长任务（任务表驱动）")
        _say("=" * 78)
        _say(f" 仓库      : {REPO}")
        _say(f" 信箱      : {self.mb.root}   ← 会话侧往这里写 req_NNNN.json")
        _say(" 应答      : rep_NNNN.json ＋ rep_NNNN.log（退出码与完整日志）")
        _say(
            f" 调试器    : pyocd {PYOCD_PKG_DIR} "
            f"{'(已装)' if PYOCD_PKG_DIR.is_dir() else '!! 未安装：跑 python tools/pyocd/install.py'}"
        )
        _say(f" 固件      : {DEFAULT_BIN if DEFAULT_BIN.exists() else '!! 还没有 rtthread.bin，先编译'}")
        _say(f" 轮询      : 每 {POLL_SECONDS:.0f}s 一次；心跳每 {HEARTBEAT_SECONDS:.0f}s")
        _say(f" 子进程TEMP: {CHILD_TMP}  (pyocd 解包用，不继承窗口 TEMP={os.environ.get('TEMP')!r})")
        _say(f" 停滞判据  : 日志连续 {int(self.stall)}s 没有新字节 ⇒ 判卡住并连进程树一起杀")
        _say(f" 任务表    : {TASKS_FILE.name}（{len(TASKS)} 条；改文件即自动重启生效）")
        for tid, task in TASKS.items():
            _say(f"   {tid:<12} 上限 {int(task.timeout):>4}s   {task.title}")
        _say(" 拒绝      : 任意命令、多余参数、参数里的 shell 元字符 → rejected，永不执行")
        if self.once:
            _say(" 模式      : --once（处理完积压就退）")
        _say("-" * 78)
        pending = self.mb.pending()
        _say(f"[{_stamp()}] 待处理：{pending if pending else '无'}    把窗口开着就行，Ctrl+C 退出")
        _say("-" * 78)

        code_mtime = max_mtime((Path(__file__), TASKS_FILE))
        reloads = 0
        try:
            while True:
                # 长驻进程只认启动那刻加载的代码；改了脚本就该自动换一份，而不是让人再关窗口重开
                new_mtime = max_mtime((Path(__file__), TASKS_FILE))
                if new_mtime and new_mtime != code_mtime:
                    reloads += 1
                    if reloads <= 3:
                        _say(
                            f"[{_stamp()}] 检测到脚本或任务表被改动 —— 自动重启以载入新配置（第 {reloads} 次）"
                        )
                        try:
                            os.execv(sys.executable, [sys.executable, *sys.argv])
                        except OSError as exc:  # 换进程失败：退回到「继续跑老代码」
                            _say(f"!! 自动重启失败：{exc}（请 Ctrl+C 后重新双击 ai_services.bat）")
                            code_mtime = new_mtime
                    else:
                        code_mtime = new_mtime
                self.beat()
                did = False
                for n in self.mb.pending():
                    if self._stop:
                        break
                    self.run_one(n)
                    did = True
                    if self.once:
                        break
                if self.once and not did:
                    _say(f"[{_stamp()}] --once：积压已清空，退出")
                    return 0
                time.sleep(POLL_SECONDS)
        except KeyboardInterrupt:
            _say(f"\n[{_stamp()}] 收到 Ctrl+C，收尾退出（正在跑的活儿会随本进程一起结束）")
            return 0
        finally:
            self.release()
