/*
 * ramdump_io.h — Unified I/O abstraction
 *
 * Transports (UART, USB, ...) register themselves via ramdump_io_register().
 * The I/O layer does not include any transport headers — dependency is
 * inverted: transports depend on io, not the other way around.
 */

#ifndef RAMDUMP_IO_H__
#define RAMDUMP_IO_H__

#include "ramdump_port.h"
#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ---- Transport ops (implemented by each transport) ---- */
typedef struct ramdump_transport_ops {
    int  (*init)(void);
    void (*putc)(uint8_t ch);
    void (*put_bytes)(const uint8_t *data, uint32_t len);
    int  (*getc)(uint32_t timeout_ms);
    void (*poll)(void);
    void (*deinit)(void);
} ramdump_transport_ops_t;

/** Register a transport ops table. Called before ramdump_io_init(). */
void ramdump_io_register(const ramdump_transport_ops_t *ops);

/* ---- Init ---- */
int  ramdump_io_init(void);

/* ---- I/O primitives ---- */
void ramdump_putc(uint8_t ch);
void ramdump_put_bytes(const uint8_t *data, uint32_t len);
int  ramdump_getc(uint32_t timeout_ms);
void ramdump_io_poll(void);
void ramdump_io_deinit(void);

#ifdef __cplusplus
}
#endif

#endif /* RAMDUMP_IO_H__ */
