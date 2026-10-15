"""
Receive YMODEM dump from a ramdump CLI (already in @ramdump> mode).

Usage:
  python receive_dump.py COM8
  python receive_dump.py COM8 flash     # FLASH only
  python receive_dump.py COM8 sram      # SRAM only
  python receive_dump.py COM8 ccm       # CCM only
"""

import sys, time
from pathlib import Path
from config import OUT_DUMP_DIR
from ymodem_receiver import ymodem_receive
import serial

def main():
    port = sys.argv[1] if len(sys.argv) > 1 else 'COM8'
    region = sys.argv[2] if len(sys.argv) > 2 else 'all'

    cmd_map = {'flash': 'ramdump_flash', 'sram': 'ramdump sram', 'ccm': 'ramdump ccm', 'all': 'ramdump'}
    cmd = cmd_map.get(region, 'ramdump')

    print(f'Connecting to {port}...')
    ser = serial.Serial(port, 115200, timeout=1, write_timeout=10)
    ser.dtr = True
    time.sleep(0.5)

    # Trigger prompt
    ser.write(b'\r\n')
    time.sleep(0.5)
    r = ser.read(ser.in_waiting or 4096)
    print(f'Prompt: {r[:100]!r}')

    # Send dump command
    print(f'Sending: {cmd}')
    ser.write((cmd + '\r\n').encode())
    ser.flush()

    # Wait for MCU to process command and enter YMODEM sender mode.
    # The sender prints "Waiting for YMODEM..." then waits for 'C'.
    print('Waiting for YMODEM sender...')
    time.sleep(2.0)

    # Read and show any output from the device
    pre = ser.read(ser.in_waiting or 4096)
    if pre:
        print(f'Device output ({len(pre)}B): {pre[:300]!r}')

    # Receive YMODEM
    out = str(OUT_DUMP_DIR / time.strftime('%Y%m%d_%H%M%S'))
    print(f'Receiving to {out} ...')
    saved = ymodem_receive(ser, out)
    ser.close()

    if saved:
        print(f'Done. {len(saved)} file(s) saved to {out}')
        for f in saved:
            print(f'  {Path(f).name}  ({Path(f).stat().st_size:,} bytes)')
    else:
        print('No files received.')

if __name__ == '__main__':
    main()
