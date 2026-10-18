/*
 * usbd_conf.c — ST USB Device 库 <-> HAL PCD 的适配层（本栈唯一的移植点）
 *
 * 来源：third-party/STM32F407_OTG_USB3300/01_Code/02_CubeMX生成代码/
 *       STM32F407_OTGHS_Device_VirtualPortCom_LoopBack/USB_DEVICE/Target/usbd_conf.c
 * 与上游差别：
 *   1. 删掉 HAL_PCD_MspInit / HAL_PCD_MspDeInit —— 引脚与时钟复用
 *      board/CubeMX_Config/Src/stm32f4xx_hal_msp.c 里已有的 USB_OTG_HS 分支
 *      （同文件已配好 12 根 ULPI 引脚 + OTG_HS/ULPI 时钟），避免重复定义。
 *   2. 新增 usb_st_phy_reset()：PE7 打一个高脉冲复位 USB3300（参考工程放在
 *      MX_USB_DEVICE_Init() 之前，这里放进 USBD_LL_Init() 开头，等价）。
 *   3. HAL_PCD_Init() 之后重设 OTG_HS 中断优先级（msp 里是 0,0，会抢占 SysTick）。
 *   4. Error_Handler() -> USB_ST_FAIL()（走 port 层，不再依赖 CubeMX 的 main.c）。
 *   5. FIFO 尺寸取自 usb_st_config.h，不再写死 0x200/0x80/0x174。
 */
#include "stm32f4xx.h"
#include "stm32f4xx_hal.h"
#include "usbd_def.h"
#include "../Core/usbd_core.h"   /* 必须写相对路径：CherryUSB 也有同名 usbd_core.h，裸文件名会被它抢走 */
#include "usbd_cdc.h"
#include "usb_st_config.h"
#include "usb_device.h"

/* ── 板级常量：USB3300 RESET 接 PE7，高电平有效 ─────────────────────────── */
#define USB_ST_PHY_RESET_PORT           GPIOE
#define USB_ST_PHY_RESET_PIN            GPIO_PIN_7

PCD_HandleTypeDef hpcd_USB_OTG_HS;

/* 前置声明（上游放在 USER CODE BEGIN PFP 段，这里保留等价位置） */
USBD_StatusTypeDef USBD_Get_USB_Status(HAL_StatusTypeDef hal_status);

/* ══ 板级：USH3300 复位脉冲 ══════════════════════════════════════════════ */
#if (USB_ST_PHY_RESET_ENABLE == 1)
static void usb_st_phy_reset(void)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    __HAL_RCC_GPIOE_CLK_ENABLE();

    GPIO_InitStruct.Pin   = USB_ST_PHY_RESET_PIN;
    GPIO_InitStruct.Mode  = GPIO_MODE_OUTPUT_PP;
    GPIO_InitStruct.Pull  = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
    HAL_GPIO_Init(USB_ST_PHY_RESET_PORT, &GPIO_InitStruct);

    /* 高 = 复位有效，保持一段后拉低释放（USB3300 数据手册要求 >= 1us，
     * 参考工程用空循环，这里保持一致，约 1~2ms @168MHz）             */
    HAL_GPIO_WritePin(USB_ST_PHY_RESET_PORT, USB_ST_PHY_RESET_PIN, GPIO_PIN_SET);
    for (volatile uint32_t i = 0; i < USB_ST_PHY_RESET_LOOPS; i++)
    {
        ;
    }
    HAL_GPIO_WritePin(USB_ST_PHY_RESET_PORT, USB_ST_PHY_RESET_PIN, GPIO_PIN_RESET);

    /* 释放后给 PHY 内部 PLL 稳定时间 */
    HAL_Delay(2);
}
#else
static void usb_st_phy_reset(void) { }
#endif

/* ══ LL Driver Callbacks (PCD -> USB Device Library) ═════════════════════ */
void HAL_PCD_SetupStageCallback(PCD_HandleTypeDef *hpcd)
{
    USBD_LL_SetupStage((USBD_HandleTypeDef *)hpcd->pData, (uint8_t *)hpcd->Setup);
}

void HAL_PCD_DataOutStageCallback(PCD_HandleTypeDef *hpcd, uint8_t epnum)
{
    USBD_LL_DataOutStage((USBD_HandleTypeDef *)hpcd->pData, epnum, hpcd->OUT_ep[epnum].xfer_buff);
}

void HAL_PCD_DataInStageCallback(PCD_HandleTypeDef *hpcd, uint8_t epnum)
{
    USBD_LL_DataInStage((USBD_HandleTypeDef *)hpcd->pData, epnum, hpcd->IN_ep[epnum].xfer_buff);
}

void HAL_PCD_SOFCallback(PCD_HandleTypeDef *hpcd)
{
    USBD_LL_SOF((USBD_HandleTypeDef *)hpcd->pData);
}

void HAL_PCD_ResetCallback(PCD_HandleTypeDef *hpcd)
{
    USBD_SpeedTypeDef speed = USBD_SPEED_FULL;

    if (hpcd->Init.speed == PCD_SPEED_HIGH)
    {
        speed = USBD_SPEED_HIGH;
    }
    else if (hpcd->Init.speed == PCD_SPEED_FULL)
    {
        speed = USBD_SPEED_FULL;
    }
    else
    {
        USB_ST_FAIL();
    }

    USBD_LL_SetSpeed((USBD_HandleTypeDef *)hpcd->pData, speed);
    USBD_LL_Reset((USBD_HandleTypeDef *)hpcd->pData);
}

void HAL_PCD_SuspendCallback(PCD_HandleTypeDef *hpcd)
{
    USBD_LL_Suspend((USBD_HandleTypeDef *)hpcd->pData);
    __HAL_PCD_GATE_PHYCLOCK(hpcd);
}

void HAL_PCD_ResumeCallback(PCD_HandleTypeDef *hpcd)
{
    USBD_LL_Resume((USBD_HandleTypeDef *)hpcd->pData);
}

void HAL_PCD_ISOOUTIncompleteCallback(PCD_HandleTypeDef *hpcd, uint8_t epnum)
{
    USBD_LL_IsoOUTIncomplete((USBD_HandleTypeDef *)hpcd->pData, epnum);
}

void HAL_PCD_ISOINIncompleteCallback(PCD_HandleTypeDef *hpcd, uint8_t epnum)
{
    USBD_LL_IsoINIncomplete((USBD_HandleTypeDef *)hpcd->pData, epnum);
}

void HAL_PCD_ConnectCallback(PCD_HandleTypeDef *hpcd)
{
    USBD_LL_DevConnected((USBD_HandleTypeDef *)hpcd->pData);
}

void HAL_PCD_DisconnectCallback(PCD_HandleTypeDef *hpcd)
{
    USBD_LL_DevDisconnected((USBD_HandleTypeDef *)hpcd->pData);
}

/* ══ 中断入口 ════════════════════════════════════════════════════════════ */
/* 注意：本仓 board/SConscript 只编译 board.c / stm32f4xx_hal_msp.c /
 * ramdump_handlers.c，CubeMX 的 stm32f4xx_it.c 不参与编译，所以 OTG_HS_IRQHandler
 * 必须由本栈自己提供，否则中断落到启动文件的 Default_Handler 里死循环。 */
void OTG_HS_IRQHandler(void)
{
    HAL_PCD_IRQHandler(&hpcd_USB_OTG_HS);
}

/* ══ LL Driver Interface (USB Device Library --> PCD) ════════════════════ */
USBD_StatusTypeDef USBD_LL_Init(USBD_HandleTypeDef *pdev)
{
    if (pdev->id == USB_ST_DEVICE_ID)
    {
        /* 复位 PHY 必须早于 HAL_PCD_Init()（ULPI 训练依赖 PHY 已退出复位） */
        usb_st_phy_reset();

        hpcd_USB_OTG_HS.pData = pdev;
        pdev->pData = &hpcd_USB_OTG_HS;

        hpcd_USB_OTG_HS.Instance                 = USB_OTG_HS;
        hpcd_USB_OTG_HS.Init.dev_endpoints       = USB_ST_DEV_ENDPOINTS;
#if (USB_ST_USE_HS == 1)
        hpcd_USB_OTG_HS.Init.speed               = PCD_SPEED_HIGH;
        hpcd_USB_OTG_HS.Init.phy_itface          = USB_OTG_ULPI_PHY;
#else
        hpcd_USB_OTG_HS.Init.speed               = PCD_SPEED_FULL;
        hpcd_USB_OTG_HS.Init.phy_itface          = PCD_PHY_EMBEDDED;
#endif
        hpcd_USB_OTG_HS.Init.dma_enable          = DISABLE;   /* FS/HS slave 模式，不用 DMA */
        hpcd_USB_OTG_HS.Init.Sof_enable          = DISABLE;
        hpcd_USB_OTG_HS.Init.low_power_enable    = DISABLE;
        hpcd_USB_OTG_HS.Init.lpm_enable          = DISABLE;
        hpcd_USB_OTG_HS.Init.vbus_sensing_enable = DISABLE;   /* 本板 VBUS 检测未接 */
        hpcd_USB_OTG_HS.Init.use_dedicated_ep1   = DISABLE;
        hpcd_USB_OTG_HS.Init.use_external_vbus   = DISABLE;

        if (HAL_PCD_Init(&hpcd_USB_OTG_HS) != HAL_OK)
        {
            usb_st_port_log("[usb_st] HAL_PCD_Init FAILED\r\n");
            USB_ST_FAIL();
            return USBD_FAIL;
        }

        /* msp 里给的是 0,0（最高优先级，会抢 SysTick），这里覆盖成可配置值 */
        HAL_NVIC_SetPriority(OTG_HS_IRQn, USB_ST_IRQ_PRIORITY, USB_ST_IRQ_SUBPRIORITY);

        HAL_PCDEx_SetRxFiFo(&hpcd_USB_OTG_HS, USB_ST_RX_FIFO_WORDS);
        HAL_PCDEx_SetTxFiFo(&hpcd_USB_OTG_HS, 0, USB_ST_TX0_FIFO_WORDS);
        HAL_PCDEx_SetTxFiFo(&hpcd_USB_OTG_HS, 1, USB_ST_TX1_FIFO_WORDS);

        usb_st_port_log("[usb_st] PCD init ok: id=%u speed=%u fifo=%u+%u+%u words\r\n",
                        (unsigned)pdev->id,
                        (unsigned)hpcd_USB_OTG_HS.Init.speed,
                        (unsigned)USB_ST_RX_FIFO_WORDS,
                        (unsigned)USB_ST_TX0_FIFO_WORDS,
                        (unsigned)USB_ST_TX1_FIFO_WORDS);
    }
    return USBD_OK;
}

USBD_StatusTypeDef USBD_LL_DeInit(USBD_HandleTypeDef *pdev)
{
    return USBD_Get_USB_Status(HAL_PCD_DeInit(pdev->pData));
}

USBD_StatusTypeDef USBD_LL_Start(USBD_HandleTypeDef *pdev)
{
    return USBD_Get_USB_Status(HAL_PCD_Start(pdev->pData));
}

USBD_StatusTypeDef USBD_LL_Stop(USBD_HandleTypeDef *pdev)
{
    return USBD_Get_USB_Status(HAL_PCD_Stop(pdev->pData));
}

USBD_StatusTypeDef USBD_LL_OpenEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr, uint8_t ep_type, uint16_t ep_mps)
{
    return USBD_Get_USB_Status(HAL_PCD_EP_Open(pdev->pData, ep_addr, ep_mps, ep_type));
}

USBD_StatusTypeDef USBD_LL_CloseEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr)
{
    return USBD_Get_USB_Status(HAL_PCD_EP_Close(pdev->pData, ep_addr));
}

USBD_StatusTypeDef USBD_LL_FlushEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr)
{
    return USBD_Get_USB_Status(HAL_PCD_EP_Flush(pdev->pData, ep_addr));
}

USBD_StatusTypeDef USBD_LL_StallEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr)
{
    return USBD_Get_USB_Status(HAL_PCD_EP_SetStall(pdev->pData, ep_addr));
}

USBD_StatusTypeDef USBD_LL_ClearStallEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr)
{
    return USBD_Get_USB_Status(HAL_PCD_EP_ClrStall(pdev->pData, ep_addr));
}

uint8_t USBD_LL_IsStallEP(USBD_HandleTypeDef *pdev, uint8_t ep_addr)
{
    PCD_HandleTypeDef *hpcd = (PCD_HandleTypeDef *)pdev->pData;

    if ((ep_addr & 0x80U) == 0x80U)
    {
        return hpcd->IN_ep[ep_addr & 0x7FU].is_stall;
    }
    return hpcd->OUT_ep[ep_addr & 0x7FU].is_stall;
}

USBD_StatusTypeDef USBD_LL_SetUSBAddress(USBD_HandleTypeDef *pdev, uint8_t dev_addr)
{
    return USBD_Get_USB_Status(HAL_PCD_SetAddress(pdev->pData, dev_addr));
}

USBD_StatusTypeDef USBD_LL_Transmit(USBD_HandleTypeDef *pdev, uint8_t ep_addr, uint8_t *pbuf, uint32_t size)
{
    return USBD_Get_USB_Status(HAL_PCD_EP_Transmit(pdev->pData, ep_addr, pbuf, size));
}

USBD_StatusTypeDef USBD_LL_PrepareReceive(USBD_HandleTypeDef *pdev, uint8_t ep_addr, uint8_t *pbuf, uint32_t size)
{
    return USBD_Get_USB_Status(HAL_PCD_EP_Receive(pdev->pData, ep_addr, pbuf, size));
}

uint32_t USBD_LL_GetRxDataSize(USBD_HandleTypeDef *pdev, uint8_t ep_addr)
{
    return HAL_PCD_EP_GetRxCount((PCD_HandleTypeDef *)pdev->pData, ep_addr);
}

/* ══ 库内部工具 ══════════════════════════════════════════════════════════ */
void *USBD_static_malloc(uint32_t size)
{
    static uint32_t mem[(sizeof(USBD_CDC_HandleTypeDef) / 4U) + 1U]; /* 32-bit 对齐 */
    (void)size;
    return mem;
}

void USBD_static_free(void *p)
{
    (void)p;
}

void USBD_LL_Delay(uint32_t Delay)
{
    usb_st_port_delay_ms(Delay);
}

USBD_StatusTypeDef USBD_Get_USB_Status(HAL_StatusTypeDef hal_status)
{
    USBD_StatusTypeDef usb_status = USBD_OK;

    switch (hal_status)
    {
    case HAL_OK:      usb_status = USBD_OK;   break;
    case HAL_ERROR:   usb_status = USBD_FAIL; break;
    case HAL_BUSY:    usb_status = USBD_BUSY; break;
    case HAL_TIMEOUT: usb_status = USBD_FAIL; break;
    default:          usb_status = USBD_FAIL; break;
    }
    return usb_status;
}

