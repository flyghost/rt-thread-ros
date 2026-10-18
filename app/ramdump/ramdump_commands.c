/*
 * ramdump_commands.c — CLI command implementations
 */

#include <string.h>
#include <stdio.h>
#include "ramdump_cli.h"
#include "ramdump_port.h"
#include "ramdump_io.h"
#include "ramdump_protocol.h"
#include "ramdump_config.h"
#include "ramdump_exception.h"
#include "ramdump_utils.h"
#ifdef RAMDUMP_ENABLE_STORAGE
#include "ramdump_storage.h"   /* must precede its use in cli_cmd_ramdump_storage */
#endif

static int ramdump_send_crash(void);
extern const cli_cmd_t cli_commands[];

/**
 * md <addr> [len] -- Memory display (hex dump)
 */
int cli_cmd_md(int argc, char **argv)
{
    uint32_t addr;
    uint32_t len = 256;  /* default: 256 bytes */
    uint32_t i, j;
    char line[80];

    if (argc < 2)
    {
        ramdump_put_bytes((const uint8_t *)
            "Usage: md <addr> [len]\r\n", 26);
        return -1;
    }

    /* Parse address (hex) */
    addr = (uint32_t)ramdump_strtoul(argv[1], 16);

    /* Parse optional length */
    if (argc >= 3)
    {
        len = (uint32_t)ramdump_strtoul(argv[2], 0);
    }

    /* Align address to 16-byte boundary */
    addr &= ~0x0F;

    for (i = 0; i < len; i += 16)
    {
        uint8_t *p = (uint8_t *)(addr + i);
        int pos = 0;

        /* Address */
        pos += snprintf(line + pos, sizeof(line) - pos,
                           "%08lx: ", (unsigned long)(addr + i));

        /* Hex bytes */
        for (j = 0; j < 16; j++)
        {
            if (i + j < len)
                pos += snprintf(line + pos, sizeof(line) - pos,
                                   "%02x ", p[j]);
            else
                pos += snprintf(line + pos, sizeof(line) - pos, "   ");
        }

        /* ASCII representation */
        pos += snprintf(line + pos, sizeof(line) - pos, " ");
        for (j = 0; j < 16 && (i + j) < len; j++)
        {
            char c = (char)p[j];
            if (c < 0x20 || c > 0x7E) c = '.';
            pos += snprintf(line + pos, sizeof(line) - pos, "%c", c);
        }

        pos += snprintf(line + pos, sizeof(line) - pos, "\r\n");
        ramdump_put_bytes((const uint8_t *)line, pos);
    }

    return 0;
}

/**
 * mw <addr> <val> -- Memory write (32-bit)
 */
int cli_cmd_mw(int argc, char **argv)
{
    uint32_t addr;
    uint32_t val;

    if (argc < 3)
    {
        ramdump_put_bytes((const uint8_t *)
            "Usage: mw <addr> <val>\r\n", 26);
        return -1;
    }

    addr = (uint32_t)ramdump_strtoul(argv[1], 16);
    val  = (uint32_t)ramdump_strtoul(argv[2], 16);

    *(volatile uint32_t *)addr = val;

    return 0;
}

/**
 * ramdump -- YMODEM send memory regions
 *
 * Usage:
 *   ramdump              -- sends all regions (SRAM+CCM+FLASH+exception)
 *   ramdump flash        -- sends FLASH only
 *   ramdump sram         -- sends SRAM only
 *   ramdump ccm          -- sends CCM only
 *   ramdump <addr> <len> -- sends custom region
 */
int cli_cmd_ramdump(int argc, char **argv)
{
    if (argc >= 3)
    {
        uint32_t addr = (uint32_t)ramdump_strtoul(argv[1], 16);
        uint32_t len  = (uint32_t)ramdump_strtoul(argv[2], 16);
        ramdump_session_start();
        int ret = ramdump_send_file(addr, len, "manual.bin");
        ramdump_session_end();
        return ret;
    }
    else if (argc == 2)
    {
        uint32_t addr = 0, size = 0;
        const char *name = "dump.bin";
        if (strcmp(argv[1], "flash") == 0) {
            addr = RAMDUMP_REGION_FLASH_ADDR; size = RAMDUMP_REGION_FLASH_SIZE; name = "FLASH.bin";
        } else if (strcmp(argv[1], "sram") == 0) {
            addr = RAMDUMP_REGION_SRAM_ADDR;  size = RAMDUMP_REGION_SRAM_SIZE;  name = "SRAM.bin";
        } else if (strcmp(argv[1], "ccm") == 0) {
            addr = RAMDUMP_REGION_CCM_ADDR;   size = RAMDUMP_REGION_CCM_SIZE;   name = "CCM.bin";
        }
        ramdump_session_start();
        int ret = ramdump_send_file(addr, size, name);
        ramdump_session_end();
        return ret;
    }

    /* default: all regions */
    return ramdump_send_crash();
}

static int ramdump_send_crash(void)
{
    static const ramdump_region_t g_default_regions[] = RAMDUMP_DEFAULT_REGIONS;
    #define DEFAULT_COUNT  (sizeof(g_default_regions) / sizeof(g_default_regions[0]))
    ramdump_region_t regions[DEFAULT_COUNT];

    memcpy(regions, g_default_regions, sizeof(g_default_regions));

    ramdump_session_start();

    int ok = 0;
    for (int i = 0; i < DEFAULT_COUNT; i++) {
        if (ramdump_send_file(regions[i].addr, regions[i].size,
                              regions[i].name) == RAMDUMP_EOK) {
            ok++;
        } else {
            break;
        }
    }

    ramdump_session_end();
    return (ok == DEFAULT_COUNT) ? RAMDUMP_EOK : RAMDUMP_ERR;
}

/**
 * ramdump_flash -- YMODEM send FLASH only (shortcut, same as 'ramdump flash')
 */
int cli_cmd_ramdump_flash(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    ramdump_session_start();
    int ret = ramdump_send_file(RAMDUMP_REGION_FLASH_ADDR,
                                RAMDUMP_REGION_FLASH_SIZE, "FLASH.bin");
    ramdump_session_end();
    return ret;
}

/**
 * errorlog -- Show exception info
 */
int cli_cmd_errorlog(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    ramdump_exception_print();
    return 0;
}

/**
 * ramdump_storage -- Save dump to local storage (SD card / flash)
 */
int cli_cmd_ramdump_storage(int argc, char **argv)
{
    (void)argc;
    (void)argv;

#ifdef RAMDUMP_ENABLE_STORAGE
    ramdump_put_bytes((const uint8_t *)
        "Saving dump to local storage...\r\n", 35);

    if (ramdump_storage_save(RAMDUMP_STORAGE_PATH) == RAMDUMP_EOK)
    {
        ramdump_put_bytes((const uint8_t *)"Done.\r\n", 7);
    }
    else
    {
        ramdump_put_bytes((const uint8_t *)"Failed!\r\n", 9);
    }
#else
    ramdump_put_bytes((const uint8_t *)
        "Local storage not enabled. Enable RAMDUMP_ENABLE_STORAGE in Kconfig.\r\n", 67);
#endif

    return 0;
}

/**
 * return -- No longer supported (ramdump always runs in exception context).
 * Use 'reboot' instead.
 */
int cli_cmd_return(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    ramdump_put_bytes((const uint8_t *)
        "\r\nReturn not available in exception context. Use 'reboot'.\r\n", 58);
    return 0;
}

/**
 * reboot -- System reset via SCB AIRCR
 */
int cli_cmd_reboot(int argc, char **argv)
{
    (void)argc;
    (void)argv;

    ramdump_put_bytes((const uint8_t *)
        "\r\nRebooting...\r\n", 17);

    /* Small delay so the message gets sent */
    {
        volatile uint32_t delay;
        for (delay = 0; delay < 1000000; delay++);
    }

    ramdump_reboot();

    /* Should never reach here */
    while (1);
    return 0;
}

#if RAMDUMP_TRANSPORT == RAMDUMP_TRANSPORT_USB
/**
 * vcom -- USB CDC ACM echo loopback test
 *
 * Runs in the same HardFault / polling context as a real crash dump.
 * Every received byte is echoed back.  Ctrl+C (0x03) to exit.
 */
int cli_cmd_vcom(int argc, char **argv)
{
    uint8_t echo_buf[64];
    uint32_t echo_len = 0;

    (void)argc;
    (void)argv;

    ramdump_put_bytes((const uint8_t *)
        "\r\nVCOM loopback active.  Type Ctrl+C to exit.\r\n", 50);

    while (1) {
        int ch = ramdump_getc(0);  /* non-blocking poll */
        if (ch < 0) {
            /* flush partial line after a quiet interval */
            if (echo_len > 0) {
                ramdump_put_bytes(echo_buf, echo_len);
                echo_len = 0;
            }
            continue;
        }

        /* Ctrl+C exits */
        if (ch == 0x03) {
            if (echo_len > 0)
                ramdump_put_bytes(echo_buf, echo_len);
            ramdump_put_bytes((const uint8_t *)
                "\r\nVCOM exited.\r\n", 16);
            return 0;
        }

        /* CR/LF flushes the line immediately */
        if (ch == '\r' || ch == '\n') {
            echo_buf[echo_len++] = (uint8_t)ch;
            ramdump_put_bytes(echo_buf, echo_len);
            echo_len = 0;
            continue;
        }

        /* Echo each byte for immediate feedback */
        ramdump_putc((uint8_t)ch);
    }
}
#endif /* RAMDUMP_TRANSPORT_USB */

/**
 * help -- Show available commands
 */
int cli_cmd_help(int argc, char **argv)
{
    const cli_cmd_t *cmd;

    (void)argc;
    (void)argv;

    ramdump_put_bytes((const uint8_t *)
        "\r\nRamdump CLI Commands:\r\n", 27);

    for (cmd = cli_commands; cmd->name != NULL; cmd++)
    {
        char buf[80];
        int len;

        len = snprintf(buf, sizeof(buf), "  %s\r\n", cmd->desc);
        ramdump_put_bytes((const uint8_t *)buf, len);
    }

    ramdump_put_bytes((const uint8_t *)"\r\n", 2);
    return 0;
}


/* ---- Command table ---- */

const cli_cmd_t cli_commands[] = {
    {"md",     "md <addr> [len]          - Memory display (hex dump)",      cli_cmd_md},
    {"mw",     "mw <addr> <val>          - Memory write (32-bit)",          cli_cmd_mw},
    {"ramdump","ramdump                  - YMODEM send all memory regions", cli_cmd_ramdump},
    {"ramdump_flash",
               "ramdump_flash            - YMODEM send FLASH only",        cli_cmd_ramdump_flash},
    {"ramdump_storage",
               "ramdump_storage          - Save dump to local storage",     cli_cmd_ramdump_storage},
    {"errorlog","errorlog                - Show exception info",            cli_cmd_errorlog},
    {"reboot", "reboot                   - Reset system",                   cli_cmd_reboot},
    {"return", "return                   - Return to MSH (manual mode only)",cli_cmd_return},
#if RAMDUMP_TRANSPORT == RAMDUMP_TRANSPORT_USB
    {"vcom",   "vcom                     - USB CDC ACM echo loopback test",  cli_cmd_vcom},
#endif
    {"help",   "help                     - Show this help",                 cli_cmd_help},
    {NULL, NULL, NULL}
};

int ramdump_commands_init(void)
{
    ramdump_cli_register_cmds(cli_commands);
    return 0;
}

/* ---- CLI Command Implementations ---- */
