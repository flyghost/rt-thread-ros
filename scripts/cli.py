"""统一入口：`python scripts/cli.py <命令> [参数...]`。

为什么要有它
------------
`scripts/` 下十几个入口脚本各有一套参数与帮助，人和 AI 都得记「哪条命令属于哪个文件」。
这里只做**路由**：把命令名映射到既有 `main(argv)`，不改各脚本行为，也不复制业务逻辑。

设计边界
--------
* **不做业务**：这里是 dispatch + 公共开关（`-v/--verbose`、`-q/--quiet`、`--json`）。
* **不替代**：老入口（`scripts/run_rtros.py build`、`scripts/quality.py` …）继续可用，
  `ai_services.py` 的命令表与 `scripts/README.md` 的对照表也都指向这些老入口。
* **`--json` 只覆盖本文件自己产出的输出**（`list`、`doctor`、`status`）；其它命令原样透传，
  真要机器可读输出时由对应脚本自己加，避免"外壳猜格式"。

用法
----
    python scripts/cli.py list                 # 有哪些命令（--json 输出机器可读清单）
    python scripts/cli.py doctor               # 环境自检（解释器/工具/串口/烧录器）
    python scripts/cli.py status --json        # 构建状态（入口、目录、产物、pyocd）
    python scripts/cli.py build-flash -j 8     # 等价 python scripts/run_rtros.py build build-flash -j 8
    python scripts/cli.py hub --com COM46      # 等价 python scripts/run_rtros.py hub --com COM46

退出码：0 成功，1 运行时失败，2 用法错误。
"""

# __pycache__ 统一写到仓库 out/pycache：仓库根由本文件位置直接推出（parents[1]），不做搜索
import sys as _sys
from pathlib import Path as _Path

_sys.pycache_prefix = str(_Path(__file__).resolve().parents[1] / "out" / "pycache")

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import os as _os  # noqa: E402

sys.path.insert(
    0, _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), *([".."] * 0), "src")
)  # rtros 包（P2）：唯一的包导入根
from rtros.runtime import logging as log  # noqa: E402

# 命令表：(名字, 分组, 帮助, 目标)
# 目标写成 "模块:函数" 的字符串，dispatch 时才 import —— 保证 `cli.py list` 秒回，
# 也不会因为某个子系统缺依赖（如没装 pyserial）而让整个入口起不来。
COMMANDS: dict[str, tuple[str, str, str]] = {
    "list": ("基础", "列出所有命令", "cli:_cmd_list"),
    "doctor": ("基础", "环境自检（解释器/工具/串口/烧录器）", "cli:_cmd_doctor"),
    "status": ("构建", "构建状态（入口/目录/产物/pyocd）", "cli:_cmd_status"),
    "build": ("构建", "编译（默认项目 projects/base）", "firmware.build:main"),
    "build-flash": ("构建", "编译 + 烧录", "firmware.build:main"),
    "flash": ("构建", "只烧录", "firmware.build:main"),
    "clean": ("构建", "清理中间文件与产物", "firmware.build:main"),
    "menuconfig": ("构建", "Kconfig 菜单（固定在板目录执行）", "firmware.build:main"),
    "quality": ("质量", "ruff / mypy / pytest（透传给 scripts/quality.py）", "quality:main"),
    "guard": ("服务", "沙箱外执行器（信箱协议）", "guard.cli:main"),
    "hub": ("服务", "串口 hub（默认 COM46/115200）", "serial_hub.serial_hub:main"),
    "dump": ("采集", "采集一次 dump", "ramdump.dump.dump:main"),
    "recv": ("采集", "持续接收 dump", "ramdump.dump.receive:main"),
    "analyze": (
        "采集",
        "离线解析 dump（参数与 ramdump_analyzer.py 相同）",
        "ramdump.analyzer.ramdump_analyzer:main",
    ),
}

# 这些命令把多余参数原样交给子系统
PASSTHROUGH = {
    "build",
    "build-flash",
    "flash",
    "clean",
    "menuconfig",
    "quality",
    "guard",
    "hub",
    "dump",
    "recv",
    "analyze",
}


def _resolve(target: str) -> Any:
    """把 'pkg.mod:func' 变成可调用对象。"""
    mod_name, _, attr = target.partition(":")
    module = __import__(mod_name, fromlist=["_"])
    return getattr(module, attr)


def _cmd_list(as_json: bool) -> int:
    rows = [
        {"name": name, "group": group, "help": help_text} for name, (group, help_text, _) in COMMANDS.items()
    ]
    if as_json:
        log.human(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    log.human(f"{'命令':<14}{'分组':<6}说明")
    log.human("-" * 72)
    for name, (group, help_text, _) in COMMANDS.items():
        log.human(f"{name:<14}{group:<6}{help_text}")
    return 0


def _quality_pkg() -> Path:
    """质量工具装在仓内 `scripts/tools/pyquality/pkg`（gitignore），存在就以它为准。"""
    return _SCRIPTS / "tools" / "pyquality" / "pkg"


def _tool_versions() -> dict[str, str | None]:
    """四个工具的版本；先找仓内 `scripts/tools/pyquality/pkg`，找不到退回当前解释器环境。"""
    from rtros.runtime import proc

    pkg = _quality_pkg()
    env = proc.child_env({"PYTHONPATH": str(pkg)}) if pkg.is_dir() else None
    out: dict[str, str | None] = {}
    for name in ("ruff", "mypy", "pytest", "pre_commit"):
        try:
            res = proc.run([sys.executable, "-m", name, "--version"], env=env, timeout=120)
        except Exception:  # 工具没装/起不来都算「没有」，doctor 只报告不失败
            out[name] = None
            continue
        text = (res.stdout or res.stderr or "").strip().splitlines()
        out[name] = text[0].strip() if res.returncode == 0 and text else None
    return out


def _cmd_doctor(as_json: bool) -> int:
    """环境自检：解释器、仓根、质量工具、烧录器、串口。任何一项缺失只报告，退出码仍 0。"""
    from rtros.firmware import config, pyocd

    started = time.time()
    ports: list[str] = []
    try:
        import serial.tools.list_ports as list_ports

        ports = [f"{p.device} {p.description}" for p in list_ports.comports()]
    except Exception as exc:  # 没装 pyserial 也要能自检
        log.warn(f"枚举串口失败：{exc}")

    pyocd_version: str | None = None
    try:
        pyocd_version = pyocd.check()
    except Exception as exc:
        log.warn(f"pyocd 不可用：{exc}")

    info: dict[str, Any] = {
        "python": sys.executable,
        "python_version": sys.version.split()[0],
        "repo": str(config.REPO_ROOT),
        "entry": {"kind": config.ENTRY_KIND, "dir": str(config.ENTRY_DIR)},
        "tools": _tool_versions(),
        "quality_pkg": str(_quality_pkg()),
        "pyocd": {"version": pyocd_version, "pack": str(config.PYOCD_PACK)},
        "serial_ports": ports,
        "elapsed_s": round(time.time() - started, 2),
    }
    if as_json:
        log.human(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    log.human(f"解释器   : {info['python']} (Python {info['python_version']})")
    log.human(f"仓库根   : {info['repo']}")
    log.human(f"构建入口 : {info['entry']['dir']} ({info['entry']['kind']})")
    log.human(f"质量工具 : {info['quality_pkg']}")
    for name, version in info["tools"].items():
        log.human(f"{name:<9}: {version or '未安装'}")
    log.human(f"pyocd    : {pyocd_version or '不可用'}")
    log.human(f"串口     : {len(ports)} 个" + (f"（{ports[0]} …）" if ports else ""))
    return 0


def _cmd_status(as_json: bool) -> int:
    """构建状态：入口、中间文件目录、产物目录、产物大小、pyocd 版本。"""
    from rtros.firmware import config, pyocd

    bin_path = config.TARGET_BIN
    elf_path = config.TARGET_ELF
    info: dict[str, Any] = {
        "entry": {"kind": config.ENTRY_KIND, "dir": str(config.ENTRY_DIR)},
        "board": str(config.BSP_DIR),
        "build_dir": str(config.BUILD_DIR),
        "artifact_dir": str(config.ARTIFACT_DIR),
        "bin": str(bin_path),
        "bin_exists": bin_path.is_file(),
        "bin_bytes": bin_path.stat().st_size if bin_path.is_file() else 0,
        "elf_exists": elf_path.is_file(),
        "pyocd_target": config.PYOCD_TARGET,
    }
    try:
        info["pyocd_version"] = pyocd.check()
    except Exception as exc:
        info["pyocd_version"] = None
        log.diag(f"pyocd 不可用：{exc}")
    if as_json:
        log.human(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    log.human(f"构建入口 : {info['entry']['dir']} ({info['entry']['kind']})")
    log.human(f"板级 BSP : {info['board']}")
    log.human(f"中间文件 : {info['build_dir']}")
    log.human(f"产物目录 : {info['artifact_dir']}")
    log.human(
        f"固件     : {info['bin']}（{'存在，' + str(info['bin_bytes']) + ' B' if info['bin_exists'] else '缺失'}）"
    )
    log.human(f"pyocd    : {info['pyocd_version'] or '不可用'}（target={info['pyocd_target']}）")
    return 0 if info["bin_exists"] else 1


def _dispatch(name: str, rest: list[str]) -> int:
    group_help_target = COMMANDS.get(name)
    if group_help_target is None:
        log.error(f"未知命令：{name}")
        log.error("可用命令见：python scripts/cli.py list")
        return 2
    target = group_help_target[2]
    if target.startswith("cli:"):
        as_json = "--json" in rest
        return {"_cmd_list": _cmd_list, "_cmd_doctor": _cmd_doctor, "_cmd_status": _cmd_status}[
            target.split(":", 1)[1]
        ](as_json)

    entry = _resolve(target)
    if name in ("build", "build-flash", "flash", "clean", "menuconfig"):
        # firmware.build.main 需要命令名作为第一个位置参数
        return int(entry([name, *rest]))
    if name == "analyze":
        # 该脚本的 main() 直接读 sys.argv，这里临时替换再还原
        saved = sys.argv
        sys.argv = ["ramdump_analyzer.py", *rest]
        try:
            return int(entry())
        finally:
            sys.argv = saved
    return int(entry(rest))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="cli.py",
        description="rt-thread-ros 统一入口（路由到既有脚本，不复制业务逻辑）",
        epilog="命令清单：python scripts/cli.py list",
    )
    ap.add_argument("-v", "--verbose", action="count", default=0, help="诊断信息（可叠加）")
    ap.add_argument("-q", "--quiet", action="store_true", help="只输出结果/错误")
    ap.add_argument("--json", action="store_true", help="机器可读输出（仅 list/doctor/status）")
    ap.add_argument("command", nargs="?", help="见 python scripts/cli.py list")
    ap.add_argument("args", nargs=argparse.REMAINDER, help="透传给子命令的参数")
    ns = ap.parse_args(argv)

    log.setup("quiet" if ns.quiet else ("verbose" if ns.verbose else "normal"))

    if not ns.command:
        _cmd_list(ns.json)
        return 0

    rest = list(ns.args)
    if ns.json and "--json" not in rest:
        rest.append("--json")
    return _dispatch(ns.command, rest)


if __name__ == "__main__":
    sys.exit(main())
