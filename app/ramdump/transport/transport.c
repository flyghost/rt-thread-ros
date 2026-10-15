/*
 * transport.c — I/O dispatch through transport ops
 *
 * ramdump_init.c selects and registers the active transport at compile
 * time.  This file only stores the ops pointer, calls init, and forwards
 * all I/O calls.
 */

#include "ramdump_config.h"
#include "ramdump_io.h"

extern const ramdump_transport_ops_t ramdump_transport_uart;
extern const ramdump_transport_ops_t ramdump_transport_usb;

static const ramdump_transport_ops_t *g_ops;

void ramdump_io_register(const ramdump_transport_ops_t *ops)
{
    g_ops = ops;
}

int ramdump_io_init(void)
{
    const ramdump_transport_ops_t *ops = NULL;

#if RAMDUMP_TRANSPORT == RAMDUMP_TRANSPORT_UART
    ops = &ramdump_transport_uart;
#elif RAMDUMP_TRANSPORT == RAMDUMP_TRANSPORT_USB
    ops = &ramdump_transport_usb;
#endif

    ramdump_io_register(ops);
    return (g_ops && g_ops->init) ? g_ops->init() : RAMDUMP_ERR;
}

/* ---- Public I/O API — unconditional forwarding with NULL guards ---- */

void ramdump_putc(uint8_t ch)
{
    if (g_ops) g_ops->putc(ch);
}

void ramdump_put_bytes(const uint8_t *data, uint32_t len)
{
    if (g_ops) g_ops->put_bytes(data, len);
}

int ramdump_getc(uint32_t timeout_ms)
{
    return g_ops ? g_ops->getc(timeout_ms) : -1;
}

void ramdump_io_poll(void)
{
    if (g_ops) g_ops->poll();
}

void ramdump_io_deinit(void)
{
    if (g_ops) g_ops->deinit();
}
