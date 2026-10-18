# app/usb — 两套 USB 设备栈

同一块板子上跑两套栈，**按控制器分工**，互不干扰：

| 目录 | 栈 | 控制器 / PHY | 工作方式 | 用途 |
|---|---|---|---|---|
| `cherryusb/` | CherryUSB（裁剪版，上游原样） | OTG_FS + 内置 FS PHY（PA11/PA12） | 轮询（中断在 NVIC 关掉） | ramdump 的 USB CDC 通道；HardFault 上下文也能用 |
| `st/` | ST 官方 USB Device 库（HAL 版） | OTG_HS + ULPI（USB3300，PE7 复位） | 中断 | 正常运行态的高速 CDC（480 Mbps 链路，实测 ~1.1 MB/s 回环） |

两套栈的对外符号没有交集（`usbd_initialize/usbd_add_interface` vs `USBD_Init/USBD_RegisterClass`），
可以同时编进固件。

## 开关

`Kconfig` 里两个**独立** bool（不是 choice，因为分控制器可以同时开）：

```c
#define USB_USE_CHERRYUSB   /* 编 app/usb/cherryusb 的三个 .c */
#define USB_USE_ST          /* 编 app/usb/st，并 select USB_HAL_PCD */
```

`USB_HAL_PCD` 是隐藏项：把 `bsp/stm32/libraries/STM32F4xx_HAL/STM32F4xx_HAL_Driver/Src/`
里的 `stm32f4xx_hal_pcd.c` / `stm32f4xx_hal_pcd_ex.c` / `stm32f4xx_ll_usb.c` 拉进构建
（这棵 HAL 树是被裁剪过的，默认没有 PCD；也**不要**用 `RT_USING_USB`，那还会拉
hal_hcd/hal_pccard）。当前值在 BSP 的 `rtconfig.h` 里。

## 配置放哪

| 栈 | 配置头 | 内容 |
|---|---|---|
| CherryUSB | `cherryusb/common/usb_config.h` | FIFO、`CONFIG_USB_PRINTF`（→ ramdump 的 printf）、`CONFIG_USBDEV_ADVANCE_DESC`、`CONFIG_USBDEV_DWC2_ST` |
| ST | `st/usb_st_config.h` | HS/FS 选择、FIFO 字数、中断优先级、PE7 复位、回环开关 |

**同名头文件的坑（已修）**：仓库里曾有第二份 `usb_config.h` 在
`bsp/stm32/stm32f407-atk-explorer/board/`。GCC 的 `#include "usb_config.h"` 按 CPPPATH
顺序解析，`board/` 排在栈目录之前，于是 CherryUSB 一直用的是 BSP 那份（`CONFIG_USB_PRINTF`
指向 `rt_kprintf`，掉电/HardFault 场景会死）。现在那份已改名
`usb_config.h.bsp-disabled`，全仓只剩 `cherryusb/common/usb_config.h` 一份。

## 分层规矩

- `st/target/usbd_conf.c` 是唯一碰 HAL 的地方；`st/Core`、`st/CDC` 是 ST 原样文件。
- `st/port/` 是唯一碰 OS 的地方（`usb_st_port.h` 只有声明）。`cherryusb/` 不 include
  任何 `rtthread.h`，OS 能力靠宏注入。
- 两套栈的 port 符号各自带前缀，不抽公共层（需求不一样：CherryUSB 要零 OS，ST 要信号量唤醒）。

## msh 命令

| 命令 | 作用 |
|---|---|
| `usb_st` | ST 栈状态与计数（ready / dev_state / rx / tx / dropped / tx_busy） |
| `usb_reinit` | 重新枚举：停栈 → PHY 硬件复位 → 重新 init。拔插 USB 线后跑这条，不用复位整板 |
| `reboot` | 整板复位（RT-Thread 自带） |
