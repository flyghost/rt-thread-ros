#include <stdio.h>
/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * ramdump_cli.c -- Post-crash interactive CLI
 *
 * This CLI runs in exception context (interrupts disabled, no scheduler).
 * It uses polled UART I/O through ramdump_io, so it does NOT depend on
 * any RT-Thread services (no semaphores, no threads, no malloc).
 *
 * In normal operation, the MSH commands 'ramdump' and 'ramdump_test'
 * are registered for manual testing.
 */

#include "ramdump_port.h"
#include "port/rtthread/ramdump_port_rtthread.h"
#include <string.h>
#include "ramdump_cli.h"
#include "ramdump_exception.h"
#include "ramdump_io.h"
#include "ramdump_protocol.h"
#include "ramdump_config.h"
#include "ramdump_assert.h"
#include "ramdump_utils.h"
#if RAMDUMP_ENABLE_LOCAL_STORAGE
#include "ramdump_storage.h"
#endif

#ifdef RT_USING_FINSH
#include <finsh.h>
#endif

#ifdef ULOG_USING_ASYNC_OUTPUT
#include <ulog.h>
#endif

/* RT-Thread's configurable assert hook (see rtthread.h) */

/* SCB AIRCR register for system reset */
#define SCB_AIRCR       (*(volatile unsigned long *)0xE000ED0C)
#define SCB_RESET_VALUE 0x05FA0004

#define CLI_PROMPT     "@ramdump> "
#define CLI_BUF_SIZE   128
#define CLI_MAX_ARGS   8

/* Always 0 — ramdump only runs in exception context (IRQs off).
 * Formerly set by cmd_ramdump cli, which no longer exists.
 * All paths now go through RAMDUMP_ASSERT → HardFault → ramdump_enter. */
static int g_ramdump_cli_msh_mode = 0;

/* ---- Command table (registered by commands.c) ---- */
static const cli_cmd_t *g_cmds;

void ramdump_cli_register_cmds(const cli_cmd_t *cmds)
{
    g_cmds = cmds;
}

/* ---- CLI Main Loop ---- */

/**
 * Enter the ramdump CLI. Called ONLY from the HardFault exception handler
 * (cpuport.c).  The CPU has already disabled global interrupts on exception
 * entry — no need for rt_enter_critical() here.
 */
void ramdump_enter(void)
{
    ramdump_cli_loop();
    /* ramdump_cli_loop only returns via reboot — we should never reach here */
    while (1);
}

/**
 * Main CLI loop. Initializes IO, prints exception info, and
 * processes commands until 'reboot' is issued.
 */
void ramdump_cli_loop(void)
{
    int ret;

    /* Init debug UART first — safe in exception context */
    ramdump_dbg_init();

    /* Register commands (also done via RAMDUMP_INIT_EXPORT in normal mode) */
    ramdump_commands_init();

    /* Initialize I/O — transport selection is internal to ramdump_io */
    ret = ramdump_io_init();
    if (ret != RAMDUMP_EOK)
    {
        ramdump_dbg_printf("\r\nWarning: I/O init failed\r\n");
        /* g_ops is NULL — put_bytes won't work.  CLI loop uses dbg_printf. */
    }

    /* Print crash summary (if available) */
    ramdump_exception_print();

    /* Print welcome message */
    ramdump_put_bytes((const uint8_t *)
        "\r\nEntering ramdump mode. Type 'help' for commands.\r\n", 53);

    /* Command loop — infinite, only exits via 'reboot' */
    while (1)
    {
        char cli_buf[CLI_BUF_SIZE];
        int idx = 0;

        /* Poll all channels — keeps USB alive between commands */
        ramdump_io_poll();

        ramdump_put_bytes((const uint8_t *)CLI_PROMPT, sizeof(CLI_PROMPT) - 1);

        /* Read a line */
        while (idx < CLI_BUF_SIZE - 1)
        {
            int ch = ramdump_getc(1000);  /* 1s inter-char timeout */
            if (ch < 0) continue;

            if (ch == '\r' || ch == '\n')
            {
                ramdump_putc('\r');
                ramdump_putc('\n');
                break;
            }
            if (ch == '\b' || ch == 0x7F)  /* backspace / DEL */
            {
                if (idx > 0)
                {
                    idx--;
                    ramdump_putc('\b');
                    ramdump_putc(' ');
                    ramdump_putc('\b');
                }
                continue;
            }
            /* Only accept printable ASCII */
            if (ch >= 0x20 && ch <= 0x7E)
            {
                cli_buf[idx++] = (char)ch;
                ramdump_putc((uint8_t)ch);
            }
        }
        cli_buf[idx] = '\0';

        if (idx == 0) continue;

        /* Parse command line into argc/argv */
        {
            char *argv[CLI_MAX_ARGS];
            int argc = 0;
            char *tok = cli_buf;
            const cli_cmd_t *cmd;
            int found = 0;

            /* Skip leading spaces */
            while (*tok == ' ') tok++;

            while (*tok && argc < CLI_MAX_ARGS)
            {
                argv[argc++] = tok;
                while (*tok && *tok != ' ') tok++;
                if (*tok) { *tok = '\0'; tok++; }
                while (*tok == ' ') tok++;
            }

            if (argc == 0) continue;

            /* Find and execute command */
            for (cmd = g_cmds; cmd && cmd->name != NULL; cmd++)
            {
                if (strcmp(argv[0], cmd->name) == 0)
                {
                    cmd->func(argc, argv);
                    found = 1;
                    break;
                }
            }

            if (!found)
            {
                ramdump_put_bytes((const uint8_t *)
                    "Unknown command. Type 'help'.\r\n", 34);
            }
        }
    }
}

static int cmd_ramdump(int argc, char **argv)
{
    const char *sub = (argc >= 2) ? argv[1] : "";

    if (strcmp(sub, "busfault") == 0)
    {
        ramdump_dbg_printf("[ramdump] Triggering BusFault in 1s...\r\n");
        ramdump_delay_ms(1000);
        *(volatile uint32_t *)0xFFFFFFFF = 0xDEADBEEF;
        ramdump_dbg_printf("[ramdump] Fault did not trigger?!\r\n");
        return 0;
    }

    if (strcmp(sub, "errorlog") == 0)
    {
        if (ramdump_exception_is_valid())
        {
            ramdump_exception_print();
            ramdump_dbg_printf("[ramdump] Clearing exception record.\r\n");
            ramdump_exception_clear();
        }
        else
        {
            ramdump_dbg_printf("[ramdump] No valid exception record.\r\n");
        }
        return 0;
    }

    /* default: trigger RAMDUMP_ASSERT → UDF → HardFault → ramdump_enter */
    ramdump_exception_clear();
    ramdump_dbg_printf("[ramdump] Entering ramdump via RAMDUMP_ASSERT(0)...\r\n");
    ramdump_delay_ms(100);
    RAMDUMP_ASSERT(0);
    /* never returns */
}
#ifdef RT_USING_FINSH
RAMDUMP_CMD_EXPORT(cmd_ramdump, ramdump: enter ramdump via assertion);
#endif /* RT_USING_FINSH */
