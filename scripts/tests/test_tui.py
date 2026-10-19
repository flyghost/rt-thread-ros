"""TUI 拆分后的对象级测试：喂事件 → 行缓冲 / 搜索 / 渲染都要正常。"""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from rtros.serial_hub.core.events import Event
from rtros.serial_hub.tui.app import TuiApp


@pytest.fixture
def app() -> TuiApp:
    instance = TuiApp(hub=None, mode="text")
    payload = b"".join(b"line %02d: hello-otg-hs\r\n" % i for i in range(40))
    instance.on_event(Event(kind="rx", data=payload))
    instance.on_event(Event(kind="tx", data=b"usb_st\r\n"))
    instance.on_event(Event(kind="hub", msg="opened COM46"))
    instance.on_state(
        {
            "rx_bytes": 1234,
            "clients": 1,
            "owner": 1,
            "com": "COM46",
            "ser_ok": True,
            "sessions": [
                {
                    "cid": 1,
                    "proto": "text",
                    "addr": "127.0.0.1:50000",
                    "rx": 1234,
                    "tx": 56,
                    "uptime": 12,
                    "locked": True,
                }
            ],
            "sinks": ["log", "tui"],
        }
    )
    return instance


def test_sink_name(app: TuiApp) -> None:
    assert app.name == "tui"


def test_rx_events_become_lines(app: TuiApp) -> None:
    lines = app.text_lines()
    assert len(lines) >= 40
    assert lines[0] == ("rx", "line 00: hello-otg-hs")
    assert any(kind == "hub" for kind, _ in lines)


def test_search_finds_all_hits(app: TuiApp) -> None:
    app.search = "hello"
    app.start_search()
    app.run_search()
    assert len(app.hits) == 40
    assert "40/40" in app.search_status()
    app.jump_hit(1)
    app.exit_search()


def test_render_produces_ansi_screen(app: TuiApp) -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        app.draw()
    out = buf.getvalue()
    assert len(out) > 0
    assert "\x1b[" in out


def test_sidebar_lists_sessions(app: TuiApp) -> None:
    sidebar = app.sidebar_lines()
    assert sidebar[0].startswith("会话 1")
    assert any("锁定" in line or "<=锁" in line for line in sidebar)


def test_hex_mode_accepts_bytes(app: TuiApp) -> None:
    app.mode = "hex"
    app.on_event(Event(kind="rx", data=bytes(range(64))))
    buf = io.StringIO()
    with redirect_stdout(buf):
        app.draw()
    assert len(buf.getvalue()) > 0
