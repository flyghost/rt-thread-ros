"""pyocd 相关动作：查版本、烧录、擦除、复位。

约定：
- pyocd 只有一份实现（`scripts/tools/pyocd/pkg`，由 `scripts/tools/pyocd/install.py` 装），因此这里
  固定用 `python -m pyocd`，并把 `PYTHONPATH` 指到该目录；
- 芯片定义不读用户目录缓存，显式传仓内 pack（离线、可复现）。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from rtros.firmware.config import (
    OUT_BIN_DIR,
    PYOCD_FLASH_OPTS,
    PYOCD_PACK,
    PYOCD_PKG_DIR,
    PYOCD_PY,
    PYOCD_TARGET,
    REPO_ROOT,
    TARGET_BIN,
    TARGET_ELF,
    TARGET_MAP,
)
from rtros.firmware.exec import run
from rtros.runtime import proc


class PyocdUnavailable(RuntimeError):
    """pyocd 或芯片 pack 不可用（属于环境问题，不是使用者参数错）。"""


def pyocd_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PYOCD_PKG_DIR)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def pyocd_argv(*args: str) -> list[str]:
    return [str(PYOCD_PY), "-m", "pyocd", *args]


def check() -> str:
    """返回 pyocd 版本号；pyocd 或 pack 缺失时抛 `PyocdUnavailable`。"""
    if not PYOCD_PKG_DIR.is_dir():
        raise PyocdUnavailable(
            f"pyocd 未安装：{PYOCD_PKG_DIR}\n         先运行：python {PYOCD_PKG_DIR.parent / 'install.py'}"
        )
    if not PYOCD_PACK.exists():
        raise PyocdUnavailable(f"芯片 pack 缺失：{PYOCD_PACK}")
    done = proc.run(pyocd_argv("--version"), env=pyocd_env(), timeout=120)
    if done.returncode != 0:
        raise PyocdUnavailable(f"pyocd 跑不起来：{(done.stderr or done.stdout).strip()}")
    return (done.stdout or done.stderr).strip().splitlines()[0]


def _with_pack(args: list[str]) -> list[str]:
    """凡是需要解析芯片的任务，都显式带仓内 pack。"""
    return [*args, "--pack", str(PYOCD_PACK)]


def flash(bin_path: str | Path | None = None) -> int:
    """把固件烧进板子；成功返回 0。"""
    target = TARGET_BIN if bin_path is None else Path(bin_path)
    try:
        version = check()
    except PyocdUnavailable as exc:
        print(f"[flash] {exc}")
        return 1
    if not target.exists():
        print(f"[flash] 固件不存在：{target}（先编译）")
        return 1
    print(f"[flash] pyocd {version} | {PYOCD_TARGET} | {target} ({target.stat().st_size:,} B)")
    rc = run(
        _with_pack(
            [
                *pyocd_argv("flash", "--target", PYOCD_TARGET),
                *PYOCD_FLASH_OPTS,
                str(target),
            ]
        ),
        REPO_ROOT,
        pyocd_env(),
    )
    if rc == 0:
        _copy_legacy_artifacts()
    return rc


def erase() -> int:
    """整片擦除（慎用，会连参数区一起清掉）。"""
    return run(_with_pack([*pyocd_argv("erase", "--chip", "--target", PYOCD_TARGET)]), REPO_ROOT, pyocd_env())


def reset() -> int:
    """复位目标芯片。"""
    return run(_with_pack([*pyocd_argv("reset", "--target", PYOCD_TARGET)]), REPO_ROOT, pyocd_env())


def list_probes() -> int:
    """列出 pyocd 能看到的调试器（排查「认不到探针」时用）。"""
    return run(_with_pack([*pyocd_argv("list", "-v")]), REPO_ROOT, pyocd_env())


def _copy_legacy_artifacts() -> None:
    """产物本来就落在 out/bin/<入口名>/（SConstruct 指定），这里只对旧布局做一次搬迁。"""
    OUT_BIN_DIR.mkdir(parents=True, exist_ok=True)
    for src in (TARGET_BIN, TARGET_ELF, TARGET_MAP):
        if src.exists() and src.parent != OUT_BIN_DIR:
            shutil.copy2(src, OUT_BIN_DIR / src.name)
