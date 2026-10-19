"""离线验 codec：不接串口、不需要 COM 口，只驱动 protocols 里的 codec。

python scripts/src/rtros/serial_hub/tests/codec_check.py
"""

# __pycache__ 统一写到仓库 out/pycache：仓库根由本文件位置直接推出（parents[3]），不做搜索
import sys as _sys
from pathlib import Path as _Path

_sys.pycache_prefix = str(_Path(__file__).resolve().parents[3] / "out" / "pycache")


from rtros.serial_hub.protocols import RawCodec, TelnetCodec  # noqa: E402


def hx(b):
    return b.hex(" ") if b else "(空)"


print("=== 1. telnet 口建立时的主动协商 ===")
c = TelnetCodec()
print("  greeting:", hx(c.greeting()))

print("\n=== 2. 某终端接入时先发的 21 字节 IAC（真实抓包顺序） ===")
seq = bytes(
    [
        0xFF,
        0xFB,
        0x1F,
        0xFF,
        0xFB,
        0x20,
        0xFF,
        0xFB,
        0x18,
        0xFF,
        0xFB,
        0x27,
        0xFF,
        0xFD,
        0x01,
        0xFF,
        0xFB,
        0x03,
        0xFF,
        0xFD,
        0x03,
    ]
)
to_board, reply = c.decode(seq)
print("  client->board :", hx(to_board), "  <-- 必须是空（协商绝不能进设备）")
print("  hub->client   :", hx(reply))
for n in c.notes:
    print("    note:", n)
c.notes.clear()

print("\n=== 3. 设备->客户端：NVT 转义（重点看有没有 CR CR LF） ===")
for name, data in [
    ("设备的 CRLF", b"version\r\n"),
    ("孤 CR", b"x\r"),
    ("孤 LF", b"x\n"),
    ("字面 0xFF", b"\xff"),
    ("CR LF CR LF", b"a\r\nb\r\n"),
]:
    got = c.encode(data)
    bad = b"\r\r" in got
    print(f"  {name:<12s} {hx(data):<22s} -> {hx(got):<26s} {'!! 出现 CR CR' if bad else 'OK'}")

print("\n=== 4. 客户端->设备：回车折叠（不该把一个 Enter 变两个） ===")
for name, data in [
    ("CR LF", b"help\r\n"),
    ("CR NUL", b"help\r\x00"),
    ("孤 CR", b"help\r"),
    ("孤 LF", b"help\n"),
    ("IAC IAC = 字面 0xFF", b"\xff\xff"),
]:
    o, r = c.decode(data)
    print(f"  {name:<20s} -> board={hx(o):<16s} reply={hx(r)}")
for n in c.notes:
    print("    note:", n)
c.notes.clear()

print("\n=== 5. 子协商（SB...SE）必须整段丢弃 ===")
sb = bytes([0xFF, 0xFA, 0x1F, 0x00, 0x50, 0x00, 0x18, 0xFF, 0xF0]) + b"version\r\n"
o, r = c.decode(sb)
print("  -> board:", hx(o), " reply:", hx(r))

print("\n=== 6. 再问一次 DO ECHO（重复协商不该刷屏） ===")
o, r = c.decode(bytes([0xFF, 0xFD, 0x01]))
print("  -> board:", hx(o), " reply:", hx(r), " notes:", c.notes)
c.notes.clear()

print("\n=== 7. raw codec 恒等 ===")
rc = RawCodec()
print(
    "  encode:",
    hx(rc.encode(b"a\r\n")),
    " decode:",
    hx(rc.decode(b"a\r\n")[0]),
    " greeting:",
    hx(rc.greeting()),
)
print("\nOK")
