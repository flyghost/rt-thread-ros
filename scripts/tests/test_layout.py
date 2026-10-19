"""布局与文件格式的硬约束：行数预算、bat 的 ASCII+CRLF、模块 docstring。"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent
SKIP_DIRS = {"__pycache__", "pkg"}
MAX_LINES = 400


def _python_files() -> list[Path]:
    out = []
    for path in SCRIPTS.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts) or "pytest-cache-files" in str(path):
            continue
        out.append(path)
    return out


PRODUCTION = [p for p in _python_files() if "tests" not in p.parts and "test" not in p.parts]
BATS = [
    path
    for path in list(REPO.glob("*.bat")) + list(SCRIPTS.rglob("*.bat"))
    if any(part not in SKIP_DIRS for part in path.parts)
]


@pytest.mark.parametrize("path", PRODUCTION, ids=lambda p: str(p.relative_to(SCRIPTS)))
def test_file_within_line_budget(path: Path) -> None:
    """单个文件不超过 400 行（超了说明该拆）。"""
    lines = len(path.read_text(encoding="utf-8").splitlines())
    assert lines <= MAX_LINES, f"{path.relative_to(SCRIPTS)} 有 {lines} 行"


@pytest.mark.parametrize("path", PRODUCTION, ids=lambda p: str(p.relative_to(SCRIPTS)))
def test_module_has_docstring(path: Path) -> None:
    """每个模块开头都要有 docstring 说明它负责什么（shebang/编码行允许在前面）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert ast.get_docstring(tree), f"{path.relative_to(SCRIPTS)} 缺模块 docstring"


@pytest.mark.parametrize("path", BATS, ids=lambda p: str(p.relative_to(REPO)))
def test_bat_is_ascii_crlf(path: Path) -> None:
    """.bat 必须纯 ASCII + CRLF：cmd 按代码页解析，中文与纯 LF 都出过事。"""
    raw = path.read_bytes()
    assert b"\x00" not in raw
    non_ascii = [i for i, byte in enumerate(raw) if byte > 0x7F]
    assert not non_ascii, f"{path.name} 有 {len(non_ascii)} 个非 ASCII 字节（首个偏移 {non_ascii[0]}）"
    assert raw.count(b"\r\n") == raw.count(b"\n"), f"{path.name} 存在纯 LF 行"
    assert raw.endswith(b"\r\n"), f"{path.name} 末尾缺 CRLF"


# 包内部（src/rtros）用 rtros.paths.pycache_prefix() 是正确写法，不参与本约束；
# 这里管的是「散落在 scripts/ 各处的旧入口脚本」。
ENTRY_FILES = [
    p
    for p in PRODUCTION
    if "pycache_prefix" in p.read_text(encoding="utf-8") and "src" not in p.relative_to(SCRIPTS).parts[:1]
]


@pytest.mark.parametrize("path", ENTRY_FILES, ids=lambda p: str(p.relative_to(SCRIPTS)))
def test_pycache_prefix_uses_explicit_parent(path: Path) -> None:
    """仓库根必须由文件位置直接推出（parents[N]），不许靠搜索标记文件。

    搜索式写法（`next(p for p in parents if ...)`）曾被 scripts/AGENTS.md 骗到，
    把 sys.pycache_prefix 指向 scripts/out/pycache，字节码分裂到两处。
    """
    text = path.read_text(encoding="utf-8")
    assert "pycache_prefix" in text
    assert "parents[" in text, f"{path.relative_to(SCRIPTS)} 没有用 parents[N] 推仓库根"
    assert "next(p for p in" not in text, f"{path.relative_to(SCRIPTS)} 仍在搜索标记文件"
    assert '".git"' not in text or "parents[" in text
