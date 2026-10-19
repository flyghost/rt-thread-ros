"""请求校验与命令拼装：把「请求里写了什么」变成「要跑的 argv」。

安全边界都在这一层：
- 请求字段必须落在该任务的 `allow` 白名单里；
- `bin` 只能是仓库内的相对路径，扩展名受限；
- `target` 只允许 `[A-Za-z0-9_.+-]`；
- 拼 argv 时**不经过 shell**，占位符的值只来自 tasks.toml 的 `[paths]` 与已校验参数。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from guard.config import (
    DEFAULT_BIN,
    DEFAULT_TARGET,
    PATHS,
    PROTOCOL,
    PY_PKG_PY,
    PYOCD_PKG_DIR,
    REPO,
    TASKS,
    Task,
)

PROBE_SRC = r"""
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
"""


USB_SRC = r"""
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
"""


SAFE_NAME = re.compile(r"^[A-Za-z0-9_.+-]{1,64}$")


BAD_CHARS = set("&|;<>$`\"'\\ \t\n*?[]{}()!^%")


def validate_request(req: dict) -> tuple[dict | None, str]:
    """通过返回 (规范化后的参数, "")，否则返回 (None, 拒绝原因)。会话侧与守卫共用。"""
    if req.get("protocol") != PROTOCOL:
        return None, f"protocol 必须是 {PROTOCOL}"
    action = req.get("action")
    if action not in TASKS:
        return None, f"任务不在白名单：{action!r}（tasks.toml 里只有 {', '.join(TASKS)}）"
    raw = req.get("args") or {}
    if not isinstance(raw, dict):
        return None, "args 必须是对象"
    extra = set(raw) - set(TASKS[action].allow) - {"note"}
    if extra:
        return None, f"多余的参数名：{sorted(extra)}"

    args: dict = {}
    target = raw.get("target") or DEFAULT_TARGET
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


def _expand_paths() -> dict[str, str]:
    """[paths] → 占位符表；值是相对路径的补成仓内绝对路径。

    注意键是「裸名」：`str.format_map` 只认 `{名字}` 里的名字，不认带花括号的键。
    """
    table: dict[str, str] = {"repo": str(REPO), "python": sys.executable}
    for key, value in PATHS.items():
        for token, resolved in list(table.items()):
            value = value.replace("{" + token + "}", resolved)
        path = Path(value)
        table[key] = str(path if path.is_absolute() else (REPO / value))
    return table


def _bin_abs(args: dict) -> str:
    rel = args.get("bin")
    return str((REPO / rel) if rel else DEFAULT_BIN)


def _builtin_argv(name: str) -> list[str]:
    """内嵌在 guard.py 里的任务实现（需要把一段 Python 源码喂给解释器）。"""
    if name == "probe":
        return [sys.executable, "-c", PROBE_SRC, str(PYOCD_PKG_DIR)]
    if name == "usb":
        return [str(PY_PKG_PY), "-c", USB_SRC]
    if name == "selftest":
        return [sys.executable, "-c", "print('guard selftest ok')"]
    raise SystemExit(f"tasks.toml 里写了未知 builtin：{name}")


def _cwd_of(task: Task) -> Path:
    path = Path(task.cwd)
    return path if path.is_absolute() else (REPO / task.cwd)


def build_argv(action: str, args: dict) -> tuple[list[list[str]], Path]:
    """按任务模板拼 argv：返回 (命令序列, 工作目录)。不经过 shell。"""
    task = TASKS[action]
    if task.builtin:
        return ([_builtin_argv(task.builtin)], _cwd_of(task))
    table = _expand_paths()
    table["bin"] = _bin_abs(args)
    table["target"] = args.get("target") or DEFAULT_TARGET
    cmds = [[token.format_map(table) for token in argv] for argv in task.run]
    return (cmds, _cwd_of(task))
