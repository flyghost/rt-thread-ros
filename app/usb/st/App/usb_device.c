/*
 * usb_device.c — USB Device 栈入口（本栈）
 *
 * 与 ST 上游例子（MX_USB_DEVICE_Init）的差别：
 *   1. Error_Handler() -> USB_ST_FAIL()（走 port 层）
 *   2. 进入前先调 usb_st_port_init()，让 port 层先备好信号量/环形缓冲
 *   3. id 用 USB_ST_DEVICE_ID（由 usb_st_config.h 的 USB_ST_USE_HS 推出）
 *   4. 增加 usb_st_start()/usb_st_is_ready() 供应用层查询，避免应用直接
 *      摸 hUsbDeviceHS
 */
#include "usb_device.h"
#include "../Core/usbd_core.h"   /* 必须写相对路径：CherryUSB 也有同名 usbd_core.h，裸文件名会被它抢走 */
#include "usbd_desc.h"
#include "usbd_cdc.h"
#include "usbd_cdc_if.h"
#include "usb_st_config.h"

USBD_HandleTypeDef hUsbDeviceHS;

static volatile uint8_t s_usb_st_ready = 0U;

void usb_st_init(void)
{
    usb_st_port_init();

    if (USBD_Init(&hUsbDeviceHS, &HS_Desc, USB_ST_DEVICE_ID) != USBD_OK)
    {
        usb_st_port_log("[usb_st] USBD_Init failed\r\n");
        USB_ST_FAIL();
    }
    if (USBD_RegisterClass(&hUsbDeviceHS, &USBD_CDC) != USBD_OK)
    {
        usb_st_port_log("[usb_st] USBD_RegisterClass failed\r\n");
        USB_ST_FAIL();
    }
    if (USBD_CDC_RegisterInterface(&hUsbDeviceHS, &USBD_Interface_fops_HS) != USBD_OK)
    {
        usb_st_port_log("[usb_st] USBD_CDC_RegisterInterface failed\r\n");
        USB_ST_FAIL();
    }
    if (USBD_Start(&hUsbDeviceHS) != USBD_OK)
    {
        usb_st_port_log("[usb_st] USBD_Start failed\r\n");
        USB_ST_FAIL();
    }

    s_usb_st_ready = 1U;
    usb_st_port_log("[usb_st] started (id=%u)\r\n", (unsigned)USB_ST_DEVICE_ID);
}

uint8_t usb_st_is_ready(void)
{
    return s_usb_st_ready;
}

/* USBD_Stop() -> USBD_LL_Stop() -> HAL_PCD_Stop()
 * USBD_DeInit() -> USBD_LL_DeInit() -> HAL_PCD_DeInit()
 * 两步合起来把控制器和 ST 库的内部状态都清干净，之后 usb_st_init() 可以重来一遍。 */
void usb_st_deinit(void)
{
    s_usb_st_ready = 0U;
    (void)USBD_Stop(&hUsbDeviceHS);
    (void)USBD_DeInit(&hUsbDeviceHS);
}

void usb_st_reinit(void)
{
    usb_st_port_log("[usb_st] re-init: deinit\r\n");
    usb_st_deinit();
    usb_st_port_log("[usb_st] re-init: init\r\n");
    usb_st_init();          /* 内部重新跑 usb_st_phy_reset() + HAL_PCD_Init + USBD_Start */
}

uint8_t usb_st_get_state(void)
{
    return (uint8_t)hUsbDeviceHS.dev_state;
}

USBD_HandleTypeDef *usb_st_handle(void)
{
    return &hUsbDeviceHS;
}
