/*
 * usbd_cdc_if.h — CDC 类应用接口（本栈）
 * 上游同名文件只声明 USBD_Interface_fops_HS；这里补上 CDC_Transmit_HS 原型
 * 与接收/发送缓冲尺寸（尺寸来自 usb_st_config.h）。
 */
#ifndef __USBD_CDC_IF_H__
#define __USBD_CDC_IF_H__

#ifdef __cplusplus
 extern "C" {
#endif

#include "usbd_cdc.h"
#include "usb_st_config.h"

extern USBD_CDC_ItfTypeDef USBD_Interface_fops_HS;

/* 供 port 层/应用层调用：把 len 字节发到 CDC IN 端点。
 * 返回 USBD_OK / USBD_BUSY（上一包未发完，调用方需重试）/ USBD_FAIL。 */
uint8_t CDC_Transmit_HS(uint8_t *Buf, uint16_t Len);

#ifdef __cplusplus
}
#endif

#endif /* __USBD_CDC_IF_H__ */
