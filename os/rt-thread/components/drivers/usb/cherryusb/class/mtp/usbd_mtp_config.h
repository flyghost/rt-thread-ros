#ifndef __USBD_MTP_CONFIG_H__
#define __USBD_MTP_CONFIG_H__

#include <stdint.h>
#include "usb_config.h"

// 文件系统配置
#define USB_FS_USING_STANDARD    0  // 1 - 使用标准C接口, 0 - 使用posix接口

// LOG配置
#define MTP_LOGRAW_SHELL(fmt, ...)  CONFIG_USB_PRINTF(fmt, ##__VA_ARGS__)
#define MTP_LOGD_SHELL(fmt, ...)    CONFIG_USB_PRINTF(fmt "\r\n", ##__VA_ARGS__)
#define MTP_LOGI_SHELL(fmt, ...)    CONFIG_USB_PRINTF("\033[" "32m" fmt "\033[0m" "\r\n", ##__VA_ARGS__)
#define MTP_LOGW_SHELL(fmt, ...)    CONFIG_USB_PRINTF("\033[" "33m" fmt "\033[0m" "\r\n", ##__VA_ARGS__)
#define MTP_LOGE_SHELL(fmt, ...)    CONFIG_USB_PRINTF("\033[" "31m" fmt "\033[0m" "\r\n", ##__VA_ARGS__)

// #define MTP_LOGRAW_SHELL(fmt, ...)  CONFIG_USB_PRINTF(fmt, ##__VA_ARGS__)
// #define MTP_LOGD_SHELL(fmt, ...)    CONFIG_USB_PRINTF("MTP_LOGD : " fmt "\n", ##__VA_ARGS__)
// #define MTP_LOGI_SHELL(fmt, ...)    CONFIG_USB_PRINTF("MTP_LOGI : " fmt "\n", ##__VA_ARGS__)
// #define MTP_LOGW_SHELL(fmt, ...)    CONFIG_USB_PRINTF("MTP_LOGW : " fmt "\n", ##__VA_ARGS__)
// #define MTP_LOGE_SHELL(fmt, ...)    CONFIG_USB_PRINTF("MTP_LOGE : " fmt "\n", ##__VA_ARGS__)


#define usb_memset      rt_memset
#define usb_mtp_memcpy      rt_memcpy
#define usb_strcmp      rt_strcmp
#define usb_strncmp     rt_strncmp
#define usb_strlen      rt_strlen
#define usb_strncpy     rt_strncpy
#define usb_malloc      rt_malloc
#define usb_free        rt_free
#define usb_strnlen        rt_strnlen

typedef rt_base_t USB_OSAL_IRQ_LOCK_TYPE;
#define USB_OSAL_IRQ_LOCK(lock)    lock = rt_hw_interrupt_disable()
#define USB_OSAL_IRQ_UNLOCK(lock)  rt_hw_interrupt_enable(lock)

static inline void MTP_DUMP_SHELL(uint32_t width, uint8_t *data, uint32_t len)
{
#define MTP_DUMP_SHOW_OFFSET 1
    if (len == 0) return;

    uint32_t i, j;
    uint32_t line_start = 0;

    for (i = 0; i < len; i++) {
        /* 行首显示偏移量（根据宏选择显示模式） */
        if (i % width == 0) {
#if MTP_DUMP_SHOW_OFFSET
            CONFIG_USB_PRINTF("%08x: ", (void*)(data + i)); // 显示实际内存地址
#else
            CONFIG_USB_PRINTF("%08x: ", i); // 从0开始计数
#endif
        }

        /* 打印HEX值（每8字节增加分隔空格） */
        CONFIG_USB_PRINTF("%02x ", data[i]);
        if ((i + 1) % 8 == 0 && (i + 1) % width != 0) {
            CONFIG_USB_PRINTF(" ");
        }

        /* 行尾处理 */
        if ((i + 1) % width == 0 || i == len - 1) {
            /* 计算当前行缺失的HEX格子数 */
            uint32_t remaining = width - ((i + 1) % width);
            if (remaining != width) {
                for (j = 0; j < remaining; j++) {
                    CONFIG_USB_PRINTF("   "); // 每个缺失HEX占3字符
                    if ((i + 1 + j) % 8 == 0) {
                        CONFIG_USB_PRINTF(" "); // 补充分隔空格
                    }
                }
            }

            /* 打印ASCII分隔符和内容 */
            CONFIG_USB_PRINTF("  ");
            for (j = line_start; j <= i; j++) {
                char c = (data[j] >= 0x20 && data[j] <= 0x7E) ? data[j] : '.';
                CONFIG_USB_PRINTF("%c", c);
            }

            /* 补齐ASCII列空格（严格对齐） */
            uint32_t ascii_remaining = width - (i - line_start + 1);
            for (j = 0; j < ascii_remaining; j++) {
                CONFIG_USB_PRINTF(" ");
            }

            CONFIG_USB_PRINTF("\r\n");
            line_start = i + 1;
        }
    }
#undef MTP_DUMP_SHOW_OFFSET
}

static inline void MTP_DUMP_SHELL_WITH_STRING(const char *str, uint32_t width, uint8_t *data, uint32_t len)
{
    if (len == 0) {
        return;
    }

    CONFIG_USB_PRINTF("%s\r\n", str);
    
    MTP_DUMP_SHELL(width, data, len);
}





#endif