/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * ramdump_cli.h -- Post-crash interactive CLI interface
 */

#ifndef RAMDUMP_CLI_H__
#define RAMDUMP_CLI_H__

#include "ramdump_port.h"
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Command descriptor (shared by CLI framework and commands) */
typedef struct {
    const char *name;
    const char *desc;
    int (*func)(int argc, char **argv);
} cli_cmd_t;

/** Register a command table (NULL-terminated).  Call before ramdump_enter(). */
void ramdump_cli_register_cmds(const cli_cmd_t *cmds);

/** Register the built-in command table (implemented in ramdump_commands.c). */
int ramdump_commands_init(void);

/**
 * Enter the ramdump CLI loop.
 *
 * This function runs in exception context (interrupts disabled, no scheduler).
 * It uses polled I/O through ramdump_io and does not return unless the
 * 'reboot' command is issued.
 *
 * The CLI provides the following commands:
 *   md <addr> [len]  - memory display (hex dump)
 *   mw <addr> <val>  - memory write (32-bit)
 *   ramdump          - YMODEM send all default memory regions
 *   ramdump <addr> <len> - YMODEM send a specific region
 *   errorlog         - show exception info
 *   ramdump_storage  - save dump to local storage (SD/Flash)
 *   reboot           - reset the system
 *   help             - show help message
 */
void ramdump_enter(void);

/**
 * Initialize the ramdump IO channel and print the crash summary,
 * then enter the interactive CLI loop.
 */
void ramdump_cli_loop(void);

/**
 * Shell entry point for the 'ramdump' command.
 *
 * Implemented here but registered by the OS port layer, which owns the
 * shell dependency -- this keeps the core free of any shell reference.
 * Runs in thread context, not in exception context.
 */
int ramdump_msh_entry(int argc, char **argv);

#ifdef __cplusplus
}
#endif

#endif /* RAMDUMP_CLI_H__ */
