"""
YMODEM batch receiver for automated ramdump extraction.

Protocol (per firmware ramdump_engine.c):

    PC (Receiver)                          Device (Sender)
    ---                                    ---
    'C'  (initiate CRC mode)         →
                                     ←   SOH 00 FF [filename\\0size...] [CRC16]
    ACK                              →
    'C'                              →
                                     ←   STX 01 FE [1024 bytes data] [CRC16]
    ACK                              →
                                     ←   ... more data blocks ...
                                     ←   EOT
    NAK  (batch continuation)        →
                                     ←   EOT
    ACK                              →
    'C'  (next file / batch end)     →
                                     ←   SOH 00 FF [128 x 0x00] [CRC16]  (batch end)
    ACK                              →

Key fix: 'C' for the next-file / batch-end request is sent immediately after
the EOT handshake, BEFORE saving the file to disk.  The firmware only waits
3 seconds for this 'C' — if we delay (e.g. slow disk write), the firmware
times out and the batch-end empty Block 0 is never sent.
"""

import time
from pathlib import Path

SOH  = 0x01
STX  = 0x02
EOT  = 0x04
ACK  = 0x06
NAK  = 0x15
CRC  = ord('C')

BLOCK0_SIZE  = 128
DATA_SIZE    = 1024
PKT_OVERHEAD = 5          # type(1) + seq(1) + ~seq(1) + crc(2)

_CRC_TAB = [
    0x0000,0x1021,0x2042,0x3063,0x4084,0x50A5,0x60C6,0x70E7,
    0x8108,0x9129,0xA14A,0xB16B,0xC18C,0xD1AD,0xE1CE,0xF1EF,
    0x1231,0x0210,0x3273,0x2252,0x52B5,0x4294,0x72F7,0x62D6,
    0x9339,0x8318,0xB37B,0xA35A,0xD3BD,0xC39C,0xF3FF,0xE3DE,
    0x2462,0x3443,0x0420,0x1401,0x64E6,0x74C7,0x44A4,0x5485,
    0xA56A,0xB54B,0x8528,0x9509,0xE5EE,0xF5CF,0xC5AC,0xD58D,
    0x3653,0x2672,0x1611,0x0630,0x76D7,0x66F6,0x5695,0x46B4,
    0xB75B,0xA77A,0x9719,0x8738,0xF7DF,0xE7FE,0xD79D,0xC7BC,
    0x48C4,0x58E5,0x6886,0x78A7,0x0840,0x1861,0x2802,0x3823,
    0xC9CC,0xD9ED,0xE98E,0xF9AF,0x8948,0x9969,0xA90A,0xB92B,
    0x5AF5,0x4AD4,0x7AB7,0x6A96,0x1A71,0x0A50,0x3A33,0x2A12,
    0xDBFD,0xCBDC,0xFBBF,0xEB9E,0x9B79,0x8B58,0xBB3B,0xAB1A,
    0x6CA6,0x7C87,0x4CE4,0x5CC5,0x2C22,0x3C03,0x0C60,0x1C41,
    0xEDAE,0xFD8F,0xCDEC,0xDDCD,0xAD2A,0xBD0B,0x8D68,0x9D49,
    0x7E97,0x6EB6,0x5ED5,0x4EF4,0x3E13,0x2E32,0x1E51,0x0E70,
    0xFF9F,0xEFBE,0xDFDD,0xCFFC,0xBF1B,0xAF3A,0x9F59,0x8F78,
    0x9188,0x81A9,0xB1CA,0xA1EB,0xD10C,0xC12D,0xF14E,0xE16F,
    0x1080,0x00A1,0x30C2,0x20E3,0x5004,0x4025,0x7046,0x6067,
    0x83B9,0x9398,0xA3FB,0xB3DA,0xC33D,0xD31C,0xE37F,0xF35E,
    0x02B1,0x1290,0x22F3,0x32D2,0x4235,0x5214,0x6277,0x7256,
    0xB5EA,0xA5CB,0x95A8,0x8589,0xF56E,0xE54F,0xD52C,0xC50D,
    0x34E2,0x24C3,0x14A0,0x0481,0x7466,0x6447,0x5424,0x4405,
    0xA7DB,0xB7FA,0x8799,0x97B8,0xE75F,0xF77E,0xC71D,0xD73C,
    0x26D3,0x36F2,0x0691,0x16B0,0x6657,0x7676,0x4615,0x5634,
    0xD94C,0xC96D,0xF90E,0xE92F,0x99C8,0x89E9,0xB98A,0xA9AB,
    0x5844,0x4865,0x7806,0x6827,0x18C0,0x08E1,0x3882,0x28A3,
    0xCB7D,0xDB5C,0xEB3F,0xFB1E,0x8BF9,0x9BD8,0xABBB,0xBB9A,
    0x4A75,0x5A54,0x6A37,0x7A16,0x0AF1,0x1AD0,0x2AB3,0x3A92,
    0xFD2E,0xED0F,0xDD6C,0xCD4D,0xBDAA,0xAD8B,0x9DE8,0x8DC9,
    0x7C26,0x6C07,0x5C64,0x4C45,0x3CA2,0x2C83,0x1CE0,0x0CC1,
    0xEF1F,0xFF3E,0xCF5D,0xDF7C,0xAF9B,0xBFBA,0x8FD9,0x9FF8,
    0x6E17,0x7E36,0x4E55,0x5E74,0x2E93,0x3EB2,0x0ED1,0x1EF0,
]


def crc16(data: bytes) -> int:
    """XMODEM CRC-16 (poly 0x1021)."""
    crc = 0
    for b in data:
        crc = ((crc << 8) ^ _CRC_TAB[((crc >> 8) ^ b) & 0xFF]) & 0xFFFF
    return crc


def _read_all(ser, n: int, timeout: float = 5.0) -> bytes:
    """Read exactly n bytes, looping until all received or timeout."""
    ser.timeout = timeout
    buf = b''
    while len(buf) < n:
        chunk = ser.read(n - len(buf))
        if chunk:
            buf += chunk
        else:
            break
    return buf


def _wait_header(ser, timeout: float = 60.0) -> int | None:
    """Wait for SOH or EOT header byte. Returns the byte or None on timeout."""
    t0 = time.time()
    while (time.time() - t0) < timeout:
        b = ser.read(1)
        if b and b[0] in (SOH, EOT):
            return b[0]
    return None


def _block0_crc_ok(rest: bytes) -> bool:
    """Validate CRC16 of a Block-0 response (132 bytes: seq + ~seq + 128 data + 2 CRC)."""
    if len(rest) < 132:
        return False
    crc_rcvd = (rest[130] << 8) | rest[131]
    crc_calc = crc16(rest[2:130])
    return crc_calc == crc_rcvd


def _data_crc_ok(blk: bytes) -> bool:
    """Validate CRC16 of an STX data block (1028 bytes: seq + ~seq + 1024 data + 2 CRC)."""
    if len(blk) < 1028:
        return False
    crc_rcvd = (blk[1026] << 8) | blk[1027]
    crc_calc = crc16(blk[2:1026])
    return crc_calc == crc_rcvd


def ymodem_receive(ser, output_dir: str, verbose: bool = True):
    """Receive files via YMODEM. Returns list of saved file paths."""
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    saved = []

    # ---- Init: send 'C' to start YMODEM (retry a few times) ----
    if verbose:
        print("  Sending 'C' to initiate YMODEM...")
    ser.reset_input_buffer()        # 丢掉进 dump 前残留的输出，避免把老字节当包头
    for _ in range(5):
        ser.write(b'C')
        ser.flush()
        time.sleep(0.3)

    if verbose:
        print("  Waiting for device to respond (up to 60s)...")

    while True:
        # ---- Wait for Block 0 (SOH) or EOT ----
        hdr = _wait_header(ser, timeout=60.0)
        if hdr is None:
            if verbose:
                print("  Timeout waiting for YMODEM transfer.")
            break
        if hdr == EOT:
            if verbose:
                print("  Received EOT — transfer complete.")
            break

        # ---- Read Block 0 (SOH packet: 132 more bytes) ----
        rest = _read_all(ser, 132)
        if len(rest) < 132:
            if verbose:
                print("  Incomplete Block 0")
            break

        # Validate Block 0 CRC
        if not _block0_crc_ok(rest):
            if verbose:
                print("  Block 0 CRC mismatch — NAK")
            ser.write(bytes([NAK]))
            ser.flush()
            continue

        # ---- Parse filename & size from Block 0 ----
        payload = rest[2:130]          # skip seq + ~seq
        raw = payload.rstrip(b'\x00')
        parts = raw.split(b'\x00')
        if len(parts) < 2:
            # Empty Block 0 → batch end
            if verbose:
                print("  Batch end (empty Block 0)")
            ser.write(bytes([ACK]))
            ser.flush()
            break

        fname = parts[0].decode('ascii', errors='replace')
        fsize = int(parts[1].decode('ascii'))
        if verbose:
            print(f"  Receiving: {fname} ({fsize:,} bytes)")

        # ---- ACK + 'C': ACK for Block 0, 'C' to request data ----
        ser.write(bytes([ACK, CRC]))
        ser.flush()

        # ---- Receive STX data blocks ----
        file_data = bytearray()
        t0 = time.time()
        expected_seq = 1                # data blocks start at seq=1

        while len(file_data) < fsize and (time.time() - t0) < 120:
            hdr_b = ser.read(1)
            if not hdr_b:
                continue
            hdr = hdr_b[0]

            if hdr == STX:
                blk = _read_all(ser, 1028)
                if len(blk) < 1028:
                    if verbose:
                        print("    Incomplete STX block")
                    break

                # Validate CRC
                if not _data_crc_ok(blk):
                    if verbose:
                        print(f"    CRC mismatch at block seq={blk[1]} — NAK")
                    ser.write(bytes([NAK]))
                    ser.flush()
                    continue

                seq = blk[0]
                chunk = blk[2:1026]      # skip seq + ~seq
                remaining = fsize - len(file_data)

                if seq == expected_seq:
                    # Normal case: next block in sequence
                    file_data.extend(chunk[:remaining])
                    expected_seq = (expected_seq + 1) & 0xFF
                    ser.write(bytes([ACK]))
                    ser.flush()

                    if verbose and len(file_data) % (32 * 1024) < DATA_SIZE:
                        pct = len(file_data) * 100 // fsize
                        print(f"    {pct}%  {len(file_data):,} bytes")

                elif seq == ((expected_seq - 1) & 0xFF):
                    # Retransmission — our previous ACK was lost.  Re-send ACK
                    # but do NOT append the data again.
                    ser.write(bytes([ACK]))
                    ser.flush()

                else:
                    # Unexpected sequence number
                    if verbose:
                        print(f"    Unexpected seq {seq} (expected {expected_seq}) — NAK")
                    ser.write(bytes([NAK]))
                    ser.flush()

            elif hdr == SOH:
                # Stale Block 0 retry — discard and re-ACK+C
                _read_all(ser, 132)
                ser.write(bytes([ACK, CRC]))
                ser.flush()

            elif hdr == EOT:
                break

            # else: garbage byte, ignore

        # ---- EOT handshake ----
        #   Device → EOT (first)  →  Receiver → NAK
        #   Device → EOT (second) →  Receiver → ACK
        #
        # The data loop may have exited either because we saw EOT (hdr==EOT),
        # or because all bytes were received.  In the latter case the first
        # EOT is still pending in the serial buffer.  Consume or wait for it.

        b = ser.read(1)
        if not (b and b[0] == EOT):
            t0 = time.time()
            while (time.time() - t0) < 3:
                b = ser.read(1)
                if b and b[0] == EOT:
                    break

        # Request batch continuation (NAK tells sender: more files please)
        ser.write(bytes([NAK]))
        ser.flush()
        time.sleep(0.05)

        # Wait for the second EOT
        b = _read_all(ser, 1, timeout=1.0)
        if b and b[0] == EOT:
            ser.write(bytes([ACK]))
            ser.flush()

        # ---- Save file ----
        fpath = output / fname
        fpath.write_bytes(bytes(file_data[:fsize]))
        if verbose:
            print(f"  Saved: {fpath} ({len(file_data):,} bytes)")
        saved.append(str(fpath))

        # ---- Send 'C' IMMEDIATELY for next file / batch end ----
        # CRITICAL: the firmware only waits 3 seconds for this 'C'.
        # Do NOT put anything slow (like disk I/O) between the ACK
        # above and this 'C'.
        ser.write(b'C')
        ser.flush()
        # The next loop iteration reads the response:
        #   - SOH with empty Block 0 → batch end
        #   - SOH with next file's name → next file
        #   - timeout (firmware already done) → exit

    if verbose:
        print(f"  Done. {len(saved)} file(s) received.")
    return saved
