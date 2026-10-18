/*
 * ramdump_usb_printf.h — pin the CherryUSB log backend to ramdump.
 *
 * Why this file exists:
 *   The basename "usb_config.h" is ambiguous. Two files carry it:
 *     - app/ramdump/transport/usb/common/usb_config.h  (this stack's own config;
 *       maps CONFIG_USB_PRINTF -> ramdump_dbg_printf, the polled UART)
 *     - bsp/stm32/stm32f407-atk-explorer/board/usb_config.h  (the BSP board copy
 *       for the on-chip CherryUSB stack; maps CONFIG_USB_PRINTF -> rt_kprintf)
 *   Include-path order makes the board copy win inside our stack, so every
 *   USB_LOG_* site was routed to the MSH console instead of the polled UART.
 *   That is both an OS-component dependency and a hazard: these log sites run
 *   from usb_dc_init()/dwc2_reset()/usbd_ep_open(), i.e. inside
 *   ramdump_io_init() on the HardFault path, where the scheduler is stopped.
 *
 * Included by usbd_core.h right AFTER "usb_config.h" (which is include-guarded,
 * so it can only take effect once per translation unit). The #undef below
 * therefore wins for the whole file body of every translation unit that pulls
 * in usbd_core.h — no reliance on include-path order.
 */
#ifndef RAMDUMP_USB_PRINTF_H
#define RAMDUMP_USB_PRINTF_H

#include "ramdump_port.h"

#undef CONFIG_USB_PRINTF
#define CONFIG_USB_PRINTF(...) ramdump_dbg_printf(__VA_ARGS__)

#endif /* RAMDUMP_USB_PRINTF_H */
