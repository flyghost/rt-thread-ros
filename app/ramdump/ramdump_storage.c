/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * ramdump_storage.c -- Save dump images to local storage (SD card / Flash)
 *
 * Uses the DFS (Device File System) to write memory images to files.
 * Each dump session creates a timestamped directory containing:
 *   SRAM.bin, CCM.bin, exception.txt
 */

#include <rtthread.h>
#include <string.h>

#ifdef RT_USING_DFS
#include <dfs.h>
#include <dfs_file.h>
#include <dfs_posix.h>
#endif

#include "ramdump_storage.h"
#include "ramdump_config.h"
#include "ramdump_exception.h"

/**
 * Save dump images to local storage.
 */
int ramdump_storage_save(const char *mount_point)
{
#ifdef RT_USING_DFS
    char path[256];
    char filepath[300];
    char timestamp[32];
    int fd;
    int ret;
    rt_uint32_t i;
    ramdump_region_t regions[] = RAMDUMP_DEFAULT_REGIONS;
    int count = sizeof(regions) / sizeof(regions[0]);
    time_t now;

    now = rt_tick_get() / RT_TICK_PER_SECOND;

    /* Create timestamped directory */
    rt_snprintf(timestamp, sizeof(timestamp), "%ld", (long)now);
    rt_snprintf(path, sizeof(path), "%s/ramdump_%s", mount_point, timestamp);

    ret = mkdir(path, 0);
    if (ret < 0)
    {
        ramdump_dbg_printf("[ramdump] Failed to create directory %s (err=%d)\r\n", path, ret);
        /* Try to continue even if mkdir fails (directory may already exist) */
    }

    ramdump_dbg_printf("[ramdump] Saving dump to %s ...\r\n", path);

    /* Save memory region files */
    for (i = 0; i < (rt_uint32_t)count; i++)
    {
        rt_snprintf(filepath, sizeof(filepath), "%s/%s", path, regions[i].name);

        fd = open(filepath, O_WRONLY | O_CREAT | O_TRUNC, 0666);
        if (fd < 0)
        {
            ramdump_dbg_printf("[ramdump] Failed to create %s\r\n", filepath);
            continue;
        }

        ret = write(fd, (const void *)regions[i].addr, regions[i].size);
        if (ret != (int)regions[i].size)
        {
            ramdump_dbg_printf("[ramdump] Write error on %s: wrote %d of %lu bytes\r\n",
                       filepath, ret, (unsigned long)regions[i].size);
        }
        else
        {
            ramdump_dbg_printf("[ramdump] Saved %s (%lu bytes)\r\n",
                       regions[i].name, (unsigned long)regions[i].size);
        }

        close(fd);
    }

    /* Save exception info as text file */
    rt_snprintf(filepath, sizeof(filepath), "%s/exception.txt", path);
    fd = open(filepath, O_WRONLY | O_CREAT | O_TRUNC, 0666);
    if (fd >= 0)
    {
        char buf[512];
        int len;

        if (ramdump_exception_is_valid())
        {
            ramdump_exception_t *e = &g_ramdump_exception;
            const char *fault_names[] = {
                "HardFault", "MemManage", "BusFault", "UsageFault", "Assert"
            };

            len = rt_snprintf(buf, sizeof(buf),
                "Fault Type: %s\r\n"
                "Thread: %s\r\n"
                "Tick: %lu\r\n"
                "CFSR: 0x%08lx\r\n"
                "HFSR: 0x%08lx\r\n"
                "MMFAR: 0x%08lx\r\n"
                "BFAR: 0x%08lx\r\n"
                "Frame @: 0x%08lx\r\n",
                fault_names[e->fault_type],
                e->thread_name,
                (unsigned long)e->tick,
                (unsigned long)e->cfsr,
                (unsigned long)e->hfsr,
                (unsigned long)e->mmfar,
                (unsigned long)e->bfar,
                (unsigned long)e->hw_frame_ptr);
        }
        else
        {
            len = rt_snprintf(buf, sizeof(buf),
                "No valid exception record.\r\n");
        }

        write(fd, buf, len);
        close(fd);
        ramdump_dbg_printf("[ramdump] Saved exception.txt\r\n");
    }

    ramdump_dbg_printf("[ramdump] All files saved to %s\r\n", path);
    return RT_EOK;
#else
    (void)mount_point;
    ramdump_dbg_printf("[ramdump] DFS not enabled. Cannot save to storage.\r\n");
    return -RT_ERROR;
#endif /* RT_USING_DFS */
}

/**
 * Save to default storage path.
 */
int ramdump_storage_save_default(void)
{
#ifdef RAMDUMP_STORAGE_PATH
    return ramdump_storage_save(RAMDUMP_STORAGE_PATH);
#else
    return ramdump_storage_save("/sd");
#endif
}
