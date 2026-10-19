"""pytest 全局装置：导入根、仓内临时目录。

为什么不用 `tmp_path`：沙箱里 `tempfile.mkdtemp()` 建出的目录对当前进程不可写
（Windows ACL），落盘类测试必须用仓内目录 `out/tmp/pytest/<用例名>`。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1]
REPO = SCRIPTS.parent

# 导入根：src/ 是 rtros 包的源码位置（等价于 `pip install -e scripts` 后的效果）；
# 其余三套是历史遗留（P2 搬包后会删掉），测试里先统一补齐。
for _root in (
    SCRIPTS / "src",
    SCRIPTS,
    SCRIPTS / "serial_hub",
    SCRIPTS / "ramdump",
    SCRIPTS / "ramdump" / "analyzer",
):
    _path = str(_root)
    if _path not in sys.path:
        sys.path.insert(0, _path)


@pytest.fixture
def work_dir(request: pytest.FixtureRequest) -> Path:
    """每个用例独立的仓内目录，用完删除。"""
    safe = request.node.name.replace("/", "_").replace("::", "_")
    base = REPO / "out" / "tmp" / "pytest" / safe
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    yield base
    shutil.rmtree(base, ignore_errors=True)
