/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * ramdump_storage.h -- Local storage interface for dump images
 */

#ifndef RAMDUMP_STORAGE_H__
#define RAMDUMP_STORAGE_H__

#include <rtthread.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Save dump images to local storage (SD card / file system).
 *
 * The dump includes:
 *   - SRAM.bin (128KB)
 *   - CCM.bin  (64KB)
 *   - exception.txt (human-readable crash info)
 *
 * @param mount_point  file system mount point (e.g., "/sd")
 * @return RT_EOK on success, negative on error
 */
int ramdump_storage_save(const char *mount_point);

/**
 * Save dump images to the default storage path.
 *
 * @return RT_EOK on success, negative on error
 */
int ramdump_storage_save_default(void);

#ifdef __cplusplus
}
#endif

#endif /* RAMDUMP_STORAGE_H__ */
