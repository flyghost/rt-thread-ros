"""固件构建/烧录：唯一实现（SCons 编译 + pyocd 烧录）。

对外只用两个东西：
    firmware/build.py   —— 命令行入口
    firmware/tools.py   —— 可被其他脚本 import 的函数
    firmware/config.py  —— 路径与工具链常量（全仓唯一来源）
"""
