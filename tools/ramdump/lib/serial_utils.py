"""
Serial port utilities: CH340 detection, open, read_until, send.
"""

import sys
import time
import serial
import serial.tools.list_ports

CH340_VID = 0x1A86
CH340_PID = 0x7523
BAUDRATE  = 115200


def find_ch340_port():
    """Auto-detect CH340 USB-UART device. Returns device name or None."""
    for port in serial.tools.list_ports.comports():
        if port.vid == CH340_VID and port.pid == CH340_PID:
            return port.device
    return None


def open_serial(port: str, baud: int = BAUDRATE) -> serial.Serial:
    """Open serial port with standard 8N1 settings."""
    ser = serial.Serial(
        port=port,
        baudrate=baud,
        bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE,
        stopbits=serial.STOPBITS_ONE,
        timeout=0.3,
        write_timeout=1.0,
    )
    return ser


def serial_read_until(ser, marker,
                      timeout: float = 15.0, echo: bool = True) -> str:
    """Read from serial until 'marker' appears or timeout expires.

    Args:
        ser: open serial.Serial instance
        marker: str or bytes to look for
        timeout: max seconds to wait
        echo: if True, print received bytes to stdout in real time

    Returns:
        All received data as a string.
    """
    if isinstance(marker, str):
        marker = marker.encode('ascii')

    buf = bytearray()
    t0 = time.time()
    while (time.time() - t0) < timeout:
        ch = ser.read(1)
        if ch:
            buf.extend(ch)
            if echo:
                sys.stdout.write(ch.decode('ascii', errors='replace'))
                sys.stdout.flush()
            if marker in buf:
                break
        else:
            time.sleep(0.02)
    return buf.decode('ascii', errors='replace')


def serial_send(ser: serial.Serial, text: str, flush: bool = True):
    """Send a line to serial (appends CRLF).  Set flush=False for commands
    that crash the target (e.g. cmd_ramdump) to avoid blocking on TX drain."""
    ser.write((text + "\r\n").encode('ascii'))
    if flush:
        ser.flush()
    time.sleep(0.1)
