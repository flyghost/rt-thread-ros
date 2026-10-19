#!/usr/bin/env python3
"""raw：透明字节。通用终端的 Raw 模式、自动化脚本、二进制工具都走它。"""

from __future__ import annotations

from .base import Codec


class RawCodec(Codec):
    """透明字节：通用终端的 Raw 模式、自动化脚本、二进制工具。"""

    name = "raw"
