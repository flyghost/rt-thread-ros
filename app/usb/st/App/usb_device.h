/*
 * usb_device.h — USB Device 栈入口（本栈）
 * 上游声明 MX_USB_DEVICE_Init() 与 hUsbDeviceHS；这里改名 usb_st_init()，
 * 并补两个查询接口，让应用层不必直接引用 hUsbDeviceHS。
 */
#ifndef __USB_DEVICE_H__
#define __USB_DEVICE_H__

#ifdef __cplusplus
 extern "C" {
#endif

#include "stm32f4xx.h"
#include "stm32f4xx_hal.h"
#include "usbd_def.h"

extern USBD_HandleTypeDef hUsbDeviceHS;

/* 初始化并启动 CDC 设备（内部会先调 usb_st_port_init()）。
 * 调用时机：调度器启动后、中断已开。重复调用无副作用（返回前一次的结果）。 */
void usb_st_init(void);

/* 关掉 USB 控制器并释放 ST 库内部资源（不重新枚举） */
void usb_st_deinit(void);

/* 重新枚举：deinit + PHY 硬件复位 + init。
 * 用途：拔插 USB 线后 PHY 不会自己重新上拉，跑一次本函数即可让主机重新枚举，
 * 不用给 MCU 复位。调用方需保证此时没有正在进行的发送（port 层会先停回环线程）。 */
void usb_st_reinit(void);

/* 1 = USBD_Start() 已成功返回 */
uint8_t usb_st_is_ready(void);

/* USBD 状态机当前状态（USBD_STATE_* 的数值，联调看它就知道枚举到哪一步） */
uint8_t usb_st_get_state(void);

/* 逃生口：需要直接操作 ST 库时用（例如 USBD_CDC_SetTxBuffer） */
USBD_HandleTypeDef *usb_st_handle(void);

#ifdef __cplusplus
}
#endif

#endif /* __USB_DEVICE_H__ */
