"""`scripts/cli.py` 的路由与输出契约。

只验证「路由对不对、输出能不能被机器读」——子命令自身的逻辑由各自的测试覆盖。
"""

from __future__ import annotations

import json

import pytest

import cli
from rtros.runtime import logging as rtlog


@pytest.fixture(autouse=True)
def _fresh_logger():
    """每个用例重建 handler：capsys 会换掉 sys.stdout，旧 handler 绑的是上一个。"""
    rtlog.reset()
    yield
    rtlog.reset()


def _stdout_json(capsys) -> object:
    return json.loads(capsys.readouterr().out)


def test_command_table_covers_every_subsystem():
    names = set(cli.COMMANDS)
    assert {"build", "flash", "status", "doctor", "list", "quality", "guard", "hub", "dump", "recv"} <= names


def test_every_target_is_importable_module_path():
    for name, (_group, _help, target) in cli.COMMANDS.items():
        mod_name, _, attr = target.partition(":")
        assert mod_name and attr, f"{name} 的目标 {target!r} 不是 模块:函数 形式"


def test_list_json_is_machine_readable(capsys):
    assert cli.main(["list", "--json"]) == 0
    rows = _stdout_json(capsys)
    assert isinstance(rows, list) and rows
    for row in rows:
        assert {"name", "group", "help"} <= set(row)


def test_list_human_output_mentions_commands(capsys):
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "build-flash" in out and "doctor" in out


def test_unknown_command_exits_2(capsys):
    assert cli.main(["definitely-not-a-command"]) == 2
    assert "未知命令" in capsys.readouterr().err


def test_no_argument_prints_table(capsys):
    assert cli.main([]) == 0
    assert "命令" in capsys.readouterr().out


def test_status_json_has_expected_keys(capsys):
    code = cli.main(["status", "--json"])
    data = _stdout_json(capsys)
    assert isinstance(data, dict)
    assert {"entry", "build_dir", "artifact_dir", "bin", "pyocd_target"} <= set(data)
    assert code in (0, 1)  # 0=固件在，1=还没编译


def test_doctor_json_reports_environment(capsys):
    assert cli.main(["doctor", "--json"]) == 0
    data = _stdout_json(capsys)
    assert isinstance(data, dict)
    assert data["python"] and data["python_version"]
    assert {"ruff", "mypy", "pytest"} <= set(data["tools"])
