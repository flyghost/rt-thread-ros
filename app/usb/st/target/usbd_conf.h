/*
 * usbd_conf.h — USB Device 库的编译期配置（移植自 ST 官方 HS VCP 例子）
 *
 * 与上游差别（仅此三处，其余逐字保留）：
 *   1. 去掉 #include "main.h"（CubeMX 那套），改指本栈的 usb_st_config.h
 *   2. USBD_UsrLog/ErrLog/DbgLog 改走 port 层，不再直接 printf
 *   3. USBD_Delay 仍映射到 HAL_Delay（BSP 的 drv_common.c 已实现）
 */
#ifndef __USBD_CONF__H__
#define __USBD_CONF__H__

#ifdef __cplusplus
 extern "C" {
#endif

/* Includes ------------------------------------------------------------------*/
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "stm32f4xx.h"
#include "stm32f4xx_hal.h"
#include "usb_st_config.h"

/*---------- -----------*/
#define USBD_MAX_NUM_INTERFACES         1U
/*---------- -----------*/
#define USBD_MAX_NUM_CONFIGURATION      1U
/*---------- -----------*/
#define USBD_MAX_STR_DESC_SIZ           512U
/*---------- -----------*/
#define USBD_DEBUG_LEVEL                0U
/*---------- -----------*/
#define USBD_LPM_ENABLED                0U
/*---------- -----------*/
#define USBD_SELF_POWERED               1U

/****************************************/
/* 控制器编号：与 ST 库的 pdev->id 比较用，数值必须保持 0/1 */
#define DEVICE_FS                       0
#define DEVICE_HS                       1

/* Memory management macros make sure to use static memory allocation */
#define USBD_malloc         (void *)USBD_static_malloc
#define USBD_free           USBD_static_free
#define USBD_memset         memset
#define USBD_memcpy         memcpy

/* Alias for delay. HAL_Delay 由 bsp/stm32/libraries/HAL_Drivers/drv_common.c:96 提供 */
#define USBD_Delay          HAL_Delay

/* DEBUG macros —— 全部走 port 层（port 实现按需丢弃，禁止在库里直接 printf） */
#define USBD_UsrLog(...)    usb_st_port_log(__VA_ARGS__)
#define USBD_ErrLog(...)    usb_st_port_log(__VA_ARGS__)
#define USBD_DbgLog(...)    usb_st_port_log(__VA_ARGS__)

/* Exported functions -------------------------------------------------------*/
void *USBD_static_malloc(uint32_t size);
void USBD_static_free(void *p);

#ifdef __cplusplus
}
#endif

#endif /* __USBD_CONF__H__ */
