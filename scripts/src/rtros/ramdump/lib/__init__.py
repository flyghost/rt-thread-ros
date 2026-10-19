"""ramdump 工具的共享库（build / dump / test 三个桶都从这里取）。

依赖方向只有一条：**桶 → lib**，桶与桶之间不互相 import
（dump 想编译就调 `builder.build_and_flash()`，而不是 import build 桶）。

包化之后库内部一律用绝对导入，不再往 `sys.path` 里塞目录：

    from rtros.ramdump.lib import builder, config, console, serial_utils, ymodem_receiver
"""

__all__ = ["builder", "config", "console", "serial_utils", "ymodem_receiver"]
