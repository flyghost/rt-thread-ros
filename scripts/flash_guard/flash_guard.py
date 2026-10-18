#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""flash_guard.py — 烧录守卫：把「沙箱里跑不了」的硬件动作交给一个由人手动启动的进程。

问题不是权限不够，而是进程位置不对：
  `pyocd`（在 `tools/pyocd/pkg`，用 `python -m pyocd` 跑）启动时要把随包的 DLL / 临时文件
  解压到临时目录；DSH 的受限文件沙箱（workspace-write）只允许写工作区，于是它必然报
  `VCRUNTIME140.dll could not be extracted! / fopen: Permission denied`（0.27 的 PyInstaller 单文件
  exe 时代是同一堵墙）。提权（danger-full-access）不但没解决，还把 job runner 拖挂（0xC0000142）。

所以这里换一条路：**AI 不越界，改由人开一个不受限的窗口**。
  人        启动本脚本（双击仓根 `ai_services.bat`），窗口开着就行；
  会话侧    用 `--request` 把动作写进文件信箱（沙箱内可跑，只读写仓内文件）；
  守卫      捡到请求 → 按白名单现拼 argv（不经 shell）→ 在自己这个放行的进程里跑 →
            把退出码与日志写回应答文件；
  会话侧    用 `--wait` 收应答，或事后 `--list` / 读 `rep_NNNN.log`。

边界：守卫是「白名单执行器」，不是远程 shell —— 不接任意命令、不联网、不读凭据，
只认下面 ACTIONS 里那几个动作，参数值里带 shell 元字符一律拒。

用法
  人（沙箱之外，常驻；Ctrl+C 退出）：
      python scripts\\flash_guard\\flash_guard.py
      python scripts\\flash_guard\\flash_guard.py --once      # 处理完积压就退（可挂计划任务）
  会话侧（沙箱内可跑）：
      python scripts\\flash_guard\\flash_guard.py --status
      python scripts\\flash_guard\\flash_guard.py --list
      python scripts\\flash_guard\\flash_guard.py --request flash --wait
      python scripts\\flash_guard\\flash_guard.py --request build_flash --wait --wait-timeout 600
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

PROTOCOL = 1

REPO = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------- 板级事实（改这里）
# 唯一 pyocd：pip 装进 tools/pyocd/pkg（gitignore），用 `python -m pyocd` 运行。
# 不再有"自带 exe 兜底"：0.27 的 pyocd.exe 认不到 CMSIS-DAP v2（WinUSB/bulk）探针，
# 留着只会让调用方选错实现。装法见 tools/pyocd/install.py。
PYOCD_DIR = REPO / "tools" / "pyocd"
PYOCD_PKG_DIR = PYOCD_DIR / "pkg"
# pkg/ 里的 cffi、hidapi 是 CPython 3.13 的二进制 wheel，必须用同 ABI 的解释器。
PY_PKG_PY = Path(r"E:\software\InstallerEdition\DevTools\Python\Python313\python.exe")
# 新版 pyocd 不内置芯片定义，必须显式给仓内精简 pack（100% 离线、可复现）。
PYOCD_PACK = PYOCD_DIR / "packs" / "Keil.STM32F4xx_DFP.2.14.0-small.pack"
PYOCD = [str(PY_PKG_PY), "-m", "pyocd"]
# 编译/烧录统一入口（build_and_flash.bat 已删）
BUILD_ENTRY = REPO / "scripts" / "firmware" / "build.py"
BSP_DIR = REPO / "bsp" / "stm32" / "stm32f407-atk-explorer"
DEFAULT_BIN = BSP_DIR / "rtthread.bin"
DEFAULT_TARGET = "STM32F407VE"

ENV_ROOT = Path(r"E:\software\EnvEdition\rt-thread-env\env-windows")
VENV_PY = ENV_ROOT / ".venv" / "Scripts" / "python.exe"
ARM_GCC_BIN = ENV_ROOT / "tools" / "gnu_gcc" / "arm_gcc" / "mingw" / "bin"

# 动作白名单：action -> (单次总时长上限秒, 说明)
ACTIONS = {
    "flash": (180, "pyocd flash：把 rtthread.bin 烧进板子"),
    "build_flash": (1100, "编译 + 烧录（都走 scripts/firmware/build.py）"),
    "build": (900, "只在守卫里编译（沙箱内其实也能编，留着给环境异常时用）"),
    "list": (60, "pyocd list -v：看看调试器认不认得到"),
    "erase": (180, "pyocd erase --chip：整片擦除"),
    "reset": (60, "pyocd reset：复位目标"),
    "probe": (90, "环境自检：TEMP 能不能写、pyocd 版本、pkg 在不在"),
    "usb": (60, "用 pyusb/libusb 枚举 USB 设备（看 libusb 到底能看见谁）"),
    "selftest": (30, "守卫自检：只跑一条无害的 python -c，用来验证信箱协议"),
}

POLL_SECONDS = 2.0
HEARTBEAT_SECONDS = 2.0
RUNNING_SECONDS = 1.0
STALL_SECONDS = 180.0
DEFAULT_EXPIRES = 900
DEFAULT_WAIT = 300.0
TAIL_LINES = 40

# 子进程统一用的临时目录：仓库内，谁开守卫谁就能写。
CHILD_TMP = REPO / "out" / "tmp"

PROBE_SRC = r'''
import os, subprocess, sys, tempfile
print("cwd      :", os.getcwd())
for k in ("TEMP", "TMP", "TMPDIR"):
    v = os.environ.get(k)
    print("%-9s: %r exists=%s" % (k, v, os.path.isdir(v) if v else None))
try:
    d = tempfile.mkdtemp(prefix="guardprobe_")
    print("mkdtemp  : ok ->", d)
    try:
        with open(os.path.join(d, "probe.tmp"), "w", encoding="utf-8") as fp:
            fp.write("ok")
        print("写入     : ok")
        os.remove(os.path.join(d, "probe.tmp"))
        os.rmdir(d)
        print("清理     : ok")
    except Exception as exc:
        # 沙箱会给 mkdtemp 造出来的目录挂一个本进程不可写的 ACL；能建不能写就说明这里有问题，
        # pyocd/pip 这类"先解包到临时目录"的程序会因此失败。
        print("写入/清理: FAILED ->", exc)
except Exception as exc:
    print("mkdtemp  : FAILED ->", exc)
pkg = sys.argv[1]
print("pyocd pkg:", pkg, "is_dir=%s" % os.path.isdir(pkg))
env = dict(os.environ); env["PYTHONPATH"] = pkg
try:
    r = subprocess.run([sys.executable, "-m", "pyocd", "--version"], env=env,
                       capture_output=True, text=True, timeout=120)
    print("  rc     :", r.returncode)
    print("  out    :", (r.stdout or "").strip()[:400])
    print("  err    :", (r.stderr or "").strip()[:400])
except Exception as exc:
    print("  FAILED :", exc)
'''

USB_SRC = r'''
import sys
try:
    import usb.core
except Exception as exc:
    print("pyusb 不可用:", exc)
    sys.exit(2)
backend = None
try:
    import libusb_package
    backend = libusb_package.get_libusb1_backend()
    print("libusb_package backend:", backend)
except Exception as exc:
    print("libusb_package 不可用:", exc)
try:
    import usb.backend.libusb1
    print("pyusb 自带 backend:", usb.backend.libusb1.get_backend())
except Exception as exc:
    print("pyusb 自带 backend 不可用:", exc)
try:
    devs = list(usb.core.find(find_all=True, backend=backend))
except Exception as exc:
    print("枚举失败:", exc)
    sys.exit(3)
print("libusb 看到的设备数:", len(devs))
for d in devs:
    try:
        print("%04x:%04x bus=%s addr=%s class=%s" % (d.idVendor, d.idProduct, d.bus, d.address, d.bDeviceClass))
    except Exception as exc:
        print("  读设备失败:", exc)
        continue
    try:
        for cfg in d:
            for intf in cfg:
                eps = [hex(e.bEndpointAddress) for e in intf]
                print("    intf %s class=%02x/%02x/%02x eps=%s"
                      % (intf.bInterfaceNumber, intf.bInterfaceClass,
                         intf.bInterfaceSubClass, intf.bInterfaceProtocol, eps))
    except Exception as exc:
        print("  读接口失败:", exc)
'''

SAFE_NAME = re.compile(r"^[A-Za-z0-9_.+-]{1,64}$")
BAD_CHARS = set('&|;<>$`"\'\\ \t\n*?[]{}()!^%')


def _say(msg: str) -> None:
    print(msg, flush=True)


def _stamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _atomic_write_json(path: Path, obj: dict) -> None:
    _atomic_write_text(path, json.dumps(obj, ensure_ascii=False, indent=2))


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong(0)
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    except Exception:
        return False


# ---------------------------------------------------------------- 信箱
class Mailbox:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.lock = root / "guard.lock"
        self.heartbeat = root / "heartbeat.json"
        self.running = root / "running.json"

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def req(self, n: int) -> Path:
        return self.root / f"req_{n:04d}.json"

    def rep(self, n: int) -> Path:
        return self.root / f"rep_{n:04d}.json"

    def log(self, n: int) -> Path:
        return self.root / f"rep_{n:04d}.log"

    def ids(self) -> list[int]:
        out = []
        if not self.root.is_dir():
            return out
        for p in self.root.glob("req_*.json"):
            m = re.match(r"req_(\d{4,})\.json$", p.name)
            if m:
                out.append(int(m.group(1)))
        return sorted(out)

    def pending(self) -> list[int]:
        return [n for n in self.ids() if not self.rep(n).exists()]

    def next_id(self) -> int:
        ids = self.ids()
        return (ids[-1] + 1) if ids else 1


# ---------------------------------------------------------------- 请求校验 + argv 组装
def validate_request(req: dict) -> tuple[dict | None, str]:
    """通过返回 (规范化后的参数, "")，否则返回 (None, 拒绝原因)。会话侧与守卫共用。"""
    if req.get("protocol") != PROTOCOL:
        return None, f"protocol 必须是 {PROTOCOL}"
    action = req.get("action")
    if action not in ACTIONS:
        return None, f"动作不在白名单：{action!r}（只接受 {', '.join(ACTIONS)}）"
    raw = req.get("args") or {}
    if not isinstance(raw, dict):
        return None, "args 必须是对象"
    extra = set(raw) - {"target", "bin", "note"}
    if extra:
        return None, f"多余的参数名：{sorted(extra)}"

    args: dict = {}
    target = raw.get("target", DEFAULT_TARGET)
    if not isinstance(target, str) or not SAFE_NAME.match(target):
        return None, "target 只许字母数字与 _ . + -"
    args["target"] = target

    if "bin" in raw:
        b = raw["bin"]
        if not isinstance(b, str) or not b:
            return None, "bin 必须是非空字符串"
        if b.startswith(("/", "\\")) or ".." in b or ":" in b:
            return None, "bin 必须是仓内相对路径，不许绝对路径 / .."
        if not re.search(r"\.(bin|hex|elf)$", b, re.I):
            return None, "bin 只接受 .bin / .hex / .elf"
        if any(ch in BAD_CHARS for ch in b):
            return None, "bin 含非法字符"
        args["bin"] = b

    for k, v in raw.items():
        if k == "note":
            continue
        if isinstance(v, str) and any(ch in BAD_CHARS for ch in v):
            return None, f"{k} 含 shell 元字符"
    note = raw.get("note")
    if note is not None and (not isinstance(note, str) or len(note) > 200):
        return None, "note 最长 200 字符"
    args["note"] = note or ""
    return args, ""


def _bin_path(args: dict) -> Path:
    rel = args.get("bin")
    return (REPO / rel) if rel else DEFAULT_BIN


def _pyocd_prefix(args: dict) -> list[str]:
    """唯一 pyocd：`python -m pyocd`（tools/pyocd/pkg 里的 0.45）。"""
    return list(PYOCD)


def _pack_opt(args: dict) -> list[str]:
    """显式给仓内 pack —— 新版 pyocd 不内置 STM32F407VE 的芯片定义。"""
    if not PYOCD_PACK.is_file():
        return []
    return ["--pack", str(PYOCD_PACK)]


def build_argv(action: str, args: dict) -> tuple[list[list[str]], Path]:
    """返回 (命令序列, 工作目录)。build_flash 是两条命令。"""
    tgt = args["target"]
    if action == "probe":
        return ([[sys.executable, "-c", PROBE_SRC, str(PYOCD_PKG_DIR)]], REPO)
    if action == "usb":
        return ([[str(PY_PKG_PY), "-c", USB_SRC]], REPO)
    if action == "selftest":
        return ([[sys.executable, "-c", "print('flash_guard selftest ok')"]], REPO)
    if action == "list":
        return ([[*_pyocd_prefix(args), "list", "-v", *_pack_opt(args)]], REPO)
    if action == "reset":
        return ([[*_pyocd_prefix(args), "reset", *_pack_opt(args), "--target", tgt]], REPO)
    if action == "erase":
        return ([[*_pyocd_prefix(args), "erase", *_pack_opt(args), "--target", tgt, "--chip"]], REPO)
    if action == "build":
        return ([[str(VENV_PY), str(BUILD_ENTRY), "build"]], REPO)

    flash_cmd = [
        *_pyocd_prefix(args),
        "flash",
        *_pack_opt(args),
        "--target",
        tgt,
        "--erase=auto",
        "--frequency=1000000",
        str(_bin_path(args)),
    ]
    if action == "flash":
        return ([flash_cmd], REPO)
    return ([[str(VENV_PY), str(BUILD_ENTRY), "build"], flash_cmd], REPO)


def _cmd_label(argv: list[str]) -> str:
    """给人看的命令标签：`python.exe -m SCons`、`pyocd flash`，别只写解释器名。"""
    exe = Path(argv[0]).name
    if "-m" in argv:
        i = argv.index("-m")
        if i + 1 < len(argv):
            return f"{exe} -m {argv[i + 1]}"
    if "pyocd" in exe.lower():
        return "pyocd " + (argv[1] if len(argv) > 1 else "")
    return exe


def child_env() -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if ENV_ROOT.is_dir():
        env["ENV_ROOT"] = str(ENV_ROOT)
        env["RTT_CC"] = "gcc"
        if ARM_GCC_BIN.is_dir():
            env["RTT_EXEC_PATH"] = str(ARM_GCC_BIN)
            env["PATH"] = str(ARM_GCC_BIN) + os.pathsep + env.get("PATH", "")
    # PyInstaller 打包的 pyocd.exe 启动时要先把自己解包到临时目录。**不要相信继承来的
    # TEMP/TMP**：实测某个窗口带着已失效的 per-session 临时路径，pyocd 直接报
    # "[18336] INTERNAL ERROR: cannot create temporary directory!" 并退 -1。
    # 这里钉到仓库内的 out/tmp —— 谁能写仓库，谁就能写它。
    try:
        CHILD_TMP.mkdir(parents=True, exist_ok=True)
        env["TEMP"] = env["TMP"] = env["TMPDIR"] = str(CHILD_TMP)
    except OSError:
        pass
    return env


def _self_mtime() -> float:
    """守卫脚本自身的修改时间的 mtime —— 用来发现「代码更新了，但进程还在跑老版本」。"""
    try:
        return Path(__file__).stat().st_mtime
    except OSError:
        return 0.0


# ---------------------------------------------------------------- 守卫侧
class Guard:
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
                "actions": {k: v[0] for k, v in ACTIONS.items()},
                "pending": len(self.mb.pending()),
                "running": self._running_info,
            },
        )

    # -- 执行一条请求 --
    def run_one(self, n: int) -> None:
        req = _read_json(self.mb.req(n))
        rep_path = self.mb.rep(n)
        log_path = self.mb.log(n)

        def finish(status: str, exit_code: int | None, message: str, started: str | None, queued: int | None, tail: list[str]) -> None:
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
                    "log": str(log_path.relative_to(REPO)) if log_path.is_relative_to(REPO) else str(log_path),
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
        total_to = self.timeout_override or ACTIONS[req["action"]][0]
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
                env["LIBUSB_DEBUG"] = "4"   # 让 libusb 自己说清楚「为什么没看见某个设备」

        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("w", encoding="utf-8", errors="replace") as log:
            for phase, argv in enumerate(cmds, 1):
                head = f"$ {' '.join(argv)}"
                log.write(head + "\n")
                log.flush()
                _say(f"[{_stamp()}]   phase {phase}/{len(cmds)}: {_cmd_label(argv)} …（上限 {int(total_to)}s）")

                try:
                    proc = subprocess.Popen(
                        argv,
                        cwd=str(cwd),
                        env=env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        bufsize=1,
                    )
                except FileNotFoundError as exc:
                    status, message = "failed", f"可执行文件不存在：{exc}"
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

                def pump() -> None:
                    nonlocal log_bytes, last_growth
                    assert proc.stdout is not None
                    for line in proc.stdout:
                        log.write(line)
                        log.flush()
                        log_bytes += len(line)
                        last_growth = time.time()
                        tail.append(line.rstrip("\n"))
                        if len(tail) > TAIL_LINES:
                            del tail[0]

                th = threading.Thread(target=pump, daemon=True)
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
                                "lastGrowthAt": datetime.fromtimestamp(last_growth).isoformat(timespec="seconds"),
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
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        pass
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
        try:
            self.mb.running.unlink()
        except OSError:
            pass
        finish(status, exit_code, message, started, queued, tail[-TAIL_LINES:])
        mark = "OK " if status == "ok" else "FAIL"
        _say(f"[{_stamp()}] req_{n:04d} 结束：[{mark}] {status} / {message}")

    @staticmethod
    def _kill_tree(pid: int) -> None:
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=20)
        except Exception:
            pass

    # -- 主循环 --
    def loop(self) -> int:
        if not self.acquire():
            return 3
        self.mb.ensure()
        try:
            self.mb.running.unlink()
        except OSError:
            pass

        _say("=" * 78)
        _say(" rt-thread-ros 烧录守卫 —— 替你跑「沙箱里跑不了」的烧录动作")
        _say("=" * 78)
        _say(f" 仓库      : {REPO}")
        _say(f" 信箱      : {self.mb.root}   ← 会话侧往这里写 req_NNNN.json")
        _say(f" 应答      : rep_NNNN.json ＋ rep_NNNN.log（退出码与完整日志）")
        _say(f" 调试器    : pyocd {PYOCD_PKG_DIR} "f"{'(已装)' if PYOCD_PKG_DIR.is_dir() else '!! 未安装：跑 python tools/pyocd/install.py'}")
        _say(f" 固件      : {DEFAULT_BIN if DEFAULT_BIN.exists() else '!! 还没有 rtthread.bin，先编译'}")
        _say(f" 轮询      : 每 {POLL_SECONDS:.0f}s 一次；心跳每 {HEARTBEAT_SECONDS:.0f}s")
        _say(f" 子进程TEMP: {CHILD_TMP}  (pyocd 解包用，不继承窗口 TEMP={os.environ.get('TEMP')!r})")
        _say(f" 停滞判据  : 日志连续 {int(self.stall)}s 没有新字节 ⇒ 判卡住并连进程树一起杀")
        _say(" 白名单    :")
        for a, (to, desc) in ACTIONS.items():
            _say(f"   {a:<12} 上限 {int(to):>4}s   {desc}")
        _say(" 拒绝      : 任意命令、多余参数、参数里的 shell 元字符 → rejected，永不执行")
        if self.once:
            _say(" 模式      : --once（处理完积压就退）")
        _say("-" * 78)
        pending = self.mb.pending()
        _say(f"[{_stamp()}] 待处理：{pending if pending else '无'}    把窗口开着就行，Ctrl+C 退出")
        _say("-" * 78)

        code_mtime = _self_mtime()
        reloads = 0
        try:
            while True:
                # 长驻进程只认启动那刻加载的代码；改了脚本就该自动换一份，而不是让人再关窗口重开
                new_mtime = _self_mtime()
                if new_mtime and new_mtime != code_mtime:
                    reloads += 1
                    if reloads <= 3:
                        _say(f"[{_stamp()}] 检测到 {Path(__file__).name} 被改动 —— 自动重启以载入新代码（第 {reloads} 次）")
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


# ---------------------------------------------------------------- 会话侧
def cmd_status(mb: Mailbox) -> int:
    hb = _read_json(mb.heartbeat) or {}
    lock = _read_json(mb.lock) or {}
    pid = hb.get("pid") or lock.get("pid")
    alive = bool(pid) and _pid_alive(int(pid))
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
        print(f"正在执行  : req_{run.get('id'):04d} {run.get('action')} —— 已跑 {run.get('elapsedSeconds')}s，日志 {run.get('logBytes')} 字节")
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
            print(f"{n:>5}  {req.get('action', '?'):<12} {'排队中':<9} {'-':>6}  写于 {req.get('createdAt') and datetime.fromtimestamp(req['createdAt']).strftime('%m-%d %H:%M:%S') or '?'}")
            continue
        ec = rep.get("exitCode")
        print(f"{n:>5}  {req.get('action', '?'):<12} {rep.get('status', '?'):<9} {('-' if ec is None else ec):>6}  {rep.get('message', '')}")
    return 0


def cmd_request(mb: Mailbox, action: str, target: str | None, binrel: str | None, note: str, expires: int, wait: bool, wait_timeout: float) -> int:
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


def main(argv: list[str] | None = None) -> int:
    for s in (sys.stdout, sys.stderr):
        try:
            # 真控制台上保持默认（Windows 走 WriteConsoleW，中文正常）；
            # 被重定向到管道/文件时强制 UTF-8，否则会被按 cp936 写出去、下游按 UTF-8 读成乱码。
            if not s.isatty():
                s.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
            else:
                s.reconfigure(errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass

    ap = argparse.ArgumentParser(
        description="rt-thread-ros 烧录守卫：白名单执行器（烧录 / 编译 / 探针），文件信箱协议",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--mailbox", default=None, help="信箱目录（默认 <仓库>/out/guard）")
    ap.add_argument("--status", action="store_true", help="守卫生不活着 ＋ 积压一览")
    ap.add_argument("--list", action="store_true", help="已处理请求一览")
    ap.add_argument("--request", metavar="ACTION", help=f"下请求：{', '.join(ACTIONS)}")
    ap.add_argument("--target", default=None, help=f"芯片型号（默认 {DEFAULT_TARGET}）")
    ap.add_argument("--bin", dest="binrel", default=None, help="要烧的固件（仓内相对路径，默认 BSP/rtthread.bin）")
    ap.add_argument("--note", default="", help="备注，最长 200 字符")
    ap.add_argument("--expires", type=int, default=DEFAULT_EXPIRES, help=f"请求有效期秒数（默认 {DEFAULT_EXPIRES}）")
    ap.add_argument("--wait", action="store_true", help="等到应答并回显日志尾")
    ap.add_argument("--wait-timeout", type=float, default=DEFAULT_WAIT, help=f"会话侧等待上限秒（默认 {DEFAULT_WAIT:.0f}）")
    ap.add_argument("--once", action="store_true", help="守卫模式：处理完积压就退")
    ap.add_argument("--timeout", type=float, default=None, help="守卫模式：覆盖单次执行上限秒")
    ap.add_argument("--stall", type=float, default=STALL_SECONDS, help=f"守卫模式：停滞判据秒（0=关闭，默认 {int(STALL_SECONDS)}）")
    ns = ap.parse_args(argv)

    mb = Mailbox(Path(ns.mailbox).resolve() if ns.mailbox else (REPO / "out" / "guard"))

    if ns.status:
        return cmd_status(mb)
    if ns.list:
        return cmd_list(mb)
    if ns.request:
        return cmd_request(mb, ns.request, ns.target, ns.binrel, ns.note, ns.expires, ns.wait, ns.wait_timeout)
    return Guard(mb, ns.once, ns.timeout, ns.stall).loop()


if __name__ == "__main__":
    sys.exit(main())
