#ifndef __USBD_MTP_CONFIG_H__
#define __USBD_MTP_CONFIG_H__

#include <stdint.h>
#include "usb_config.h"

#define MTP_LOGD_SHELL(fmt, ...)    CONFIG_USB_PRINTF(fmt "\r\n", ##__VA_ARGS__)
#define MTP_LOGI_SHELL(fmt, ...)    CONFIG_USB_PRINTF("\033[" "32m" fmt "\033[0m" "\r\n", ##__VA_ARGS__)
#define MTP_LOGW_SHELL(fmt, ...)    CONFIG_USB_PRINTF("\033[" "33m" fmt "\033[0m" "\r\n", ##__VA_ARGS__)
#define MTP_LOGE_SHELL(fmt, ...)    CONFIG_USB_PRINTF("\033[" "31m" fmt "\033[0m" "\r\n", ##__VA_ARGS__)

#define MTP_STORAGE_ID              0x00010001   //存储ID定义


#define usb_memset      rt_memset
#define usb_mtp_memcpy      rt_memcpy
#define usb_strcmp      rt_strcmp
#define usb_strncmp     rt_strncmp
#define usb_strlen      rt_strlen
#define usb_strncpy     rt_strncpy
#define usb_malloc      rt_malloc
#define usb_free        rt_free

static inline void MTP_DUMP_SHELL(uint32_t width, uint8_t *data, uint32_t len)
{
    if (len == 0) {
        return;
    }
    
    uint32_t i;
    for (i = 0; i < len; i++) {
        // if (i % width == 0) {
        //     CONFIG_USB_PRINTF("%08x: ", i);
        // }
        CONFIG_USB_PRINTF("%02x ", data[i]);
        if ((i + 1) % width == 0 || i == len - 1) {
            CONFIG_USB_PRINTF("\r\n");
        }
    }
}





#endif