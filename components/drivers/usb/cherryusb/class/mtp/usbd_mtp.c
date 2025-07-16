/*
 * Copyright (c) 2025, sakumisu
 *
 * SPDX-License-Identifier: Apache-2.0
 *
 * USB MTP 设备核心实现
 */

#include "usb_config.h"
#include "usbd_mtp_config.h"
#include "usbd_core.h"
#include "usbd_mtp.h"
#include "usb_mtp.h"
#include "mtp_operation.h"
#include <string.h>

/* 端点配置 */
#define MTP_OUT_EP_IDX 0
#define MTP_IN_EP_IDX  1
#define MTP_INT_EP_IDX 2

/* 端点描述符 */
static struct usbd_endpoint mtp_ep_data[3];

/* MTP 全局状态 */
struct usbd_mtp_priv g_usbd_mtp;

/* 非缓存缓冲区 */
USB_NOCACHE_RAM_SECTION USB_MEM_ALIGNX uint8_t mtp_rx_buffer[MTP_BUFFER_SIZE];
USB_NOCACHE_RAM_SECTION USB_MEM_ALIGNX uint8_t mtp_tx_buffer[MTP_BUFFER_SIZE];
USB_NOCACHE_RAM_SECTION USB_MEM_ALIGNX uint8_t mtp_int_buffer[100];

extern void usbd_mtp_mount(void);

/* USB 事件回调 */
static void mtp_notify_handler(uint8_t busid, uint8_t event, void *arg)
{
    (void)busid;
    (void)arg;

    switch (event) {
        case USBD_EVENT_RESET:
            g_usbd_mtp.session_open = false;
            g_usbd_mtp.session_id = 0;
            g_usbd_mtp.transaction_id = 0;
            break;
            
        case USBD_EVENT_CONFIGURED:
            usbd_mtp_mount();
            usbd_mtp_object_init();
            usbd_mtp_start_read(mtp_rx_buffer, MTP_BUFFER_SIZE);
            break;
            
        default:
            break;
    }
}

/* 批量输出端点回调（接收主机数据） */
void mtp_bulk_out(uint8_t busid, uint8_t ep, uint32_t nbytes)
{
    (void)busid;
    (void)ep;

    MTP_LOGD_SHELL("\r\nreceive %d bytes", nbytes);
    MTP_DUMP_SHELL(32, g_usbd_mtp.rx_buffer, nbytes);

    if (g_usbd_mtp.rx_length == 0) {
        /* 新命令包 */
        struct mtp_header *hdr = (struct mtp_header *)g_usbd_mtp.rx_buffer;
        if (nbytes < sizeof(struct mtp_header)) {
            usbd_mtp_start_read(mtp_rx_buffer, MTP_BUFFER_SIZE);
            return;
        }
        
        g_usbd_mtp.rx_total_length = hdr->conlen;
        g_usbd_mtp.rx_length = nbytes;
        
        if (nbytes < hdr->conlen) {
            usbd_ep_start_read(busid, ep, 
                g_usbd_mtp.rx_buffer + nbytes, 
                hdr->conlen - nbytes);
            return;
        }
    } else {
        /* 继续接收数据 */
        g_usbd_mtp.rx_length += nbytes;
        if (g_usbd_mtp.rx_length < g_usbd_mtp.rx_total_length) {
            usbd_ep_start_read(busid, ep, 
                g_usbd_mtp.rx_buffer + g_usbd_mtp.rx_length, 
                g_usbd_mtp.rx_total_length - g_usbd_mtp.rx_length);
            return;
        }
    }
    
    /* 完整数据包接收完成，处理命令 */
    mtp_command_handler(g_usbd_mtp.rx_buffer, g_usbd_mtp.rx_length);
    
    /* 重置接收状态 */
    g_usbd_mtp.rx_length = 0;
    g_usbd_mtp.rx_total_length = 0;

    usbd_mtp_start_read(mtp_rx_buffer, MTP_BUFFER_SIZE);
}

/* 批量输入端点回调（发送数据到主机） */
void mtp_bulk_in(uint8_t busid, uint8_t ep, uint32_t nbytes)
{
    (void)busid;
    (void)ep;
    (void)nbytes;

    MTP_LOGD_SHELL("send %d bytes ok", nbytes);

    if (g_usbd_mtp.tx_length > 0) {
        g_usbd_mtp.tx_length = 0;
        mtp_data_send_done();

        struct mtp_header *hdr = (struct mtp_header *)g_usbd_mtp.tx_buffer;

        if (hdr->contype != MTP_CONTAINER_TYPE_RESPONSE) {
            mtp_send_response(MTP_RESPONSE_OK, hdr->trans_id);
        }
    }
}

/* 中断端点回调 */
void mtp_int_in(uint8_t busid, uint8_t ep, uint32_t nbytes)
{
    (void)busid;
    (void)ep;
    (void)nbytes;
}

/* MTP 类接口请求处理 */
static int mtp_class_interface_request_handler(uint8_t busid, struct usb_setup_packet *setup, uint8_t **data, uint32_t *len)
{
    (void)busid;

    MTP_LOGE_SHELL("MTP class interface request: bRequest = 0x%02x, wValue = 0x%04x, wIndex = 0x%04x, wLength = %d",
             setup->bRequest, setup->wValue, setup->wIndex, setup->wLength);
    
    switch (setup->bRequest) {
        case MTP_REQUEST_CANCEL:
            /* 取消当前传输 */
            g_usbd_mtp.rx_length = 0;
            g_usbd_mtp.tx_length = 0;
            g_usbd_mtp.cur_object = NULL;
            *len = 0;
            return 0;
            
        case MTP_REQUEST_GET_EXT_EVENT_DATA:
            /* 获取扩展事件数据 */
            *data = mtp_int_buffer;
            *len = 0; // 当前实现不提供扩展事件数据
            return 0;
            
        case MTP_REQUEST_RESET:
            /* 重置设备 */
            g_usbd_mtp.session_open = false;
            g_usbd_mtp.session_id = 0;
            g_usbd_mtp.transaction_id = 0;
            g_usbd_mtp.rx_length = 0;
            g_usbd_mtp.tx_length = 0;
            g_usbd_mtp.cur_object = NULL;
            *len = 0;
            return 0;
            
        case MTP_REQUEST_GET_DEVICE_STATUS: {
            /* 获取设备状态 */
            struct mtp_device_status {
                uint16_t status_code;
                uint32_t session_id;
                uint32_t transaction_id;
                uint8_t params[5];
            } *status = (struct mtp_device_status *)mtp_int_buffer;
            
            status->status_code = MTP_RESPONSE_OK;
            status->session_id = g_usbd_mtp.session_id;
            status->transaction_id = g_usbd_mtp.transaction_id;
            memset(status->params, 0, sizeof(status->params));
            
            *data = mtp_int_buffer;
            *len = sizeof(struct mtp_device_status);
            return 0;

        // case 0x64: {  // Windows MTP 初始化请求
        //     /* 返回 6 字节数据：协议版本 + 功能标志 */
        //     uint8_t response[6] = {0x01, 0x00, 0x02, 0x00, 0x00, 0x00}; // MTP 1.0, 基础功能
        //     memcpy(mtp_int_buffer, response, sizeof(response));
        //     *data = mtp_int_buffer;
        //     *len = sizeof(response);
        //     return 0;
        // }

        // case 0x67: {  // Windows MTP 设备信息请求
        //     /* 返回 36 字节数据：状态码 + 设备ID + 扩展数据 */
        //     uint8_t response[36] = {
        //         0x04, 0x00, 0x01, 0x20,  // Status: RESPONSE_OK (0x2001)
        //         0x03, 0x00, 0x01, 0x20,  // Data block count (示例值)
        //         0x00, 0x00, 0x00, 0x00,  // Reserved
        //         // 16-byte 设备唯一ID (随机生成)
        //         0xC8, 0xAA, 0x6B, 0xD3, 0x0D, 0xA3, 0xA6, 0xAE,
        //         0xAB, 0x8C, 0xA8, 0x69, 0xA8, 0x0F, 0x3F, 0xBE,
        //         // 8-byte 尾部数据 (填充或校验和)
        //         0x4C, 0xDA, 0xAA, 0xBA, 0xAA, 0x8F, 0x6E, 0x0D
        //     };
        //     memcpy(mtp_int_buffer, response, sizeof(response));
        //     *data = mtp_int_buffer;
        //     *len = sizeof(response);
        //     return 0;
        }
        
        default:
            return -1;
    }
    return -1;
}

/* 初始化 MTP 接口 */
struct usbd_interface *usbd_mtp_init_intf(struct usbd_interface *intf,
                                         const uint8_t out_ep,
                                         const uint8_t in_ep,
                                         const uint8_t int_ep)
{
    /* 初始化端点配置 */
    mtp_ep_data[MTP_OUT_EP_IDX].ep_addr = out_ep;
    mtp_ep_data[MTP_OUT_EP_IDX].ep_cb = mtp_bulk_out;
    mtp_ep_data[MTP_IN_EP_IDX].ep_addr = in_ep;
    mtp_ep_data[MTP_IN_EP_IDX].ep_cb = mtp_bulk_in;
    mtp_ep_data[MTP_INT_EP_IDX].ep_addr = int_ep;
    mtp_ep_data[MTP_INT_EP_IDX].ep_cb = mtp_int_in;

    /* 添加端点 */
    usbd_add_endpoint(0, &mtp_ep_data[MTP_OUT_EP_IDX]);
    usbd_add_endpoint(0, &mtp_ep_data[MTP_IN_EP_IDX]);
    usbd_add_endpoint(0, &mtp_ep_data[MTP_INT_EP_IDX]);

    /* 设置接口处理函数 */
    intf->class_interface_handler = mtp_class_interface_request_handler;
    intf->class_endpoint_handler = NULL;
    intf->vendor_handler = NULL;
    intf->notify_handler = mtp_notify_handler;

    /* 初始化全局变量 */
    memset(&g_usbd_mtp, 0, sizeof(g_usbd_mtp));
    g_usbd_mtp.rx_buffer = mtp_rx_buffer;
    g_usbd_mtp.tx_buffer = mtp_tx_buffer;

    return intf;
}

/* 启动数据发送 */
int usbd_mtp_start_write(uint8_t *buf, uint32_t len)
{
    if (!usb_device_is_configured(0)) {
        return -1;
    }

    if (g_usbd_mtp.tx_length > 0) {
        return -1; /* 上次发送未完成 */
    }

    MTP_LOGD_SHELL("usbd_mtp_start_write %d bytes", len);
    MTP_DUMP_SHELL(32, buf, len);

    g_usbd_mtp.tx_length = len;
    return usbd_ep_start_write(0, mtp_ep_data[MTP_IN_EP_IDX].ep_addr, buf, len);
}

/* 启动数据接收 */
int usbd_mtp_start_read(uint8_t *buf, uint32_t len)
{
    if (!usb_device_is_configured(0)) {
        return -1;
    }

    g_usbd_mtp.rx_buffer = buf;
    g_usbd_mtp.rx_length = 0;
    g_usbd_mtp.rx_total_length = len;
    return usbd_ep_start_read(0, mtp_ep_data[MTP_OUT_EP_IDX].ep_addr, buf, len);
}

/* 弱定义回调函数 */
void mtp_data_send_done(void)
{
    /* 可由用户重写 */
}

void mtp_data_recv_done(uint32_t len)
{
    /* 可由用户重写 */
}
