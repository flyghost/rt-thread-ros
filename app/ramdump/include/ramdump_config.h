/*
 * Copyright (c) 2006-2024, RT-Thread Development Team
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * ramdump_config.h -- STM32F407ZG memory layout and configuration
 */

#ifndef RAMDUMP_CONFIG_H__
#define RAMDUMP_CONFIG_H__

#include "ramdump_port.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ===== STM32F407ZG Memory Region Definitions ===== */
#define RAMDUMP_REGION_SRAM_ADDR    0x20000000
#define RAMDUMP_REGION_SRAM_SIZE    (128 * 1024)    /* 128KB SRAM */

#define RAMDUMP_REGION_CCM_ADDR     0x10000000
#define RAMDUMP_REGION_CCM_SIZE     (64 * 1024)     /* 64KB CCM RAM */

#define RAMDUMP_REGION_FLASH_ADDR   0x08000000
#define RAMDUMP_REGION_FLASH_SIZE   (1024 * 1024)   /* 1MB Flash */

/* ===== Dump Policy ===== */
/* Default: dump SRAM + CCM. Flash is available on demand. */
#define RAMDUMP_DEFAULT_REGIONS     \
    {                                \
        {RAMDUMP_REGION_SRAM_ADDR,  RAMDUMP_REGION_SRAM_SIZE,  "SRAM.bin"},  \
        {RAMDUMP_REGION_CCM_ADDR,   RAMDUMP_REGION_CCM_SIZE,   "CCM.bin"},   \
        {RAMDUMP_REGION_FLASH_ADDR, RAMDUMP_REGION_FLASH_SIZE, "FLASH.bin"},  \
    }

/* Region descriptor structure */
typedef struct {
    uint32_t addr;       /* start address */
    uint32_t size;       /* region size in bytes */
    const char *name;        /* file name for YMODEM transfer */
} ramdump_region_t;

/* ===== Transport Configuration ===== */
/*
 * Choose ONE transport for dump output (mutually exclusive):
 *   RAMDUMP_TRANSPORT_UART  — polling UART only
 *   RAMDUMP_TRANSPORT_USB   — USB CDC ACM only
 *
 * USB transport also requires RT_USING_RAMDUMP_USB in rtconfig.h.
 */
#define RAMDUMP_TRANSPORT_UART  0
#define RAMDUMP_TRANSPORT_USB   1

#ifndef RAMDUMP_TRANSPORT
#define RAMDUMP_TRANSPORT  RAMDUMP_TRANSPORT_USB
#endif

#ifndef RAMDUMP_UART_DEVICE
#define RAMDUMP_UART_DEVICE     "uart1"
#endif

#ifndef RAMDUMP_UART_BAUDRATE
#define RAMDUMP_UART_BAUDRATE   115200
#endif

/* ===== Debug Output ===== */
/*
 * RAMDUMP_DBG_UART — polling UART (safe in HardFault crash context)
 * RAMDUMP_DBG_RTT  — rt_kprintf (MSH console, normal mode only)
 */
#define RAMDUMP_DBG_UART  0
#define RAMDUMP_DBG_RTT   1

#ifndef RAMDUMP_DBG_MODE
#define RAMDUMP_DBG_MODE  RAMDUMP_DBG_UART
#endif

/* ===== Feature Switches ===== */
/*
 * Names match app/ramdump/Kconfig, so menuconfig actually takes effect.
 *
 * Kconfig emits these as *valueless* defines (e.g. "#define RAMDUMP_ENABLE_STORAGE"),
 * so they must be tested with #ifdef — never with "#if RAMDUMP_ENABLE_STORAGE",
 * which expands to "#if" with no expression and fails to compile.
 * Do not give them a C-side numeric default here: that would make #ifdef true
 * even when the feature is switched off in Kconfig.
 */

#ifndef RAMDUMP_STORAGE_PATH
#define RAMDUMP_STORAGE_PATH    "/sd"
#endif

#ifndef RAMDUMP_ENABLE_EXCEPTION_AUTO
#define RAMDUMP_ENABLE_EXCEPTION_AUTO 1
#endif

#ifdef __cplusplus
}
#endif

#endif /* RAMDUMP_CONFIG_H__ */
