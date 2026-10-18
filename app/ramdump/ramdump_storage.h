/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * ramdump_storage.h -- Local storage backend interface (OS-free)
 *
 * The core only knows a save() function pointer.  A real file system
 * (DFS/FAT plus the SD card) is an OS service, so the implementation
 * lives in the port layer and registers itself with
 * ramdump_storage_register() at startup.
 */

#ifndef RAMDUMP_STORAGE_H__
#define RAMDUMP_STORAGE_H__

#include "ramdump_port.h"

#ifdef __cplusplus
extern "C" {
#endif

/** Backend contract: write every dump region below mount_point. */
typedef struct ramdump_storage_ops {
    /** @return RAMDUMP_EOK on success, RAMDUMP_ERR on failure */
    int (*save)(const char *mount_point);
} ramdump_storage_ops_t;

/**
 * Register the storage backend.  Called once by the port layer.
 */
void ramdump_storage_register(const ramdump_storage_ops_t *ops);

/**
 * Is a backend registered?
 *
 * @return 1 if ramdump_storage_save() can do anything, 0 otherwise
 */
int ramdump_storage_available(void);

/**
 * Save dump images through the registered backend.
 *
 * The dump includes (per RAMDUMP_DEFAULT_REGIONS):
 *   - SRAM.bin (128KB), CCM.bin (64KB), FLASH.bin (1MB)
 *   - exception.txt (human-readable crash info)
 *
 * @param mount_point  file system mount point (e.g. "/sd")
 * @return RAMDUMP_EOK on success, RAMDUMP_ERR if no backend is registered
 */
int ramdump_storage_save(const char *mount_point);

/**
 * Save dump images to RAMDUMP_STORAGE_PATH.
 *
 * @return RAMDUMP_EOK on success, RAMDUMP_ERR otherwise
 */
int ramdump_storage_save_default(void);

#ifdef __cplusplus
}
#endif

#endif /* RAMDUMP_STORAGE_H__ */
