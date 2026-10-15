/*
 * ramdump_protocol.h — Transfer protocol abstraction
 *
 * Protocol implementations (YMODEM, custom, ...) register themselves
 * via ramdump_protocol_register().  The CLI composes multi-region dumps
 * from the three primitives below — the protocol only handles single-file
 * transfer mechanics.
 */

#ifndef RAMDUMP_PROTOCOL_H__
#define RAMDUMP_PROTOCOL_H__

#include "ramdump_port.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    int  (*session_start)(void);
    int  (*send_file)(uint32_t addr, uint32_t size, const char *name);
    int  (*session_end)(void);
} ramdump_protocol_ops_t;

void ramdump_protocol_register(const ramdump_protocol_ops_t *ops);

/* ---- Public API (forwards to registered ops) ---- */
int  ramdump_session_start(void);
int  ramdump_send_file(uint32_t addr, uint32_t size, const char *name);
int  ramdump_session_end(void);

#ifdef __cplusplus
}
#endif

#endif /* RAMDUMP_PROTOCOL_H__ */
