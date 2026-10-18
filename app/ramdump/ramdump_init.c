/*
 * ramdump_init.c — single, OS-free initialization entry point
 *
 * This file used to hold RAMDUMP_INIT_EXPORT / RAMDUMP_CMD_EXPORT registrations,
 * which made the core depend on RT-Thread's INIT_*_EXPORT autostart sections.
 * It is an ordinary function now: the port layer calls ramdump_init() once at
 * startup (see port/rtthread/ramdump_port_rtthread.c).
 */

#include "ramdump_port.h"
#include "ramdump_init.h"
#include "ramdump_io.h"
#include "ramdump_protocol.h"
#include "ramdump_exception.h"

/* ---- Subsystem initializers (each returns 0; no header declares them) ---- */

extern int ramdump_assert_hook_init(void);      /* assert hook          */
extern int ramdump_exception_hook_init(void);   /* HardFault entry hook */
extern int ramdump_thread_list_init(void);      /* thread list snapshot */
extern int ramdump_commands_init(void);         /* CLI command table    */

/* ---- Transport init ---- */

static void ramdump_transport_auto_init(void)
{
    ramdump_io_init();
}

/* ---- Protocol registration ---- */

extern const ramdump_protocol_ops_t ramdump_protocol_ymodem;

static void ramdump_protocol_init(void)
{
    ramdump_protocol_register(&ramdump_protocol_ymodem);
}

void ramdump_init(void)
{
    ramdump_assert_hook_init();
    ramdump_exception_hook_init();
    ramdump_thread_list_init();
    ramdump_commands_init();
    ramdump_transport_auto_init();
    ramdump_protocol_init();
}
