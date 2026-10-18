/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * ramdump_storage.c -- storage backend registry (OS-free)
 *
 * Holds the one registered backend and forwards save requests to it.  The
 * DFS/SD-card implementation lives in port/rtthread/ramdump_port_storage.c;
 * nothing in this file touches the OS.
 */

#include "ramdump_storage.h"
#include "ramdump_config.h"

static const ramdump_storage_ops_t *g_storage;

void ramdump_storage_register(const ramdump_storage_ops_t *ops)
{
    g_storage = ops;
}

int ramdump_storage_available(void)
{
    return (g_storage != NULL) && (g_storage->save != NULL);
}

int ramdump_storage_save(const char *mount_point)
{
    if (!ramdump_storage_available())
    {
        ramdump_dbg_printf("[ramdump] No storage backend registered.\r\n");
        return RAMDUMP_ERR;
    }

    return g_storage->save(mount_point);
}

int ramdump_storage_save_default(void)
{
    return ramdump_storage_save(RAMDUMP_STORAGE_PATH);
}
