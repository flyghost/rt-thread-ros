/*
 * usb_st_config.h — ST USB Device 栈（app/usb/st）的全部编译期配置
 *
 * 这个头是本栈唯一的「旋钮面板」：换控制器、改 FIFO、改中断优先级、关调试
 * 输出，都只动这里，不改 ST 原始文件（Core/ 与 Class/ 是逐字节复制，别动）。
 *
 * 依赖方向：usb_st_config.h -> usb_st_port.h（只声明，不 include 任何 OS 头）
 *          本文件不得 include stm32f4xx*.h，以免和 HAL 的 include 顺序互相绑死。
 */
#ifndef __USB_ST_CONFIG_H__
#define __USB_ST_CONFIG_H__

/* ══ 1. 控制器 ══════════════════════════════════════════════════════════ */
/* 1 = OTG_HS + ULPI 外置 PHY（USB3300，本板高速口）
 * 0 = OTG_FS 内置 PHY（PA11/PA12）—— 本板 FS 口已被 cherryusb 轮询版占用，
 *     两者不能同时开，见 app/usb/README.md                     */
#define USB_ST_USE_HS                   1

/* 传给 USBD_Init() 的 id，并与 pdev->id 比较。DEVICE_FS/DEVICE_HS 由
 * usbd_conf.h 定义（0/1），此处延迟展开，所以不构成循环依赖。        */
#define USB_ST_DEVICE_ID                (USB_ST_USE_HS ? DEVICE_HS : DEVICE_FS)

/* ══ 2. FIFO 预算（单位：32-bit word）════════════════════════════════════ */
/* OTG_HS 共 1024 word，内部 DMA 描述符占 12 word，可用 1012 word。
 * 与 ST 官方 HS VCP 例子逐项一致（HAL_PCDEx_SetRxFiFo/SetTxFiFo 的入参）。
 *   512 + 128 + 372 = 1012                                             */
#define USB_ST_RX_FIFO_WORDS            512U    /* 2048 B  所有 OUT 端点共享 */
#define USB_ST_TX0_FIFO_WORDS           128U    /*  512 B  EP0               */
#define USB_ST_TX1_FIFO_WORDS           372U    /* 1488 B  EP1 IN (CDC)      */

#define USB_ST_FIFO_TOTAL_WORDS \
    (USB_ST_RX_FIFO_WORDS + USB_ST_TX0_FIFO_WORDS + USB_ST_TX1_FIFO_WORDS)

#if (USB_ST_FIFO_TOTAL_WORDS > 1012U)
#error "USB_ST FIFO 超预算：OTG_HS 可用 1012 word（1024 - 12 内部 DMA）"
#endif

/* ══ 3. 端点 ════════════════════════════════════════════════════════════ */
#define USB_ST_DEV_ENDPOINTS            6U      /* 设备模式最大端点数（HS 为 6） */

/* ══ 4. CDC 应用缓冲（一次传输上限，字节）══════════════════════════════════ */
#define APP_RX_DATA_SIZE                2048U
#define APP_TX_DATA_SIZE                2048U

/* ══ 5. 中断优先级 ══════════════════════════════════════════════════════ */
/* 不要用 0：OTG_HS 中断里会调用 port 层的 rx 投递（可能触发 rt_sem_release
 * 一类内核 API），优先级应低于 SysTick，避免抢占内核临界区。          */
#define USB_ST_IRQ_PRIORITY             5U
#define USB_ST_IRQ_SUBPRIORITY          0U

/* ══ 6. 板级：USB3300 RESET（PE7，高电平有效，拉低=释放）═════════════════ */
/* 原理图网络名 ULPI_RESETB；参考工程在 MX_USB_DEVICE_Init() 之前打一个
 * 高脉冲再拉低。放到 USBD_LL_Init() 里做，等价且不依赖应用层顺序。      */
#define USB_ST_PHY_RESET_ENABLE         1
#define USB_ST_PHY_RESET_LOOPS          0xFFFFU /* 空循环延时（168MHz 下约 1~2 ms）*/

/* ══ 7. 调试输出 ════════════════════════════════════════════════════════ */
/* 0 = 静默（默认）；1 = 打印枚举/端点事件。走 port 层，不在库内部直接 printf */
#define USB_ST_DEBUG_LEVEL              1

/* 回环自测：1 = 把 PC 发来的数据原样发回（bring-up 验证用）；
 * 0 = 只收不环，数据留在 port 环形缓冲里等业务取。                    */
#define USB_ST_ECHO_ENABLE              1

/* ══ 8. 依赖 port 契约（只有声明）══════════════════════════════════════════ */
#include "usb_st_port.h"

/* 库内部致命错误 → 交给 port 决定怎么处理（这里只打印+停住，不 HardFault）*/
#define USB_ST_FAIL()                   usb_st_port_fatal(__FILE__, __LINE__)

#endif /* __USB_ST_CONFIG_H__ */
