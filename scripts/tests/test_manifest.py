"""工程清单 `rtros.toml` 的读取与校验契约。"""

from __future__ import annotations

from pathlib import Path

import pytest

from rtros import manifest

REPO_TOML = Path(__file__).resolve().parents[2] / "rtros.toml"


def _write(root: Path, body: str) -> Path:
    path = root / manifest.MANIFEST_NAME
    path.write_text(body, encoding="utf-8")
    return path


def test_repo_manifest_resolves_required_facts() -> None:
    """本仓清单能被读出来，且关键路径都真实存在。"""
    m = manifest.load(REPO_TOML.parent)
    assert m.root == REPO_TOML.parent
    assert m.workspace.bsp_dir.is_dir()
    assert (m.workspace.bsp_dir / "SConstruct").is_file()
    assert m.build.toolchain_root.is_dir()
    assert m.flash.pack.is_file()
    assert m.flash.target == "STM32F407VE"
    assert m.serial.port and m.serial.baud > 0


def test_entry_dir_prefers_project_and_falls_back_to_board() -> None:
    m = manifest.load(REPO_TOML.parent)
    entry, kind = m.entry_dir()
    assert kind == "project" and (entry / "SConstruct").is_file()
    board, board_kind = m.entry_dir("none")
    assert board_kind == "board" and board == m.workspace.bsp_dir


def test_missing_manifest_raises(work_dir: Path) -> None:
    with pytest.raises(manifest.ManifestError, match="找不到"):
        manifest.load(work_dir)


def test_missing_required_key_raises(work_dir: Path) -> None:
    _write(
        work_dir,
        '[workspace]\nprojects_dir = "projects"\n[build]\ntoolchain_root = "."\n[flash]\ntarget = "x"\n',
    )
    with pytest.raises(manifest.ManifestError, match=r"\[workspace\]\.bsp_dir"):
        manifest.load(work_dir)


def test_missing_path_raises(work_dir: Path) -> None:
    _write(
        work_dir,
        "[workspace]\n"
        'bsp_dir = "no-such-board"\n'
        'projects_dir = "projects"\n'
        "[build]\n"
        'toolchain_root = "."\n'
        "[flash]\n"
        'target = "x"\n'
        'pack = "."\n'
        'python = "."\n',
    )
    with pytest.raises(manifest.ManifestError, match=r"不存在的路径"):
        manifest.load(work_dir)


def test_broken_toml_raises(work_dir: Path) -> None:
    _write(work_dir, "[workspace\nbsp_dir = ")
    with pytest.raises(manifest.ManifestError, match="不是合法 TOML"):
        manifest.load(work_dir)


def test_env_overrides_win(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYOCD_TARGET", "STM32F407VG")
    monkeypatch.setenv("RTROS_SERIAL_PORT", "COM99")
    m = manifest.load(REPO_TOML.parent)
    assert m.flash.target == "STM32F407VG"
    assert m.serial.port == "COM99"


def test_unknown_project_raises(work_dir: Path) -> None:
    m = manifest.load(REPO_TOML.parent)
    with pytest.raises(manifest.ManifestError, match="没有 SConstruct"):
        m.entry_dir("definitely-not-a-project")
