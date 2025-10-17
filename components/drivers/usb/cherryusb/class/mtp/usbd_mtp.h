/*
 * Copyright (c) 2025, sakumisu
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#ifndef USBD_MTP_H
#define USBD_MTP_H

#include "usb_mtp.h"
#include "usbd_mtp.h"
#include <stdint.h>
#include "mtp_filesystem.h"

// 制造商信息
#ifndef CONFIG_USBDEV_MTP_MANUFACTURER
#define CONFIG_USBDEV_MTP_MANUFACTURER "CherryUSB"
#endif

// 产品型号
#ifndef CONFIG_USBDEV_MTP_MODEL
#define CONFIG_USBDEV_MTP_MODEL "CherryUSB MTP Device"
#endif


#ifdef __cplusplus
extern "C" {
#endif

struct usbd_interface *usbd_mtp_init_intf(struct usbd_interface *intf,
                                          const uint8_t out_ep,
                                          const uint8_t in_ep,
                                          const uint8_t int_ep);

// 弱定义回调函数
void mtp_data_send_done(void);
void mtp_data_recv_done(uint32_t len);

int usbd_mtp_start_write(uint8_t *buf, uint32_t len);
int usbd_mtp_start_read(uint8_t *buf, uint32_t len);
int usbd_mtp_start_write_int(uint16_t code, const uint32_t params[3]);
int mtp_enqueue_event(uint16_t code, const uint32_t params[3]);

#ifdef __cplusplus
}
#endif

#endif /* USBD_MTP_H */
