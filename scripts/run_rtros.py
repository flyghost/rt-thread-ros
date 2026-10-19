#!/usr/bin/env python3
"""`rtros` 的免安装入口：把 `scripts/src` 加进 `sys.path` 后转给 `rtros.cli`。

文件名不叫 `rtros.py`：那会和包名 `rtros` 同名，`import rtros` 会先命中本文件，
把包遮住（实测报错「'rtros' is not a package」）。

为什么还要这个文件：`python -m rtros` 要求包已安装（editable 或 PYTHONPATH），
而多数机器上「先装一遍」是多余的摩擦。这个入口零安装即可运行，便于：

    python scripts/run_rtros.py paths
    python scripts/run_rtros.py --version

装了 editable（`python tools/pyenv/install.py`）之后，直接 `rtros paths` 即可，
本文件仍可继续用于「换了台机器、还没装」的场景。
"""

# __pycache__ 统一写到仓库 out/pycache：仓库根由本文件位置直接推出（parents[1]），不做搜索
import sys as _sys
from pathlib import Path as _Path

_sys.pycache_prefix = str(_Path(__file__).resolve().parents[1] / "out" / "pycache")

import sys  # noqa: E402
from pathlib import Path  # noqa: E402

_SRC = Path(__file__).resolve().parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rtros.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
