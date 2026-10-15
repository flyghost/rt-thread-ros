/*
 * usb_config.h — ramdump_usb minimal configuration
 *
 * Stripped down from cherryusb_config_template.h.
 * No OSAL threads, no DMA, no dcache.
 */
#ifndef RAMDUMP_USB_CONFIG_H
#define RAMDUMP_USB_CONFIG_H

#include <rtthread.h>
#include "ramdump_port.h"

/* ---- printf backend (polling UART, safe in crash context) ---- */
#define CONFIG_USB_PRINTF(...) ramdump_dbg_printf(__VA_ARGS__)

/* ---- debug level ---- */
#define CONFIG_USB_DBG_LEVEL USB_DBG_INFO

/* ---- data alignment (no DMA, no dcache) ---- */
#define CONFIG_USB_ALIGN_SIZE 4

/* Use standard libc memcpy instead of cherryusb's optimized version.
 * Safer in crash context where source data may be at arbitrary addresses. */
#define CONFIG_USB_MEMCPY_DISABLE

#define USB_NOCACHE_RAM_SECTION
#define USB_MEM_ALIGNX __attribute__((aligned(CONFIG_USB_ALIGN_SIZE)))

/* ---- EP0 buffer size ---- */
#define CONFIG_USBDEV_REQUEST_BUFFER_LEN 512

/* ---- device stack ---- */
#define CONFIG_USBDEV_MAX_BUS      1
#define CONFIG_USBDEV_EP_NUM       4   /* EP0 + 2xCDC_ACM(bulk IN/OUT) */

/* ---- DWC2 port (same as cherryusb BSP usb_config.h) ---- */
// #define CONFIG_USB_DWC2_DMA_ENABLE   /* STM32F407 OTG FS = slave-only, no DMA */
#define CONFIG_USB_DWC2_RXALL_FIFO_SIZE  (512 / 4)
#define CONFIG_USB_DWC2_TX0_FIFO_SIZE     (64 / 4)
#define CONFIG_USB_DWC2_TX1_FIFO_SIZE     (64 / 4)
#define CONFIG_USB_DWC2_TX2_FIFO_SIZE     (64 / 4)
#define CONFIG_USB_DWC2_TX3_FIFO_SIZE     (64 / 4)

/* ---- STM32F407 DWC2 glue ---- */
#define CONFIG_USBDEV_DWC2_ST

#endif /* RAMDUMP_USB_CONFIG_H */
