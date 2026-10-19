"""`python -m rtros` 的入口：先把字节码落点钉到 out/pycache，再进 CLI。"""

from __future__ import annotations

import sys

from rtros.paths import pycache_prefix

sys.pycache_prefix = str(pycache_prefix())

from rtros import cli  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(cli.main(sys.argv[1:]))
