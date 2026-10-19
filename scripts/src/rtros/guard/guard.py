"""沙箱外执行器（守卫）：`python scripts/run_rtros.py guard` 启动常驻进程。

真正的实现按职责拆在同目录：
- `config.py`    读 tasks.toml（允许执行哪些命令）
- `request.py`   校验请求并拼 argv（安全边界）
- `executor.py`  信箱 / 心跳 / 子进程执行 / 超时与停滞
- `cli.py`       会话侧 --status / --list / --request / --tasks

这个文件只做一件事：把 `scripts/` 放进 sys.path，然后调用 cli.main()。
"""

from __future__ import annotations

import sys

from rtros.guard.cli import main

if __name__ == "__main__":
    sys.exit(main())
