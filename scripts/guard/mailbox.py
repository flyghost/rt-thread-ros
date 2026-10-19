"""守卫的信箱：请求/应答/日志文件的原子读写与进程判活。

拆自 executor.py，被 executor（跑任务）与 cli（会话侧下请求）共用；
这里不依赖 Guard，也不做任何执行动作。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path


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
        out: list[int] = []
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
