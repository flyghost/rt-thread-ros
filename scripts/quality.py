#!/usr/bin/env python3
"""仓库内 Python 质量的统一入口（检查 / 格式化 / 类型 / 测试）。

用法（仓库根目录或任意目录都可以）：
    python scripts/quality.py doctor        # 看工具装没装、版本对不对
    python scripts/quality.py check         # ruff check（只看不改）
    python scripts/quality.py check --fix   # ruff check --fix
    python scripts/quality.py format        # ruff format（真改文件）
    python scripts/quality.py format-check  # ruff format --check（只看不改）
    python scripts/quality.py types         # mypy（覆盖 pyproject 里 files=）
    python scripts/quality.py tests         # pytest
    python scripts/quality.py all           # check + format-check + types + tests

工具来源只有一个：`tools/pyquality/pkg`（gitignore），用 `python tools/pyquality/install.py` 安装。
所有命令都 `cwd=scripts/` 运行，让 ruff/mypy/pytest 自动读到 `scripts/pyproject.toml`。

退出码：0 全过；1 有失败；2 工具没装（先跑 install.py）。
"""

from __future__ import annotations

# __pycache__ 统一写到仓库 out/pycache：仓库根由本文件位置直接推出（parents[1]），不做搜索
import sys as _sys
from pathlib import Path as _Path

_sys.pycache_prefix = str(_Path(__file__).resolve().parents[1] / "out" / "pycache")

import argparse  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

from runtime import proc  # noqa: E402
from runtime.errors import ToolMissingError  # noqa: E402

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PKG = REPO / "tools" / "pyquality" / "pkg"
PRE_COMMIT_HOME = REPO / "out" / "precommit"


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PKG)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # 字节码统一写到 out/pycache：子进程（pytest/mypy 收集的模块）无论导入顺序如何
    # 都不会在源码树里留 __pycache__；内部再自己设 prefix 的入口也不会分裂成两处。
    env["PYTHONPYCACHEPREFIX"] = str(REPO / "out" / "pycache")
    # pre-commit 默认把缓存放 ~/.cache/pre-commit；仓内固定到 out/precommit，
    # 既避免写用户目录（受限环境会被拒），也让缓存可随时整体删除。
    env["PRE_COMMIT_HOME"] = str(PRE_COMMIT_HOME)
    return env


def _tool(name: str) -> list[str]:
    """返回调用某个工具的 argv 前缀（python -m <name>）。"""
    return [sys.executable, "-m", name]


def _have(name: str) -> bool:
    try:
        out = proc.run([*_tool(name), "--version"], env=_env(), timeout=120, cwd=HERE)
    except (OSError, ToolMissingError):
        return False
    return out.returncode == 0


def _run(label: str, argv: list[str], quiet: bool = False) -> int:
    started = time.time()
    if not quiet:
        print(f"$ {' '.join(argv)}")
    rc = proc.run(argv, env=_env(), cwd=HERE, capture=False).returncode
    print(f"[{label}] 退出码 {rc}，耗时 {time.time() - started:.1f}s")
    return rc


def doctor() -> int:
    print(f"解释器 : {sys.executable}")
    print(f"工具目录: {PKG}（{'存在' if PKG.is_dir() else '缺失'}）")
    ok = True
    for name in ("ruff", "mypy", "pytest"):
        argv = [*_tool(name), "--version"]
        try:
            out = proc.run(argv, env=_env(), timeout=120, cwd=HERE)
        except (OSError, ToolMissingError) as exc:
            print(f"{name:<7}: 调用失败 {exc}")
            ok = False
            continue
        line = (out.stdout or out.stderr or "").strip().splitlines()
        if out.returncode == 0:
            print(f"{name:<7}: {line[0] if line else '(无输出)'}")
        else:
            print(f"{name:<7}: 未安装")
            ok = False
    if not ok:
        print(f"\n安装：{sys.executable} {REPO / 'tools' / 'pyquality' / 'install.py'}")
        return 2
    return 0


def require_tools() -> int:
    missing = [n for n in ("ruff", "mypy") if not _have(n)]
    if missing:
        print(f"缺少工具：{', '.join(missing)}")
        print(f"安装：{sys.executable} {REPO / 'tools' / 'pyquality' / 'install.py'}")
        return 2
    return 0


def _hooks_install() -> int:
    """把 .pre-commit-config.yaml 装进 .git/hooks/pre-commit（每台机器一次）。"""
    if not _have("pre_commit"):
        print(f"缺少 pre-commit。安装：{sys.executable} {REPO / 'tools' / 'pyquality' / 'install.py'}")
        return 2
    PRE_COMMIT_HOME.mkdir(parents=True, exist_ok=True)
    rc = _run("pre-commit install", [*_tool("pre_commit"), "install"], quiet=True)
    if rc != 0:
        return rc
    # 生成的钩子由 git 直接调用，拿不到本进程的环境变量；把缓存目录钉进钩子，
    # 这样「人 git commit」与「AI 跑 quality.py hooks」用的是同一个仓内缓存。
    hook = REPO / ".git" / "hooks" / "pre-commit"
    if hook.is_file():
        text = hook.read_text(encoding="utf-8", errors="replace")
        if "PRE_COMMIT_HOME" not in text:
            lines = text.splitlines()
            pinned = f'export PRE_COMMIT_HOME="{PRE_COMMIT_HOME}"  # 缓存放仓内，不写用户目录'
            lines.insert(1 if lines and lines[0].startswith("#!") else 0, pinned)
            hook.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"已把 PRE_COMMIT_HOME 钉进 {hook.relative_to(REPO)}")
    return 0


def _hooks(staged: bool = False) -> int:
    """按配置跑钩子；staged=True 只检查暂存文件（提交时自动跑的就是这条）。"""
    if not _have("pre_commit"):
        print(f"缺少 pre-commit。安装：{sys.executable} {REPO / 'tools' / 'pyquality' / 'install.py'}")
        return 2
    PRE_COMMIT_HOME.mkdir(parents=True, exist_ok=True)
    argv = [*_tool("pre_commit"), "run"]
    argv += [] if staged else ["--all-files"]
    return _run("pre-commit", argv, quiet=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="quality.py",
        description="Python 质量统一入口（ruff / mypy / pytest）",
    )
    sub = ap.add_subparsers(dest="cmd")

    p_check = sub.add_parser("check", help="ruff check")
    p_check.add_argument("--fix", action="store_true", help="自动修复可修的")

    sub.add_parser("format", help="ruff format（会改文件）")
    sub.add_parser("format-check", help="ruff format --check（不改文件）")
    sub.add_parser("types", help="mypy 类型检查")
    p_tests = sub.add_parser("tests", help="pytest")
    p_tests.add_argument("args", nargs=argparse.REMAINDER, help="透传给 pytest 的参数")
    sub.add_parser("doctor", help="检查工具是否安装")
    sub.add_parser("all", help="全套：check + format-check + types + tests")
    p_hooks = sub.add_parser("hooks", help="跑 pre-commit 钩子（默认全量）")
    p_hooks.add_argument("--staged", action="store_true", help="只跑已暂存文件")
    sub.add_parser("hooks-install", help="把钩子装进 .git/hooks（每台机器一次）")

    ns = ap.parse_args(argv)
    cmd = ns.cmd or "all"

    if cmd == "doctor":
        return doctor()
    if cmd == "hooks-install":
        return _hooks_install()
    if cmd == "hooks":
        return _hooks(staged=getattr(ns, "staged", False))

    if cmd != "all":
        rc = require_tools()
        if rc != 0:
            return rc

    if cmd == "check":
        argv_check = [*_tool("ruff"), "check", "."]
        if getattr(ns, "fix", False):
            argv_check.append("--fix")
        return _run("ruff check", argv_check)

    if cmd == "format":
        return _run("ruff format", [*_tool("ruff"), "format", "."])

    if cmd == "format-check":
        return _run("ruff format --check", [*_tool("ruff"), "format", "--check", "."])

    if cmd == "types":
        return _run("mypy", [*_tool("mypy")])

    if cmd == "tests":
        extra = [a for a in getattr(ns, "args", []) if a != "--"]
        return _run("pytest", [*_tool("pytest"), *extra])

    # all
    rc = require_tools()
    if rc != 0:
        return rc
    results: list[tuple[str, int]] = []
    results.append(("ruff check", _run("ruff check", [*_tool("ruff"), "check", "."])))
    results.append(
        ("ruff format --check", _run("ruff format --check", [*_tool("ruff"), "format", "--check", "."]))
    )
    results.append(("mypy", _run("mypy", [*_tool("mypy")])))
    results.append(("pytest", _run("pytest", [*_tool("pytest")])))

    print("\n== 汇总 ==")
    for label, code in results:
        print(f"  {label:<22} {'PASS' if code == 0 else f'FAIL({code})'}")
    return 0 if all(code == 0 for _, code in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
