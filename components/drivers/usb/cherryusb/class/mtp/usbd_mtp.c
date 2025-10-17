#include "usbd_mtp_config.h"
#include "usbd_core.h"
#include "usbd_mtp.h"
#include "usb_mtp.h"
#include "mtp_operation.h"
#include <string.h>

#define USBD_MTP_DEBUG    0

#ifdef CONFIG_USBDEV_MTP_THREAD
#define USBD_MTP_USING_THREAD
#endif

/* 端点配置 */
#define MTP_OUT_EP_IDX 0
#define MTP_IN_EP_IDX  1
#define MTP_INT_EP_IDX 2

/* 端点描述符 */
static struct usbd_endpoint mtp_ep_data[3];

/* MTP 全局状态 */
struct usbd_mtp_priv g_usbd_mtp;


static usb_osal_thread_t g_usbd_mtp_thread = NULL;
static usb_osal_mq_t g_usbd_mtp_mq = NULL;
static usb_osal_mutex_t g_usbd_mtp_tx_mutex = NULL;

enum {
    MTP_MSG_SEND_DONE = 0,
    MTP_MSG_RECEIVE_DONE,
};

/* 非缓存缓冲区 */
USB_NOCACHE_RAM_SECTION USB_MEM_ALIGNX uint8_t mtp_rx_buffer[MTP_BUFFER_SIZE];
USB_NOCACHE_RAM_SECTION USB_MEM_ALIGNX uint8_t mtp_tx_buffer[MTP_BUFFER_SIZE];
USB_NOCACHE_RAM_SECTION USB_MEM_ALIGNX uint8_t mtp_int_buffer[100];

void mtp_tx_lock(void)
{
    if (g_usbd_mtp_tx_mutex) {
        if (usb_osal_mutex_take(g_usbd_mtp_tx_mutex) != 0) {
            MTP_LOGE_SHELL("Failed to lock MTP TX mutex");
        }
    }
}

static void mtp_tx_unlock(void)
{
    if (g_usbd_mtp_tx_mutex) {
        if (usb_osal_mutex_give(g_usbd_mtp_tx_mutex) != 0) {
            MTP_LOGE_SHELL("Failed to unlock MTP TX mutex");
        }
    }
}

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
            usbd_mtp_start_read(mtp_rx_buffer, MTP_BUFFER_SIZE);
            break;
            
        default:
            break;
    }
}

static void mtp_bulk_out_done(void)
{
    /* 完整数据包接收完成，处理命令 */
    mtp_command_handler(g_usbd_mtp.rx_buffer, g_usbd_mtp.rx_length);
    
    /* 重置接收状态 */
    g_usbd_mtp.rx_length = 0;
    g_usbd_mtp.rx_total_length = 0;

    usbd_mtp_start_read(mtp_rx_buffer, MTP_BUFFER_SIZE);
}

/* 批量输出端点回调（接收主机数据） */
void mtp_bulk_out(uint8_t busid, uint8_t ep, uint32_t nbytes)
{
    (void)busid;
    (void)ep;

#if USBD_MTP_DEBUG
    MTP_LOGD_SHELL("receive %d bytes", nbytes);
    MTP_DUMP_SHELL(16, g_usbd_mtp.rx_buffer, nbytes);
#endif

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

#ifdef USBD_MTP_USING_THREAD
    if (usb_osal_mq_send(g_usbd_mtp_mq, (uintptr_t)MTP_MSG_RECEIVE_DONE)) {
        MTP_LOGE_SHELL("Failed to send MTP message to queue");
        g_usbd_mtp.rx_length = 0;
        g_usbd_mtp.rx_total_length = 0;
        usbd_mtp_start_read(mtp_rx_buffer, MTP_BUFFER_SIZE);
        return;
    }
#else
    mtp_bulk_out_done();
#endif
}

/* 批量输入端点回调（发送数据到主机） */
void mtp_bulk_in(uint8_t busid, uint8_t ep, uint32_t nbytes)
{
    (void)busid;
    (void)ep;
    (void)nbytes;

#if USBD_MTP_DEBUG
    MTP_LOGD_SHELL("send %d bytes ok", nbytes);
#endif

    if (g_usbd_mtp.tx_length > 0) {
        g_usbd_mtp.tx_length = 0;
    
    #ifdef USBD_MTP_USING_THREAD
        if (usb_osal_mq_send(g_usbd_mtp_mq, (uintptr_t)MTP_MSG_SEND_DONE)) {
            MTP_LOGE_SHELL("Failed to send MTP message to queue");
            return;
        }
    #else
        mtp_data_send_done();
    #endif
    }
    else {
        MTP_LOGE_SHELL("No data to send, tx_length is zero");
    }
}

/* 中断端点回调 */
void mtp_int_in(uint8_t busid, uint8_t ep, uint32_t nbytes)
{
    (void)busid;
    (void)ep;
    (void)nbytes;
}

static int handle_cancel_request(struct usb_setup_packet *setup, 
                                uint8_t **data, uint32_t *len) 
{
    // 协议要求：清空所有进行中的传输
    // g_usbd_mtp.rx_length = 0;
    // g_usbd_mtp.tx_length = 0;
    // g_usbd_mtp.cur_object = NULL;
    
    // 返回空响应（Windows要求）
    *len = 0;
    return 0;
}

static int handle_get_event_data(struct usb_setup_packet *setup,
                                 uint8_t **data, uint32_t *len)
{
    // static uint8_t event_buffer[64]; // 事件缓冲区
    
    // if (g_usbd_mtp.event_pending) {
    //     // 返回待处理事件（示例：存储设备插入）
    //     memcpy(event_buffer, &g_usbd_mtp.pending_event, sizeof(g_usbd_mtp.pending_event));
        
    //     *data = event_buffer;
    //     *len = sizeof(struct MtpEvent);
    //     g_usbd_mtp.event_pending = false;
    // } else {
        // 无事件时返回空
        *len = 0;
    // }
    return 0;
}

static int handle_reset_request(struct usb_setup_packet *setup,
                               uint8_t **data, uint32_t *len) 
{
    // 协议要求：重置所有状态
    // g_usbd_mtp.session_id = 0;
    // g_usbd_mtp.session_open = false;
    // g_usbd_mtp.trans_id = 0;
    
    // // 清空对象传输状态
    // memset(&g_usbd_mtp.transfer, 0, sizeof(g_usbd_mtp.transfer));
    
    // 返回空响应
    *len = 0;
    return 0;
}

static int handle_get_status(struct usb_setup_packet *setup,
                            uint8_t **data, uint32_t *len) 
{
    static struct {
        uint16_t status_code;
        uint32_t session_id;
        uint32_t trans_id;
        uint8_t  reserved[24];  // 确保总共36字节
    } status = {0};
    
    // 填充状态信息
    status.status_code = MTP_RESPONSE_OK;
    status.session_id = g_usbd_mtp.session_id;
    // 操作完成后，事务ID应该清零
    status.trans_id = 0;
    memset(status.reserved, 0, sizeof(status.reserved));
    
    // Windows要求固定返回36字节
    *data = (uint8_t*)&status;
    *len = sizeof(status);
    
    MTP_LOGD_SHELL("GET_STATUS: status=0x%04X, session=0x%08X, trans=0x%08X", 
                   status.status_code, status.session_id, status.trans_id);
    
    return 0;
}

/* MTP 类接口请求处理 */
static int mtp_class_interface_request_handler(uint8_t busid, struct usb_setup_packet *setup, uint8_t **data, uint32_t *len)
{
    (void)busid;

    MTP_LOGE_SHELL("MTP class interface request: bRequest = 0x%02x, wValue = 0x%04x, wIndex = 0x%04x, wLength = %d",
             setup->bRequest, setup->wValue, setup->wIndex, setup->wLength);
    
    switch (setup->bRequest) {
        case MTP_REQUEST_CANCEL:
            return handle_cancel_request(setup, data, len);
            
        case MTP_REQUEST_GET_EXT_EVENT_DATA:
            return handle_get_event_data(setup, data, len);
            
        case MTP_REQUEST_RESET:
            return handle_reset_request(setup, data, len);
            
        case MTP_REQUEST_GET_DEVICE_STATUS:
            return handle_get_status(setup, data, len);
            
        default:
            MTP_LOGE_SHELL("Unsupported request: 0x%02X", setup->bRequest);
            return -1;
    }
    return -1;
}

static void usbd_mtp_thread(void *argv)
{
    (void)argv;

    uintptr_t event;
    int ret = 0;

    while (1) {
        ret = usb_osal_mq_recv(g_usbd_mtp_mq, (uintptr_t *)&event, USB_OSAL_WAITING_FOREVER);
        if (ret) {
            MTP_LOGE_SHELL("Failed to receive message from MTP queue: %d", ret);
            continue;
        }
    #if USBD_MTP_DEBUG
        MTP_LOGD_SHELL("Received event: %d", event);
    #endif

        switch (event) {
            case MTP_MSG_SEND_DONE:
            #if USBD_MTP_DEBUG
                MTP_LOGD_SHELL("MTP_MSG_SEND_DONE");
            #endif
                // mtp_tx_unlock();
                mtp_data_send_done();
                break;

            case MTP_MSG_RECEIVE_DONE:
            #if USBD_MTP_DEBUG
                MTP_LOGD_SHELL("MTP_MSG_RECEIVE_DONE");
            #endif
                mtp_bulk_out_done();
                break;

            default:
                MTP_LOGE_SHELL("Unknown message type: %d", event);
                break;
        }
    }
}

/* 初始化 MTP 接口 */
struct usbd_interface *usbd_mtp_init_intf(struct usbd_interface *intf,
                                         const uint8_t out_ep,
                                         const uint8_t in_ep,
                                         const uint8_t int_ep)
{
    g_usbd_mtp_mq = usb_osal_mq_create(7);
    if (g_usbd_mtp_mq == NULL) {
        MTP_LOGE_SHELL("Failed to create mtp mq");
        return NULL;
    }

    if (g_usbd_mtp_thread == NULL) {
        g_usbd_mtp_thread = usb_osal_thread_create("usbd_mtp", 2048, 10, usbd_mtp_thread, NULL);
        if (g_usbd_mtp_thread == NULL) {
            MTP_LOGE_SHELL("Failed to create MTP thread");
            return NULL;
        }
    }

    if (g_usbd_mtp_tx_mutex == NULL) {
        g_usbd_mtp_tx_mutex = usb_osal_mutex_create();
        if (g_usbd_mtp_tx_mutex == NULL) {
            MTP_LOGE_SHELL("Failed to create MTP TX mutex");
            return NULL;
        }
    }

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
        MTP_LOGE_SHELL("USB device not configured, cannot start write");
        return -1;
    }

    if (g_usbd_mtp.tx_length > 0) {
        MTP_LOGE_SHELL("Previous write not completed, cannot start new write");
        return -1; /* 上次发送未完成 */
    }

#if USBD_MTP_DEBUG
    MTP_LOGD_SHELL("usbd_mtp_start_write %d bytes", len);
    MTP_DUMP_SHELL(16, buf, len);
#endif

    g_usbd_mtp.tx_length = len;
    return usbd_ep_start_write(0, mtp_ep_data[MTP_IN_EP_IDX].ep_addr, buf, len);
}

/* 启动数据接收 */
int usbd_mtp_start_read(uint8_t *buf, uint32_t len)
{
    int ret;
    if (!usb_device_is_configured(0)) {
        MTP_LOGE_SHELL("USB device not configured, cannot start read");
        return -1;
    }

    g_usbd_mtp.rx_buffer = buf;
    g_usbd_mtp.rx_length = 0;
    g_usbd_mtp.rx_total_length = len;
    ret = usbd_ep_start_read(0, mtp_ep_data[MTP_OUT_EP_IDX].ep_addr, buf, len);
    if (ret) {
        MTP_LOGE_SHELL("Failed to start read : %d", ret);
        return ret;
    }

    return 0;
}

/* 弱定义回调函数 */
__WEAK void mtp_data_send_done(void)
{
    /* 可由用户重写 */
}

__WEAK void mtp_data_recv_done(uint32_t len)
{
    /* 可由用户重写 */
}
