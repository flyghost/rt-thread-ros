/*
 * Copyright (c) 2022, sakumisu
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * Modified for ramdump_usb: use rt_kprintf directly.
 */
#ifndef USB_LOG_H
#define USB_LOG_H

#include <stdio.h>

/* DEBUG level */
#define USB_DBG_ERROR   0
#define USB_DBG_WARNING 1
#define USB_DBG_INFO    2
#define USB_DBG_LOG     3

#ifndef USB_DBG_TAG
#define USB_DBG_TAG "USB"
#endif

#ifdef  CONFIG_USB_PRINTF_COLOR_ENABLE
#define _USB_DBG_COLOR(n)    CONFIG_USB_PRINTF("\033[" #n "m")
#define _USB_DBG_LOG_HDR(lvl_name, color_n) \
    CONFIG_USB_PRINTF("\033[" #color_n "m[" lvl_name "/" USB_DBG_TAG "] ")
#define _USB_DBG_LOG_X_END \
    CONFIG_USB_PRINTF("\033[0m")
#else
#define _USB_DBG_COLOR(n)
#define _USB_DBG_LOG_HDR(lvl_name, color_n) \
    CONFIG_USB_PRINTF("[" lvl_name "/" USB_DBG_TAG "] ")
#define _USB_DBG_LOG_X_END
#endif

#define usb_dbg_log_line(lvl, color_n, fmt, ...) \
    do {                                         \
        _USB_DBG_LOG_HDR(lvl, color_n);          \
        CONFIG_USB_PRINTF(fmt, ##__VA_ARGS__);              \
        _USB_DBG_LOG_X_END;                      \
    } while (0)

#if (CONFIG_USB_DBG_LEVEL >= USB_DBG_LOG)
#define USB_LOG_DBG(fmt, ...) usb_dbg_log_line("D", 0, fmt, ##__VA_ARGS__)
#else
#define USB_LOG_DBG(...)  {}
#endif

#if (CONFIG_USB_DBG_LEVEL >= USB_DBG_INFO)
#define USB_LOG_INFO(fmt, ...) usb_dbg_log_line("I", 32, fmt, ##__VA_ARGS__)
#else
#define USB_LOG_INFO(...) {}
#endif

#if (CONFIG_USB_DBG_LEVEL >= USB_DBG_WARNING)
#define USB_LOG_WRN(fmt, ...) usb_dbg_log_line("W", 33, fmt, ##__VA_ARGS__)
#else
#define USB_LOG_WRN(...) {}
#endif

#if (CONFIG_USB_DBG_LEVEL >= USB_DBG_ERROR)
#define USB_LOG_ERR(fmt, ...) usb_dbg_log_line("E", 31, fmt, ##__VA_ARGS__)
#else
#define USB_LOG_ERR(...) {}
#endif

#define USB_LOG_RAW(...) CONFIG_USB_PRINTF(__VA_ARGS__)

#ifndef CONFIG_USB_ASSERT_DISABLE
#define USB_ASSERT(f)                                                            \
    do {                                                                         \
        if (!(f)) {                                                              \
            USB_LOG_ERR("ASSERT FAIL [%s] @ %s:%d\r\n", #f, __FILE__, __LINE__); \
            while (1) {                                                          \
            }                                                                    \
        }                                                                        \
    } while (false)

#define USB_ASSERT_MSG(f, fmt, ...)                                              \
    do {                                                                         \
        if (!(f)) {                                                              \
            USB_LOG_ERR("ASSERT FAIL [%s] @ %s:%d\r\n", #f, __FILE__, __LINE__); \
            USB_LOG_ERR(fmt "\r\n", ##__VA_ARGS__);                              \
            while (1) {                                                          \
            }                                                                    \
        }                                                                        \
    } while (false)
#else
#define USB_ASSERT(f) {}
#define USB_ASSERT_MSG(f, fmt, ...) {}
#endif

#endif /* USB_LOG_H */
