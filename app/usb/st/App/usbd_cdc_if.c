/*
 * usbd_cdc_if.c — CDC 类应用回调（本栈）
 *
 * 与 ST 上游例子的差别：
 *   1. CDC_Receive_HS 不再"回环发送"（上游是 VCP_LoopBack 示例，直接把收到的
 *      包发回去）。这里改成投递到 port 层的环形缓冲，由 port 决定怎么处理
 *      （回环 / 协议解析 / 落盘），库本身不掺业务。
 *   2. USER CODE 段的注释全部去掉，保留纯逻辑，便于和上游 diff。
 */
#include "usbd_cdc_if.h"
#include "usb_st_config.h"

/* 接收/发送缓冲（尺寸见 usb_st_config.h 的 APP_RX_DATA_SIZE/APP_TX_DATA_SIZE） */
uint8_t UserRxBufferHS[APP_RX_DATA_SIZE];
uint8_t UserTxBufferHS[APP_TX_DATA_SIZE];

static int8_t CDC_Init_HS(void);
static int8_t CDC_DeInit_HS(void);
static int8_t CDC_Control_HS(uint8_t cmd, uint8_t *pbuf, uint16_t length);
static int8_t CDC_Receive_HS(uint8_t *pbuf, uint32_t *Len);
static int8_t CDC_TransmitCplt_HS(uint8_t *pbuf, uint32_t *Len, uint8_t epnum);

extern USBD_HandleTypeDef hUsbDeviceHS;

USBD_CDC_ItfTypeDef USBD_Interface_fops_HS =
{
    CDC_Init_HS,
    CDC_DeInit_HS,
    CDC_Control_HS,
    CDC_Receive_HS,
    CDC_TransmitCplt_HS
};

static int8_t CDC_Init_HS(void)
{
    USBD_CDC_SetTxBuffer(&hUsbDeviceHS, UserTxBufferHS, 0);
    USBD_CDC_SetRxBuffer(&hUsbDeviceHS, UserRxBufferHS);
    return (USBD_OK);
}

static int8_t CDC_DeInit_HS(void)
{
    return (USBD_OK);
}

static int8_t CDC_Control_HS(uint8_t cmd, uint8_t *pbuf, uint16_t length)
{
    (void)pbuf;
    (void)length;

    /* CDC 类请求（SET_LINE_CODING 等）本栈一律接受，波特率对 USB 无意义 */
    switch (cmd)
    {
    case CDC_SEND_ENCAPSULATED_COMMAND:
    case CDC_GET_ENCAPSULATED_RESPONSE:
    case CDC_SET_COMM_FEATURE:
    case CDC_GET_COMM_FEATURE:
    case CDC_CLEAR_COMM_FEATURE:
    case CDC_SET_LINE_CODING:
    case CDC_GET_LINE_CODING:
    case CDC_SET_CONTROL_LINE_STATE:
    case CDC_SEND_BREAK:
    default:
        break;
    }
    return (USBD_OK);
}

/* OUT 端点收到一包（中断上下文）：投递到 port，然后重新挂接收 */
static int8_t CDC_Receive_HS(uint8_t *Buf, uint32_t *Len)
{
    usb_st_port_rx_push(Buf, *Len);

    USBD_CDC_SetRxBuffer(&hUsbDeviceHS, &Buf[0]);
    USBD_CDC_ReceivePacket(&hUsbDeviceHS);

    return (USBD_OK);
}

uint8_t CDC_Transmit_HS(uint8_t *Buf, uint16_t Len)
{
    USBD_CDC_HandleTypeDef *hcdc = (USBD_CDC_HandleTypeDef *)hUsbDeviceHS.pClassData;

    if (hcdc == NULL)
    {
        return USBD_FAIL;
    }

    if (hcdc->TxState != 0U)
    {
        return USBD_BUSY;
    }

    USBD_CDC_SetTxBuffer(&hUsbDeviceHS, Buf, Len);
    return USBD_CDC_TransmitPacket(&hUsbDeviceHS);
}

static int8_t CDC_TransmitCplt_HS(uint8_t *Buf, uint32_t *Len, uint8_t epnum)
{
    (void)Buf;
    (void)Len;
    (void)epnum;
    return (USBD_OK);
}
