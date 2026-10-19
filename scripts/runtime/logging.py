"""输出分层：**结果走 stdout，诊断走 stderr，级别由 `setup()` 统一控制**。

为什么不用裸 `print`：
- 脚本要能进管道（`build.py status | grep`），此时诊断信息不能掺进 stdout；
- `--quiet`（只要结果/退出码）、`--verbose`（要过程）是同一套开关，不需要每个文件各写一遍 if；
- 将来换成 JSON 输出（`--json`）时只改这一处。

用法：
    from runtime import logging as log
    log.setup("verbose")
    log.human("烧录完成：26 页")      # stdout，给人看的结果
    log.diag("scons 用时 12.3s")     # stderr，默认不显示
    log.warn("端口被占用，稍后重试")   # stderr，始终显示
"""

from __future__ import annotations

import logging
import sys

_LOGGER_NAME = "rtros"
_LEVELS = {"quiet": logging.WARNING, "normal": logging.INFO, "verbose": logging.DEBUG}
_configured = False


class _StdoutFilter(logging.Filter):
    """只让 INFO 及以下（结果）进 stdout，警告以上走 stderr。"""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= logging.INFO


def setup(level: str = "normal") -> logging.Logger:
    """初始化全局 logger（幂等，可重复调用以切换级别）。"""
    global _configured
    logger = logging.getLogger(_LOGGER_NAME)
    if not _configured:
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        out = logging.StreamHandler(sys.stdout)
        out.setLevel(logging.DEBUG)
        out.addFilter(_StdoutFilter())
        out.setFormatter(logging.Formatter("%(message)s"))

        err = logging.StreamHandler(sys.stderr)
        err.setLevel(logging.WARNING)
        err.setFormatter(logging.Formatter("%(message)s"))

        logger.addHandler(out)
        logger.addHandler(err)
        _configured = True

    logger.setLevel(_LEVELS.get(level, logging.INFO))
    return logger


def get_logger(name: str = "") -> logging.Logger:
    """取子 logger（名字会出现在 verbose 行里，便于定位来源）。"""
    setup() if not _configured else None
    return logging.getLogger(_LOGGER_NAME if not name else f"{_LOGGER_NAME}.{name}")


def human(message: str) -> None:
    """给人看的结果（stdout）。"""
    get_logger().info(message)


def diag(message: str) -> None:
    """过程/细节（stderr，`--verbose` 才显示）。"""
    get_logger().debug(message)


def warn(message: str) -> None:
    """警告（stderr，始终显示）。"""
    get_logger().warning(message)


def error(message: str) -> None:
    """错误（stderr，始终显示）。"""
    get_logger().error(message)
