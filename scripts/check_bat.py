#!/usr/bin/env python3
"""校验 .bat/.cmd 文件是「纯 ASCII + CRLF」——这两个约束都是 cmd.exe 的硬要求。

为什么需要这个检查（都是踩过的坑）：
    * 非 ASCII 字节：cmd.exe 按控制台代码页（本机 cp936）解析脚本，UTF-8 中文会被
      拆成乱码命令 → `'…' is not recognized as an internal or external command`。
    * 纯 LF 换行：`goto`/标签解析错乱，实测能让脚本进入无限循环刷屏。

用法：
    python scripts/check_bat.py a.bat b.cmd     # 有违规退出码 1，否则 0
    python scripts/check_bat.py                 # 不带参数：检查仓库里所有 .bat/.cmd
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

# 这些目录不用检查：git 内部备份、被忽略的产物、第三方只读资料（不可能改）。
SKIP_DIRS = {".git", "third-party", "out", "build", "node_modules", "scratch", "pkg", "__pycache__"}


def _iter_bats(root: Path):
    """按目录遍历所有 .bat/.cmd，跳过 SKIP_DIRS 里的目录。"""
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            entries = list(cur.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir():
                if entry.name not in SKIP_DIRS:
                    stack.append(entry)
            elif entry.suffix.lower() in {".bat", ".cmd"}:
                yield entry


def check_one(path: Path) -> list[str]:
    """返回该文件的违规清单；空列表表示通过。"""
    data = path.read_bytes()
    problems: list[str] = []

    bad = [(i, b) for i, b in enumerate(data) if b > 0x7F]
    if bad:
        offset, byte = bad[0]
        problems.append(
            f"含 {len(bad)} 个非 ASCII 字节（首个在偏移 {offset}，0x{byte:02X}）"
            " —— cmd 会按代码页解析成乱码"
        )

    lone_lf = 0
    i = 0
    while i < len(data):
        if data[i] == 0x0A and (i == 0 or data[i - 1] != 0x0D):
            lone_lf += 1
        i += 1
    if lone_lf:
        problems.append(f"含 {lone_lf} 个裸 LF —— 必须全部是 CRLF，否则 goto/标签解析错乱")

    if data and not data.endswith(b"\r\n"):
        problems.append("文件末尾缺少 CRLF 换行")

    if b"\x00" in data:
        problems.append("含 NUL 字节（不是文本文件）")

    return problems


def main(argv: list[str]) -> int:
    if argv:
        files = [Path(a) for a in argv if not any(part in SKIP_DIRS for part in Path(a).parts)]
    else:
        files = sorted(_iter_bats(REPO))

    failed = 0
    for path in files:
        if not path.exists():
            print(f"  MISS {path}")
            failed += 1
            continue
        problems = check_one(path)
        if problems:
            failed += 1
            print(f"  FAIL {path}")
            for p in problems:
                print(f"       - {p}")

    total = len(files)
    if failed:
        print(f"\n{len([f for f in files if f.exists()]) - failed} 通过 / {failed} 失败（共 {total}）")
        return 1
    print(f"OK：{total} 个 .bat/.cmd 全部为纯 ASCII + CRLF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
