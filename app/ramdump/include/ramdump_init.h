/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * ramdump_init.h -- the single entry point the core offers to the outside
 *
 * ramdump core code carries no OS dependency, so it cannot use any
 * INIT_*_EXPORT autostart machinery.  Instead the port layer (or the BSP)
 * calls ramdump_init() once at startup.
 */

#ifndef RAMDUMP_INIT_H__
#define RAMDUMP_INIT_H__

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialize every ramdump subsystem, in order:
 *   assert hook -> fault hook -> thread-list snapshot -> command table
 *   -> transport -> protocol.
 *
 * Does NOT enter the CLI.  That happens either on a fault
 * (ramdump_enter(), from the HardFault path) or on request through the
 * shell entry ramdump_msh_entry().
 */
void ramdump_init(void);

#ifdef __cplusplus
}
#endif

#endif /* RAMDUMP_INIT_H__ */
