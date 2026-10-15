#include <string.h>
#include <stdio.h>
/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * ramdump_engine.c - Memory dump engine with YMODEM protocol
 *
 * Implements YMODEM batch transfer protocol directly (not using RT-Thread's
 * built-in ymodem component). Uses polled I/O through ramdump_io so it
 * works in both exception context (no OS services) and normal MSH mode.
 *
 * YMODEM batch protocol (single-file transfer):
 *   PC                                    Device
 *   ---                                   ------
 *   'C' (initiate CRC mode)        →
 *                                    ←   SOH 00 FF [filename\0size...] [CRC16]
 *   ACK                            →
 *   'C'                            →
 *                                    ←   STX 01 FE [1024 bytes data] [CRC16]
 *   ACK                            →
 *                                    ←   ... more data blocks ...
 *   ACK                            →
 *                                    ←   EOT
 *   NAK (batch continuation?)      →
 *                                    ←   EOT
 *   ACK                            →
 *   'C' (next file?)               →
 *                                    ←   SOH 00 FF [128 x 0x00] [CRC16] (end of batch)
 *   ACK                            →
 */

#include "ramdump_port.h"
#include <string.h>
#include "ramdump_io.h"

/* YMODEM protocol constants */
#define YM_SOH          0x01
#define YM_STX          0x02
#define YM_EOT          0x04
#define YM_ACK          0x06
#define YM_NAK          0x15
#define YM_CAN          0x18
#define YM_CRC          'C'

#define YM_DATA_SIZE    1024       /* YMODEM uses 1024-byte data blocks */
#define YM_FILEINFO_SIZE 128       /* Block 0 payload (file name + size) */
#define YM_PKT_OVERHEAD 5          /* SOH/STX(1) + seq(1) + ~seq(1) + CRC16(2) */
#define YM_PKT_SIZE     (YM_DATA_SIZE + YM_PKT_OVERHEAD)

/* Timeouts (ms) */
#define YM_INIT_TIMEOUT   60000    /* wait for initial 'C' */
#define YM_BLOCK_TIMEOUT  10000    /* wait for ACK/NAK per block */
#define YM_EOT_TIMEOUT    10000    /* wait for ACK after EOT */
#define YM_BATCH_TIMEOUT  3000     /* wait for 'C' after file done (next file or end) */

/* Max retries per block on NAK (standard YMODEM: up to 10) */
#define YM_MAX_RETRIES    10

/* State per region being transferred */
struct ym_state
{
    uint32_t addr;       /* memory base address */
    uint32_t size;       /* total size */
    uint32_t offset;     /* current offset */
    const char *name;       /* file name */
};

/* CRC16 table (XMODEM polynomial: x^16 + x^12 + x^5 + 1) */
static const uint16_t crc16_table[256] =
{
    0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50A5, 0x60C6, 0x70E7,
    0x8108, 0x9129, 0xA14A, 0xB16B, 0xC18C, 0xD1AD, 0xE1CE, 0xF1EF,
    0x1231, 0x0210, 0x3273, 0x2252, 0x52B5, 0x4294, 0x72F7, 0x62D6,
    0x9339, 0x8318, 0xB37B, 0xA35A, 0xD3BD, 0xC39C, 0xF3FF, 0xE3DE,
    0x2462, 0x3443, 0x0420, 0x1401, 0x64E6, 0x74C7, 0x44A4, 0x5485,
    0xA56A, 0xB54B, 0x8528, 0x9509, 0xE5EE, 0xF5CF, 0xC5AC, 0xD58D,
    0x3653, 0x2672, 0x1611, 0x0630, 0x76D7, 0x66F6, 0x5695, 0x46B4,
    0xB75B, 0xA77A, 0x9719, 0x8738, 0xF7DF, 0xE7FE, 0xD79D, 0xC7BC,
    0x48C4, 0x58E5, 0x6886, 0x78A7, 0x0840, 0x1861, 0x2802, 0x3823,
    0xC9CC, 0xD9ED, 0xE98E, 0xF9AF, 0x8948, 0x9969, 0xA90A, 0xB92B,
    0x5AF5, 0x4AD4, 0x7AB7, 0x6A96, 0x1A71, 0x0A50, 0x3A33, 0x2A12,
    0xDBFD, 0xCBDC, 0xFBBF, 0xEB9E, 0x9B79, 0x8B58, 0xBB3B, 0xAB1A,
    0x6CA6, 0x7C87, 0x4CE4, 0x5CC5, 0x2C22, 0x3C03, 0x0C60, 0x1C41,
    0xEDAE, 0xFD8F, 0xCDEC, 0xDDCD, 0xAD2A, 0xBD0B, 0x8D68, 0x9D49,
    0x7E97, 0x6EB6, 0x5ED5, 0x4EF4, 0x3E13, 0x2E32, 0x1E51, 0x0E70,
    0xFF9F, 0xEFBE, 0xDFDD, 0xCFFC, 0xBF1B, 0xAF3A, 0x9F59, 0x8F78,
    0x9188, 0x81A9, 0xB1CA, 0xA1EB, 0xD10C, 0xC12D, 0xF14E, 0xE16F,
    0x1080, 0x00A1, 0x30C2, 0x20E3, 0x5004, 0x4025, 0x7046, 0x6067,
    0x83B9, 0x9398, 0xA3FB, 0xB3DA, 0xC33D, 0xD31C, 0xE37F, 0xF35E,
    0x02B1, 0x1290, 0x22F3, 0x32D2, 0x4235, 0x5214, 0x6277, 0x7256,
    0xB5EA, 0xA5CB, 0x95A8, 0x8589, 0xF56E, 0xE54F, 0xD52C, 0xC50D,
    0x34E2, 0x24C3, 0x14A0, 0x0481, 0x7466, 0x6447, 0x5424, 0x4405,
    0xA7DB, 0xB7FA, 0x8799, 0x97B8, 0xE75F, 0xF77E, 0xC71D, 0xD73C,
    0x26D3, 0x36F2, 0x0691, 0x16B0, 0x6657, 0x7676, 0x4615, 0x5634,
    0xD94C, 0xC96D, 0xF90E, 0xE92F, 0x99C8, 0x89E9, 0xB98A, 0xA9AB,
    0x5844, 0x4865, 0x7806, 0x6827, 0x18C0, 0x08E1, 0x3882, 0x28A3,
    0xCB7D, 0xDB5C, 0xEB3F, 0xFB1E, 0x8BF9, 0x9BD8, 0xABBB, 0xBB9A,
    0x4A75, 0x5A54, 0x6A37, 0x7A16, 0x0AF1, 0x1AD0, 0x2AB3, 0x3A92,
    0xFD2E, 0xED0F, 0xDD6C, 0xCD4D, 0xBDAA, 0xAD8B, 0x9DE8, 0x8DC9,
    0x7C26, 0x6C07, 0x5C64, 0x4C45, 0x3CA2, 0x2C83, 0x1CE0, 0x0CC1,
    0xEF1F, 0xFF3E, 0xCF5D, 0xDF7C, 0xAF9B, 0xBFBA, 0x8FD9, 0x9FF8,
    0x6E17, 0x7E36, 0x4E55, 0x5E74, 0x2E93, 0x3EB2, 0x0ED1, 0x1EF0
};

static uint16_t ym_crc16(const uint8_t *data, uint32_t len)
{
    uint16_t crc = 0;
    while (len-- > 0)
        crc = (crc << 8) ^ crc16_table[((crc >> 8) ^ *data++) & 0xFF];
    return crc;
}

/*
 * Send a YMODEM data packet.
 *   type: YM_SOH (128-byte) or YM_STX (1024-byte)
 *   seq:  block sequence number (0-255)
 *   data: payload buffer
 *   dlen: payload length (128 for SOH, 1024 for STX)
 */
static void ym_send_pkt(uint8_t type, uint8_t seq,
                        const uint8_t *data, uint32_t dlen)
{
    static uint8_t __attribute__((aligned(4))) pkt[YM_PKT_SIZE];
    uint16_t crc;

    pkt[0] = type;
    pkt[1] = seq;
    pkt[2] = (uint8_t)(~seq);
    memcpy(&pkt[3], data, dlen);
    crc = ym_crc16(&pkt[3], dlen);
    pkt[dlen + 3] = (uint8_t)(crc >> 8);
    pkt[dlen + 4] = (uint8_t)(crc & 0xFF);

    ramdump_put_bytes(pkt, dlen + YM_PKT_OVERHEAD);
}

/*
 * Send Block 0 (file info): SOH 00 FF [filename\0size...] [CRC]
 * File info format: filename + '\0' + decimal_size + '\0'
 * Padded with zeros to 128 bytes.
 */
static void ym_send_block0(const char *name, uint32_t size)
{
    uint8_t buf[YM_FILEINFO_SIZE];
    int len;

    memset(buf, 0, sizeof(buf));
    len = snprintf((char *)buf, sizeof(buf), "%s%c%lu", name, 0, (unsigned long)size);
    /* Ensure at least one zero byte after the size string if snprintf truncated */
    if (len >= (int)sizeof(buf))
        buf[sizeof(buf) - 1] = '\0';

    ym_send_pkt(YM_SOH, 0x00, buf, YM_FILEINFO_SIZE);
}

/*
 * Send empty Block 0 (all zeros, 128 bytes) — signals end of YMODEM batch.
 */
static void ym_send_batch_end(void)
{
    uint8_t buf[YM_FILEINFO_SIZE];
    memset(buf, 0, sizeof(buf));
    ym_send_pkt(YM_SOH, 0x00, buf, YM_FILEINFO_SIZE);
}

/*
 * Send a single memory region using YMODEM protocol.
 */
static int ym_send_region(uint32_t addr, uint32_t size, const char *name, int is_last)
{
    static uint8_t __attribute__((aligned(4))) buf[YM_DATA_SIZE];
    uint32_t offset;
    uint8_t seq;
    uint32_t i;
    int ch;
    int got_c_for_block0 = 0;  /* some receivers use 'C' as implicit ACK */

    /* === Phase 1: Wait for receiver 'C' (CRC mode initiation) === */
    for (i = 0; i < (YM_INIT_TIMEOUT / 100); i++)
    {
        ch = ramdump_getc(100);
        if (ch == YM_CRC || ch == YM_NAK)
            break;
    }
    if (ch != YM_CRC && ch != YM_NAK)
        return -1;

    /* === Phase 2: Send Block 0 (file info) === */
    {
        int retry;
        for (retry = 0; retry < YM_MAX_RETRIES; retry++)
        {
            ym_send_block0(name, size);
            ch = ramdump_getc(YM_BLOCK_TIMEOUT);
            if (ch == YM_ACK)
                break;
            if (ch == YM_CRC)
            {
                /* Some YMODEM implementations send 'C' directly as
                 * implicit ACK for Block 0 + request for data. */
                got_c_for_block0 = 1;
                break;
            }
            if (ch == YM_CAN)
                return -1;
            /* NAK or timeout: retry */
        }
        if (retry >= YM_MAX_RETRIES)
        {

            return -1;
        }
    }

    /* Wait for 'C' (receiver ready for data) — skip if Block 0 already got 'C' */
    if (!got_c_for_block0)
    {
        ch = ramdump_getc(YM_BLOCK_TIMEOUT);
        if (ch != YM_CRC)
            return -1;
    }

    /* === Phase 3: Send data blocks (1024 bytes each, STX) === */
    offset = 0;
    seq = 1;

    while (offset < size)
    {
        uint32_t chunk = size - offset;
        int retry;

        if (chunk > YM_DATA_SIZE)
            chunk = YM_DATA_SIZE;

        /* Copy from memory region */
        memcpy(buf, (const void *)(addr + offset), chunk);

        /* Pad partial block with 0x1A (CPM EOF) */
        if (chunk < YM_DATA_SIZE)
            memset(buf + chunk, 0x1A, YM_DATA_SIZE - chunk);

        /* Send block with retry on NAK/timeout (standard YMODEM error recovery) */
        for (retry = 0; retry < YM_MAX_RETRIES; retry++)
        {
            ym_send_pkt(YM_STX, seq, buf, YM_DATA_SIZE);

            ch = ramdump_getc(YM_BLOCK_TIMEOUT);
            if (ch == YM_ACK)
                break;              /* success */
            if (ch == YM_CAN)
            {

                return -1;
            }
            /* NAK or timeout: will retransmit same block */
            {
            }
        }

        if (retry >= YM_MAX_RETRIES)
        {
            return -1;
        }

        offset += YM_DATA_SIZE;
        seq++;
    }

    /* === Phase 4: End-of-file sequence (YMODEM spec) === */
    /* 4a: Send EOT */
    ramdump_putc(YM_EOT);

    /* 4b: Expect NAK (receiver asks for batch continuation) */
    ch = ramdump_getc(YM_EOT_TIMEOUT);
    if (ch == YM_NAK)
    {
        /* 4c: Send EOT again (to confirm end of this file) */
        ramdump_putc(YM_EOT);

        /* 4d: Expect ACK */
        ch = ramdump_getc(YM_EOT_TIMEOUT);
        if (ch != YM_ACK)
        {
            /* Some receivers send nothing here - not an error */
        }

        if (is_last)
        {
            /* 4e: Expect 'C' (receiver wants next file or batch end) */
            ch = ramdump_getc(YM_BATCH_TIMEOUT);
            if (ch == YM_CRC)
            {
                /* 4f: Send empty Block 0 to signal end of batch */
                ym_send_batch_end();

                /* 4g: Expect final ACK (tolerant) */
                ch = ramdump_getc(YM_EOT_TIMEOUT);
                (void)ch;
            }
            /* else: receiver may have closed after single file */
        }
        /* else: NOT the last file — the receiver will send 'C' to
         * request the next file.  That 'C' is consumed by the next
         * ym_send_region's Phase 1 wait loop. */
    }
    /* else: some receivers send ACK instead of NAK after first EOT -
       treat it as single-file completion */

    return 0;
}

/* ================================================================
 *  Protocol ops — YMODEM
 * ================================================================ */

#include "ramdump_protocol.h"

static int ymodem_session_start(void)
{
    return RAMDUMP_EOK;  /* YMODEM has no session handshake */
}

static int ymodem_send_file(uint32_t addr, uint32_t size, const char *name)
{
    return ym_send_region(addr, size, name, 0);  /* is_last=0; session_end handles batch-end */
}

static int ymodem_session_end(void)
{
    ym_send_batch_end();
    return RAMDUMP_EOK;
}

const ramdump_protocol_ops_t ramdump_protocol_ymodem = {
    .session_start = ymodem_session_start,
    .send_file     = ymodem_send_file,
    .session_end   = ymodem_session_end,
};
