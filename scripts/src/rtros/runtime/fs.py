"""文件读写：统一编码、统一原子写、统一 JSON/TOML 入口。

规则：
- 文本一律 UTF-8（显式 `encoding="utf-8"`，不依赖 locale）；
- 写入要么成功要么保持原样（`write_text`/`write_json` 都是「先写临时文件再替换」），
  这样半夜断电不会留下半个配置文件；
- 读不到文件时返回默认值，而不是抛 `FileNotFoundError`——调用点自己决定要不要报错。
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from rtros.runtime.errors import UserError


def read_text(path: str | Path, *, default: str | None = None) -> str:
    """读文本（UTF-8）；文件不存在时返回 `default`（默认再抛出 UserError）。"""
    target = Path(path)
    try:
        return target.read_text(encoding="utf-8")
    except FileNotFoundError:
        if default is not None:
            return default
        raise UserError(f"文件不存在：{target}") from None


def write_text(path: str | Path, text: str) -> Path:
    """原子写文本（UTF-8、LF 行尾）。"""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=target.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return target


def read_json(path: str | Path, *, default: Any = None) -> Any:
    """读 JSON；解析失败时返回 `default`（默认抛出 UserError，避免把坏配置当空配置）。"""
    raw = read_text(path, default="")
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UserError(f"JSON 解析失败：{path}（{exc}）") from exc


def write_json(path: str | Path, data: Any) -> Path:
    """原子写 JSON（UTF-8、2 空格缩进、保留中文）。"""
    return write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_toml(path: str | Path) -> dict[str, Any]:
    """读 TOML（Python 3.11+ 标准库 tomllib）；缺失或语法错都给出明确错误。"""
    try:
        import tomllib
    except ImportError:  # pragma: no cover - 3.11+ 才有
        raise UserError("需要 Python 3.11+（TOML 用标准库 tomllib 解析）") from None
    target = Path(path)
    if not target.is_file():
        raise UserError(f"找不到配置文件：{target}")
    with target.open("rb") as fh:
        try:
            return tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            raise UserError(f"TOML 语法错误：{target}（{exc}）") from exc
