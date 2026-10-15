/*
 * protocol.c — Transfer protocol dispatch
 */

#include "ramdump_protocol.h"

static const ramdump_protocol_ops_t *g_proto;

void ramdump_protocol_register(const ramdump_protocol_ops_t *ops)
{
    g_proto = ops;
}

int ramdump_session_start(void)
{
    return g_proto ? g_proto->session_start() : RAMDUMP_ERR;
}

int ramdump_send_file(uint32_t addr, uint32_t size, const char *name)
{
    return g_proto ? g_proto->send_file(addr, size, name) : RAMDUMP_ERR;
}

int ramdump_session_end(void)
{
    return g_proto ? g_proto->session_end() : RAMDUMP_ERR;
}
