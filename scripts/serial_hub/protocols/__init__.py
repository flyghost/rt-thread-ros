#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""接入协议注册表：按端口/嗅探挑一个 codec。

加新协议（rfc2217 / websocket）只需两步：写一个 Codec 子类，在 CODECS 里登记。
"""

from __future__ import annotations


from .base import Codec
from .raw import RawCodec
from .telnet import TelnetCodec

CODECS = {"raw": RawCodec, "telnet": TelnetCodec}

__all__ = ["Codec", "RawCodec", "TelnetCodec", "CODECS"]
