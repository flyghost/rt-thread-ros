/*
 * ramdump_init.c — Centralized RT-Thread initialization
 *
 * All RAMDUMP_INIT_EXPORT / RAMDUMP_CMD_EXPORT live here.
 * Other source files do NOT include ramdump_port_rtthread.h.
 */

#include "ramdump_port.h"
#include "port/rtthread/ramdump_port_rtthread.h"
#include "ramdump_io.h"
#include "ramdump_protocol.h"
#include "ramdump_exception.h"

/* ---- Assert hook (was in ramdump_assert.c) ---- */

extern int ramdump_assert_hook_init(void);
RAMDUMP_INIT_EXPORT(ramdump_assert_hook_init);

/* ---- CPU fault hook (zero-intrusion HardFault entry) ---- */

extern int ramdump_exception_hook_init(void);
RAMDUMP_INIT_EXPORT(ramdump_exception_hook_init);

/* ---- Thread list for Trace32 (was in ramdump_exception.c) ---- */

extern int ramdump_thread_list_init(void);
RAMDUMP_INIT_EXPORT(ramdump_thread_list_init);

/* ---- Command registration ---- */

extern int ramdump_commands_init(void);
RAMDUMP_INIT_EXPORT(ramdump_commands_init);

/* ---- Transport init (normal mode) ---- */

static int ramdump_transport_auto_init(void)
{
    ramdump_io_init();
    return 0;
}
RAMDUMP_INIT_EXPORT(ramdump_transport_auto_init);

/* ---- Protocol registration ---- */

extern const ramdump_protocol_ops_t ramdump_protocol_ymodem;

static int ramdump_protocol_init(void)
{
    ramdump_protocol_register(&ramdump_protocol_ymodem);
    return 0;
}
RAMDUMP_INIT_EXPORT(ramdump_protocol_init);
