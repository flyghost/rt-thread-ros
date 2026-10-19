"""`rtros.paths` 的两类根：工具仓库根由位置推出，工程根由环境变量/标记决定。"""

from __future__ import annotations

from pathlib import Path

import pytest

from rtros import cli
from rtros.paths import ENV_REPO, MARKER, ProjectRootError, out_dir, project_root, pycache_prefix, tool_root


def test_tool_root_is_scripts_dir() -> None:
    """工具仓库根 = scripts/（包在 scripts/src/rtros 下，上溯两级）。"""
    assert tool_root().name == "scripts"
    assert (tool_root() / "pyproject.toml").is_file()


def test_project_root_walks_up_to_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """不给环境变量时，从 cwd 向上找 .git（本仓根）。"""
    monkeypatch.delenv(ENV_REPO, raising=False)
    assert (project_root() / ".git").exists()


def test_project_root_env_override(monkeypatch: pytest.MonkeyPatch, work_dir: Path) -> None:
    """RTROS_REPO 优先级最高。"""
    monkeypatch.setenv(ENV_REPO, str(work_dir))
    assert project_root() == work_dir.resolve()


def test_project_root_env_points_to_missing_dir(monkeypatch: pytest.MonkeyPatch, work_dir: Path) -> None:
    """环境变量指向不存在的目录时明确报错，不退化成“向上找”。"""
    monkeypatch.setenv(ENV_REPO, str(work_dir / "nope"))
    with pytest.raises(ProjectRootError):
        project_root()


def test_project_root_marker_file(monkeypatch: pytest.MonkeyPatch, work_dir: Path) -> None:
    """没有 .git 时，`.rtros-root` 标记文件也能确定工程根。"""
    monkeypatch.delenv(ENV_REPO, raising=False)
    (work_dir / MARKER).write_text("", encoding="utf-8")
    nested = work_dir / "a" / "b"
    nested.mkdir(parents=True)
    assert project_root(start=nested) == work_dir.resolve()


def test_project_root_walks_up_from_nested_dir(monkeypatch: pytest.MonkeyPatch, work_dir: Path) -> None:
    """从深层子目录起步时，向上找到仓库根（`out/tmp/pytest/...` 仍在本仓内）。"""
    monkeypatch.delenv(ENV_REPO, raising=False)
    nested = work_dir / "a" / "b"
    nested.mkdir(parents=True)
    assert project_root(start=nested) == tool_root().parent.resolve()


def test_out_dir_and_pycache_follow_project_root(monkeypatch: pytest.MonkeyPatch, work_dir: Path) -> None:
    """产物与字节码目录都在 <工程根>/out 下。"""
    monkeypatch.setenv(ENV_REPO, str(work_dir))
    assert out_dir("build") == work_dir / "out" / "build"
    assert pycache_prefix().name == "pycache"
    assert pycache_prefix().parent.name == "out"


@pytest.mark.parametrize("argv", [["--version"], ["version"], ["paths"]])
def test_cli_returns_zero_or_one(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    """`rtros` 的三条自带命令都能跑（paths 找不到工程根时退 1 属正常）。"""
    assert cli.main(argv) in (0, 1)
    assert capsys.readouterr().out
