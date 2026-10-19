"""
Console interaction: MSH prompt check, ramdump trigger, CLI command dispatch.
"""

import time

from serial_utils import serial_read_until, serial_send


def check_console(ser) -> bool:
    """Verify the MSH prompt is alive by sending newlines."""
    print("\n[CONSOLE] Checking MSH prompt...")
    ser.reset_input_buffer()
    time.sleep(0.3)

    for _ in range(3):
        serial_send(ser, "")

    output = serial_read_until(ser, "msh", timeout=8.0)
    if "msh" not in output:
        print("\n[CONSOLE] WARNING: MSH prompt not detected, retrying...")
        ser.reset_input_buffer()
        serial_send(ser, "")
        output = serial_read_until(ser, "msh", timeout=8.0)
        if "msh" not in output:
            print("\n[CONSOLE] ERROR: Cannot detect MSH prompt. Output:")
            print(output[-300:])
            return False

    print("[CONSOLE] OK — MSH prompt detected")
    return True


def enter_ramdump(ser) -> bool:
    """Send cmd_ramdump and wait for the @ramdump> CLI prompt.

    The board enters HardFault → ramdump_enter() → @ramdump> CLI.
    Global interrupts are disabled by the CPU on exception entry.
    """
    print("\n[CONSOLE] Entering ramdump...")
    serial_send(ser, "cmd_ramdump", flush=False)

    output = serial_read_until(ser, "@ramdump>", timeout=30.0)
    if "@ramdump>" not in output:
        print("\n[CONSOLE] ERROR: Did not get @ramdump> prompt")
        print(output[-400:])
        return False

    print("[CONSOLE] @ramdump> prompt detected")
    return True


def enter_ramdump_usb(uart_ser):
    """Trigger ramdump via UART, then find and connect to the USB CDC ACM port.

    USB transport: crash info goes to UART, but the @ramdump> CLI goes to USB.
    This function triggers on UART, waits for crash output, then returns a
    serial connection to the newly-enumerated USB CDC ACM port.

    Returns (usb_ser, usb_port) on success, (None, None) on failure.
    """
    import serial
    import serial.tools.list_ports

    # Record existing ports
    before = {p.device for p in serial.tools.list_ports.comports()}

    print("\n[CONSOLE] Triggering ramdump via UART (USB transport)...")
    serial_send(uart_ser, "cmd_ramdump", flush=False)

    # Wait for crash dump output on UART (confirms HardFault entry)
    print("[CONSOLE] Waiting for crash dump on UART...")
    output = uart_ser.read(4096).decode("ascii", errors="replace")
    print(output[-300:] if len(output) > 300 else output)

    # Done with UART — close it now to avoid port leak
    uart_ser.close()

    # Wait for USB enumeration
    print("[CONSOLE] Waiting for USB enumeration (5s)...")
    time.sleep(5.0)

    # Find new USB CDC ACM port
    after = {p.device: p.description for p in serial.tools.list_ports.comports()}
    new_ports = set(after.keys()) - before

    usb_port = None
    for p in new_ports:
        if "USB" in after.get(p, ""):
            usb_port = p
            break
    if not usb_port:
        # Fallback: try known ports
        for p in ["COM8", "COM4"]:
            if p in after:
                usb_port = p
                break
    if not usb_port:
        print("[CONSOLE] ERROR: USB CDC ACM port not found")
        return None, None

    print(f"[CONSOLE] USB CDC ACM port: {usb_port}")

    # Connect with retry — Windows may need a moment to finish driver init
    usb_ser = None
    for attempt in range(10):
        try:
            usb_ser = serial.Serial(usb_port, 115200, timeout=1, write_timeout=3)
            break
        except serial.SerialException:
            print(f"[CONSOLE] Retry {attempt + 1}/10 opening {usb_port}...")
            time.sleep(1.0)
    if not usb_ser:
        print(f"[CONSOLE] ERROR: Cannot open {usb_port}")
        return None, None

    usb_ser.dtr = True
    time.sleep(0.5)

    # Wait for CLI prompt
    print("[CONSOLE] Waiting for @ramdump> on USB...")
    output = serial_read_until(usb_ser, "@ramdump>", timeout=10.0)
    if "@ramdump>" not in output:
        print("\n[CONSOLE] WARNING: @ramdump> not seen, trying to proceed anyway")
        usb_ser.write(b"\r\n")
        time.sleep(0.3)
        usb_ser.reset_input_buffer()
    else:
        print("[CONSOLE] @ramdump> prompt detected on USB")

    return usb_ser, usb_port


def trigger_dump(ser, region: str = "all") -> bool:
    """Enter ramdump and start a YMODEM transfer.

    Args:
        ser: open serial.Serial instance
        region: "all" | "flash" | "sram" | "ccm"

    Returns True if the dump command was sent and the device is ready
    for YMODEM receive.
    """
    if not enter_ramdump(ser):
        return False

    time.sleep(0.3)

    cmd_map = {
        "flash": "ramdump_flash",
        "sram": "ramdump sram",
        "ccm": "ramdump ccm",
        "all": "ramdump",
    }
    cmd = cmd_map.get(region, "ramdump")

    print(f"\n[CONSOLE] Starting dump: {cmd}")
    serial_send(ser, cmd)

    print("[CONSOLE] Waiting 3s for YMODEM sender...")
    time.sleep(3.0)
    ser.reset_input_buffer()
    print("[CONSOLE] Ready for YMODEM transfer")
    return True
