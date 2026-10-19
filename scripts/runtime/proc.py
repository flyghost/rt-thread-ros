"""子进程：全仓唯一的 `subprocess` 出口。

设计要点：
- 默认 **拿到完整输出**（`capture=True`）、**不抛异常**（`check=False`），因为多数调用点要自己决定
  失败后干什么；确实想「失败即抛」时用 `result.check()` 或 `run(..., check=True)`。
- 统一处理编码：Windows 控制台默认 cp936，子进程若输出 UTF-8 会乱码；这里统一
  `encoding="utf-8", errors="replace"`，并给子进程钉上 `PYTHONIOENCODING=utf-8`。
- 需要**实时日志**（长时间构建）时用 `run_streaming()`：逐行回调，不把输出攒在内存里。
- 需要句柄自己管（守卫的泵线程）时用 `popen()`，这是明确的逃生口，调用方负责收尾。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from runtime.errors import CommandFailed, ToolMissingError

DEFAULT_TIMEOUT = 1800.0

# 新窗口启动（串口 hub 需要独立控制台）；非 Windows 上为 0。
CREATE_NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)

# `Popen.wait()` 超时抛的类型；调用方要精确捕获时用这个名字，不必再 import subprocess。
TimeoutExpired = subprocess.TimeoutExpired


@dataclass(frozen=True)
class Result:
    """一次子进程调用的结果（stdout/stderr 已解码成 str）。"""

    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    def check(self, *, hint: str = "") -> Result:
        """非 0 退出时抛 CommandFailed（带上 stderr 尾部），否则返回自身。"""
        if not self.ok:
            detail = self.stderr or self.stdout
            raise CommandFailed(self.argv, self.returncode, detail if not hint else f"{hint}\n{detail}")
        return self


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """子进程环境：在当前环境上钉住 UTF-8 输出，避免中文在管道里乱码。"""
    import os

    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("PYTHONUNBUFFERED", "1")
    if extra:
        env.update({k: str(v) for k, v in extra.items()})
    return env


def run(
    argv: Sequence[str] | str,
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = DEFAULT_TIMEOUT,
    capture: bool = True,
    check: bool = False,
    stdin_text: str | None = None,
) -> Result:
    """跑一条命令并等它结束。

    `argv` 传列表（不经 shell，避免引号/通配符/注入问题）；传字符串时按 shell 语义执行，
    仅用于确实需要 shell 的场合。
    """
    args: list[str] | str = list(argv) if not isinstance(argv, str) else argv
    printable = tuple(args) if isinstance(args, list) else (args,)
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd is not None else None,
            env=child_env(env),
            capture_output=capture,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            input=stdin_text,
        )
    except FileNotFoundError as exc:
        raise ToolMissingError(printable[0], hint="确认它在 PATH 里，或改用绝对路径") from exc
    except subprocess.TimeoutExpired as exc:
        raise CommandFailed(printable, -1, f"超时（{timeout}s）已终止") from exc

    result = Result(
        argv=printable,
        returncode=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
    )
    return result.check() if check else result


def run_streaming(
    argv: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float | None = DEFAULT_TIMEOUT,
    on_line: object = None,
) -> Result:
    """边跑边把输出逐行交给回调（用于构建/烧录这类长时间任务）。"""
    args = list(argv)
    try:
        proc = subprocess.Popen(
            args,
            cwd=str(cwd) if cwd is not None else None,
            env=child_env(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
    except FileNotFoundError as exc:
        raise ToolMissingError(args[0], hint="确认它在 PATH 里，或改用绝对路径") from exc

    lines: list[str] = []
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            lines.append(line)
            if callable(on_line):
                on_line(line)
        returncode = proc.wait(timeout=timeout)
    finally:
        if proc.poll() is None:
            proc.kill()
    return Result(argv=tuple(args), returncode=returncode, stdout="".join(lines), stderr="")


def popen(
    argv: Sequence[str],
    *,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    creationflags: int = 0,
) -> subprocess.Popen[str]:
    """逃生口：需要自己管句柄时用（调用方负责 wait/kill 与关闭管道）。"""
    args = list(argv)
    try:
        return subprocess.Popen(
            args,
            cwd=str(cwd) if cwd is not None else None,
            env=child_env(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
        )
    except FileNotFoundError as exc:
        raise ToolMissingError(args[0], hint="确认它在 PATH 里，或改用绝对路径") from exc


def which(name: str) -> str | None:
    """在 PATH 里找可执行文件；找不到返回 None。"""
    return shutil.which(name)


def python_exe() -> str:
    """当前解释器绝对路径（子进程复用同一解释器的场景很多）。"""
    return sys.executable


def stream_stdout(stream: IO[str] | None) -> Iterable[str]:
    """把 Popen 的 stdout 当可迭代行用（None 时给空迭代）。"""
    if stream is None:
        return ()
    return iter(stream)
