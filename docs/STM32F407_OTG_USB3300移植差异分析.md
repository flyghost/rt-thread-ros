# STM32F407_OTG_USB3300 板卡移植差异分析

> **文档性质**：差异分析 + 移植方案（本文不含已落地的代码改动）
> **结论对象**：本工作区 `bsp/stm32/stm32f407-atk-explorer` + `app/ramdump/transport/usb`
> **依据资料**：`third-party/STM32F407_OTG_USB3300/`（官方原始资料，未做任何修改）
> **核对方式**：源码静态阅读 + 原理图 PDF 文本抽取。**未上电实测**，凡属推断的结论均显式标注 `【推断】`。
> **证据标注**：`【源码】`＝逐行读过的代码；`【原理图】`＝PDF 抽文本（网络名/位号级）；`【推断】`＝由前两者推演、待硬件验证。

---

## 目录

- [0. 结论速览](#0-结论速览)
- [1. 差异分层模型](#1-差异分层模型)
- [2. 硬件接口层差异（板卡 ↔ BSP）](#2-硬件接口层差异板卡--bsp)
  - [2.1 板卡硬件事实](#21-板卡硬件事实)
  - [2.2 MCU 资源差异](#22-mcu-资源差异)
  - [2.3 引脚级对照表](#23-引脚级对照表)
  - [2.4 硬件层缺陷 H1~H4](#24-硬件层缺陷-h1h4)
- [3. 库层差异（标准库 ↔ HAL ↔ 裸寄存器）](#3-库层差异标准库--hal--裸寄存器)
  - [3.1 三层写法模型](#31-三层写法模型)
  - [3.2 API 映射表](#32-api-映射表)
  - [3.3 配置项对照表](#33-配置项对照表)
  - [3.4 为什么不能同时引入标准库](#34-为什么不能同时引入标准库)
- [4. USB 协议栈层差异（ST OTG ↔ CherryUSB）](#4-usb-协议栈层差异st-otg--cherryusb)
  - [4.1 分层对应表](#41-分层对应表)
  - [4.2 初始化时序对照](#42-初始化时序对照)
  - [4.3 官方 HAL 参考工程的实际参数](#43-官方-hal-参考工程的实际参数)
  - [4.4 CherryUSB 侧需要改动的 4 处](#44-cherryusb-侧需要改动的-4-处)
- [5. 构建 / 工具链层差异](#5-构建--工具链层差异)
- [6. 缺陷与整改清单](#6-缺陷与整改清单)
- [7. 实施步骤与验收](#7-实施步骤与验收)
- [8. 待确认事项](#8-待确认事项)
- [9. 参考资料索引](#9-参考资料索引)

---

## 0. 结论速览

| 层 | 本工程现状 | 官方参考资料 | 差异性质 | 结论 |
|---|---|---|---|---|
| **硬件接口层** | `stm32f407-atk-explorer` BSP 的引脚常量（ATK 探索者 F407ZG 板） | 本板为 `STM32F407_OTG_USB3300_ULPI_V1.1`（LQFP100 + USB3300） | **实体不一致**，有 3 处实质错误 | 必须改引脚/容量常量，**不必换 BSP** |
| **库层** | HAL（`STM32F4xx_HAL`，v1.8.1）+ 裸寄存器 | 标准库（`STM32F4xx_StdPeriph_Driver`）**和** HAL 两套都有 | 同一批硬件事实的两种写法 | **不引入标准库**，只搬 30 行板级事实；HAL 参考工程可直接对号 |
| **USB 协议栈层** | CherryUSB 裁剪版（轮询，DWC2 从机） | ST `USB_OTG_Driver` + `USB_Device_Library`（中断驱动） | 架构不同（中断 vs 轮询） | **保留 CherryUSB**，不搬 ST 栈；只改 4 处配置 |
| **构建层** | SCons + GCC + `link.lds` + pyocd | MDK-ARM（GBK 源文件、`Project.uvprojx`） | 工具链完全不同 | 参考工程不可直接编入本工程 |
| **目标形态** | 当前仅 OTG_FS 12 Mbps | 板载 USB3300 可跑 OTG_HS 480 Mbps | 能力未启用 | 属功能升级，非缺陷 |

**一句话**：这份资料的价值不在“代码怎么搬”，而在**它同时给了标准库版和 HAL 版的同一块板子配置**——后者（`02_CubeMX生成代码`）与本工程的 HAL 层几乎可以逐行对号，是本次分析最有价值的部分。

---

## 1. 差异分层模型

```
┌────────────────────────────────────────────────────────────────────────┐
│ L4  应用层      ramdump CLI / YMODEM / CDC 类                          │  本工程独有
├────────────────────────────────────────────────────────────────────────┤
│ L3  USB 栈层    CherryUSB(usbd_core + usbd_cdc_acm + usb_dc_dwc2)      │  ← 对应 ST
│                 │                          ↑                           │    USB_Device_Library
│                 │  glue: usb_dc_low_level_init()                      │    + USB_OTG_Driver
├────────────────────────────────────────────────────────────────────────┤
│ L2  库层        HAL 驱动(stm32f4xx_hal_*) / 裸寄存器                    │  ← 对应
│                 （互斥，不混用）                                        │    StdPeriph_Driver
├────────────────────────────────────────────────────────────────────────┤
│ L1  硬件接口层  MCU 外设时钟 / GPIO 复用 / PHY / 复位 / 板级网络        │  ← 对应
│                 （唯一真正与板子强绑定的层）                            │    usb_bsp.c
└────────────────────────────────────────────────────────────────────────┘
        ▲                                                    ▲
   本工程改这层的两处常量                          参考工程把事实写在这层
```

**关键判断**：三层之间**只有 L1 需要移植**。L2/L3 是“同一件事的两种实现”，选一种用到底即可；跨实现混用会带来重复定义与初始化竞争（见 3.4）。

---

## 2. 硬件接口层差异（板卡 ↔ BSP）

### 2.1 板卡硬件事实

来源：`third-party/STM32F407_OTG_USB3300/02_原理图/STM32F407_OTG_USB3300.pdf`（3 页，嘉立创 EDA，`STM32F407_OTG_USB3300_ULPI_V1.1`，V1.0 / 2024-03-02）【原理图】

```
                    ┌──────────── STM32F407Vx (LQFP100) ────────────┐
   X1 8MHz ────────►│ PH0/PH1 (OSC_IN/OUT)                          │
   X2 32.768kHz ───►│ PC14/PC15 (OSC32)                             │
                    │                                               │
   CH340G RXD ◄─────│ PA9  (USART1_TX)      ┌── 也接到 USBFS_VBUS ──┤← 冲突点
   CH340G TXD ─────►│ PA10 (USART1_RX)      │                       │
                    │                                               │
   USBFS-DEVICE ────│ PA11 (USBFS_DM) / PA12 (USBFS_DP)             │
   USBFS-HOST   ────┤ PA8 (USBFS_ID) / PA9 (USBFS_VBUS) / SOF        │
                    │                                               │
                    │ PA3/PA5/PB0/PB1/PB5/PB10-13/PC0/PC2/PC3       │
   USBHS-HOST ──────┤   └── ULPI_D0..D7 / CK / STP / DIR / NXT       │
   USBHS-DEVICE ────┤            └──► U1 USB3300-EZK-TR (24MHz X3)   │
                    │ PE7 (ULPI_RESETB) ──► USB3300 RESET            │
                    │                                               │
   TF 卡 SDIO ──────┤ PC8-DAT0 PC9-DAT1 PC10-DAT2 PC11-DAT3         │
                    │ PC12-CLK  PD2-CMD                             │
   LED ─────────────┤ PB8(TIM4_CH3) PB9(TIM4_CH4) PD12(TIM4_CH1)     │
   KEY ─────────────┤ PA0(KEY1) PC13(KEY2)，4.7K 上拉 + 1K 串联      │
                    └───────────────────────────────────────────────┘
```

- 封装：引脚编号 1~100 且为 LQFP100 编号（PC0=15、PA0=23、PE7=38、PB10=47、PB12=51、PA13=72、PA11=70、PA12=71、PC12=80、BOOT0=94），含 PE7~PE15、PD8~PD15、PH0/PH1 → **100 脚器件，无 GPIOF/G/I**【原理图】
- 跳线 **H2（6 pin）** 原理图注：「35、46 短接表示使用内部全速 phy，13、24 短接表示使用外部高速 phy」→ ULPI 使用时须短 1-3 / 2-4【原理图】
- USB3300 时钟：X3=24MHz + C19/C22 20pF + R3 10M + R4 12K，CLKOUT 输出 60MHz 给 PA5【原理图】
- 原理图另有文字注「STM32F407不支持CPEN命令」（指 ULPI PHY 的 CPEN 控制）【原理图】

### 2.2 MCU 资源差异

| 项目 | BSP 的假设 | 本板实际 | 证据 |
|---|---|---|---|
| 引脚数 / 端口 | 144 脚，含 GPIOF/G/I（FSMC/ETH/LCD/SDRAM） | 100 脚，只有 A/B/C/D/E/H | 【原理图】 |
| Flash | `link.lds` `CODE LENGTH = 1024k`；`board.h` `STM32_FLASH_SIZE (1024*1024)` | F407VE=512K 或 F407VG=1M，**待实测** | 【源码】【推断】 |
| RAM | 128K + 64K CCM | F407 一致（112K+16K + 64K CCM） | 【源码】✅ 匹配 |
| HSE | 8 MHz | X1 = 8 MHz + 20pF | 【原理图】✅ 匹配 |
| 外部 SDRAM | `link.lds` 有 `MCUlcdgrambysram @ 0x68000000, 1024k` | **无 SDRAM 芯片** | 【原理图】 |
| ETH / FSMC / LCD | msp 里有对应 `HAL_xxx_MspInit` | 无 PHY、无 FMC 器件 | 【源码】【原理图】 |
| SDIO | PC8-PC12 + PD2，AF12 | 完全一致（TF 卡座） | 【源码】【原理图】✅ 匹配 |
| 时钟树 | `board.c`：`sys_stm32_clock_init(336, 8, 2, 7)` → 168MHz / PLLQ=7 → 48MHz | 官方 CubeMX 工程：`PLLM=4, PLLN=168, PLLP=DIV2, PLLQ=7` → 同样 168MHz / 48MHz | 【源码】✅ **等效** |

> 注意：`board.c` 用 (N=336, M=8) 与官方 (N=168, M=4) 比值相同，VCO=336MHz，最终频率完全一致，**换 HS 也不必改时钟树**——ULPI 的 60MHz 由 USB3300 自己的 24MHz 晶振产生，不来自 PLL。

### 2.3 引脚级对照表

| 功能 | BSP / 本工程配置 | 板子实际 | 一致? | 证据 |
|---|---|---|---|---|
| **USART1（控制台 + ramdump UART）** | `stm32f4xx_hal_msp.c:742` `GPIO_InitStruct.Pin = GPIO_PIN_6\|GPIO_PIN_7;` → `GPIOB`，AF7 | **PA9/PA10 → CH340G**；PB6/PB7 只引到 H10 排针（注「用于插逻辑分析仪」） | ❌ | 【源码】【原理图】 |
| USB OTG_FS | `ramdump_usb_cdc.c:250-273`：PA11/PA12 AF10 + `RCC_AHB2ENR_OTGFSEN` | USBFS_DM=PA11 / USBFS_DP=PA12（MINI 5P 座） | ✅ | 【源码】【原理图】 |
| USB OTG_HS ULPI | msp 有配置，但**从未被调用**（无 `HAL_PCD_Init`） | 12 根 ULPI 线接 USB3300 | ⚠️ 配置存在但不生效 | 【源码】【原理图】 |
| USB3300 RESET | **全仓库零引用** | PE7 = ULPI_RESETB | ❌ 缺失 | 【源码】【原理图】 |
| USB VBUS 传感 | `ramdump_usb_cdc.c:281-287` 返回 `(1<<16)\|(1<<21)` → NOVBUSSENS | `USBFS_VBUS = PA9`，**与 USART1_TX 共用** | ✅（当前正确，以后也别开） | 【源码】【原理图】 |
| SDIO | PC8-PC12 + PD2 | 同左 | ✅ | 【源码】【原理图】 |
| LED0 | `applications/main.c:20` `GET_PIN(F, 9)` | PB8/PB9/PD12 | ❌（但 `rt_pin_*` 已注释，当前无害） | 【源码】【原理图】 |
| KEY | 无 | PA0 / PC13 | — 未使用 | 【原理图】 |
| BOOT0/BOOT1 | — | 各 10K 下拉 | — | 【原理图】 |

### 2.4 硬件层缺陷 H1~H4

#### H1 🔴 USART1 引脚错（阻塞级）

`bsp/stm32/stm32f407-atk-explorer/board/CubeMX_Config/Src/stm32f4xx_hal_msp.c:737-747`【源码】：

```c
    __HAL_RCC_GPIOB_CLK_ENABLE();
    /**USART1 GPIO Configuration
    PA9     ------> USART1_TX      ← 注释是 PA9/PA10
    PA10     ------> USART1_RX
    */
    GPIO_InitStruct.Pin = GPIO_PIN_6|GPIO_PIN_7;   ← 代码是 PB6/PB7（ATK 板接法）
    ...
    HAL_GPIO_Init(GPIOB, &GPIO_InitStruct);
```

影响链：`RT_CONSOLE_DEVICE_NAME "uart1"` → `drv_usart.c:231 HAL_UART_Init()` → `HAL_UART_MspInit()`（drv_usart.c 内部**完全没有 GPIO 代码**）→ 控制台落在 PB6/PB7。`ramdump_uart_init()` 只重配 USART 寄存器、不碰 GPIO，所以 **ramdump 的 UART 通道同样落在 PB6/PB7**。`【推断】` 在这块板上表现为：MSH 无输出、`cmd_ramdump` 无法从 CH340 口触发。

改法：

```c
    __HAL_RCC_GPIOA_CLK_ENABLE();
    GPIO_InitStruct.Pin = GPIO_PIN_9|GPIO_PIN_10;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_PULLUP;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    GPIO_InitStruct.Alternate = GPIO_AF7_USART1;
    HAL_GPIO_Init(GPIOA, &GPIO_InitStruct);
```

> **反向校验**：如果当前固件在这块板上 COM46 能打出 MSH，说明实际编译的不是仓库里这份 msp（见 §8 待确认项 1）。

#### H2 🟠 Flash 容量写大（潜在、静默）

| 位置 | 当前值 |
|---|---|
| `board/linker_scripts/link.lds` | `CODE (rx) : ORIGIN = 0x08000000, LENGTH = 1024k` |
| `board/board.h` | `#define STM32_FLASH_SIZE (1024*1024)` |
| `scripts/src/toolbelt/firmware/config.py`（原 `bsp/.../build_and_flash.bat:67`，该 bat 已删） | `PYOCD_TARGET = "STM32F407VE"`（512K 型号） |

三者互相矛盾。改法（先测再改）：

```bash
# Flash size 寄存器 0x1FFF7A22，单位 KB；device ID 0x1FFF7A10
pyocd cmd -t STM32F407VE -c "read32 0x1FFF7A22"
```

- 读到 `0x80000`（512K）→ `link.lds` 改 `LENGTH = 512k`，`board.h` 改 `512*1024`
- 读到 `0x100000`（1M）→ `build_and_flash.bat` 的 pyocd target 改 `STM32F407VG`（当前 target 对 VG 只擦一半，容易跑出诡异现象）

#### H3 🟠 USB3300 完全未初始化

现状（三项全缺）【源码】：

| 需要的东西 | 参考工程里在哪 | 本工程 |
|---|---|---|
| ULPI 12 根引脚的 AF10 配置 | `02_CubeMX生成代码/.../USB_DEVICE/Target/usbd_conf.c:69-123`；`01_基于标准库修改/.../usb_bsp.c` 的 `USE_ULPI_PHY` 分支 | 只在从不被调用的 `HAL_PCD_MspInit()` 里 |
| `RCC OTG_HS + OTG_HS_ULPI` 时钟 | 同上 `__HAL_RCC_USB_OTG_HS_ULPI_CLK_ENABLE()` | 无 |
| **PE7 → USB3300 RESET 脉冲** | `02_CubeMX生成代码/.../Core/Src/main.c:161-181`；`usb_bsp.c` 注释「增加USB3300 pin脚复位代码」 | **无** |

官方 HAL 版原文（`main.c:161-181`）【源码】：

```c
  __HAL_RCC_GPIOE_CLK_ENABLE();
  GPIO_InitStruct.Pin = GPIO_PIN_7;
  GPIO_InitStruct.Mode = GPIO_MODE_OUTPUT_PP;
  GPIO_InitStruct.Pull = GPIO_NOPULL;
  GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_LOW;
  HAL_GPIO_Init(GPIOE, &GPIO_InitStruct);

  HAL_GPIO_WritePin(GPIOE, GPIO_PIN_7, GPIO_PIN_SET);      /* 复位有效（高） */
  for (int i=0; i<0xffff; i++) { ; }                       /* 忙等 */
  HAL_GPIO_WritePin(GPIOE, GPIO_PIN_7, GPIO_PIN_RESET);    /* 释放复位 */
```

> 标准库版用 `0xfff` 次空循环，HAL 版用 `0xffff` 次。168MHz 下分别约 0.1ms / 2ms 量级。USB3300 对 RESET 脉宽的具体要求见 `04_Datasheet/USB3300.pdf`（本文未逐条核对）；枚举不稳定时把脉宽加长即可。

#### H4 🟡 无害残留（不建议动）

| 项 | 说明 |
|---|---|
| msp 里的 ETH / FSMC / LCD / DAC / SPI / TIM4 编码器 MspInit | 对应外设均未启用；本板无 GPIOF/G/I，但这些函数不会被调用 |
| `link.lds` 的 `MCUlcdgrambysram @ 0x68000000` | 空区域，不占 Flash/RAM |
| `main.c` 的 `LED0_PIN GET_PIN(F, 9)` | `rt_pin_mode/write` 全注释，无运行时影响 |
| `stm32f4xx_it.c` 未被编译 | `board/SConscript` 只编译 `board.c` + `CubeMX_Config/Src/stm32f4xx_hal_msp.c` + `ramdump_handlers.c`，所以 `stm32f4xx_it.c:256 OTG_FS_IRQHandler` 与 `ramdump_usb_cdc.c:291 OTG_FS_IRQHandler` **不会重复定义** |

---

## 3. 库层差异（标准库 ↔ HAL ↔ 裸寄存器）

### 3.1 三层写法模型

```
        参考工程 01_基于标准库修改              本工程 app/ramdump/transport/usb
        ┌──────────────────────────┐          ┌──────────────────────────┐
        │ usb_bsp.c:               │          │ ramdump_usb_cdc.c:       │
        │   USB_OTG_BSP_Init()     │          │   usb_dc_low_level_init()│
        │   RCC_AHBxPeriphClockCmd │          │   RCC->AHB1ENR |= ...    │
        │   GPIO_Init / PinAFConfig│          │   GPIOA->MODER / AFR     │
        │   NVIC_Init              │          │   (无 NVIC，轮询)         │
        └───────────┬──────────────┘          └──────────────────────────┘
                    │                                   ▲
                    │        语义完全相同，只是 API       │
                    └─────────────►  HAL 写法 ◄──────────┘
                                    __HAL_RCC_xxx_CLK_ENABLE()
                                    HAL_GPIO_Init()  Alternate = GPIO_AF10_OTG_HS
                                    HAL_NVIC_SetPriority/EnableIRQ
```

**结论**：所谓“标准库转 HAL”，在本项目里就是**把 `usb_bsp.c` 的 30 行板级初始化重写成 HAL 或裸寄存器**——而这一步本工程早就做完了（`usb_dc_low_level_init()` 存在）。真正缺的不是“翻译”，是 §2.4-H3 那三项**本板专属事实**（ULPI 引脚、USB3300 复位、OTG_HS 时钟）。

### 3.2 API 映射表

| 参考工程（StdPeriph） | HAL 写法（官方 CubeMX 工程里就是这么写的） | 本工程实际（裸寄存器） |
|---|---|---|
| `RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_OTG_HS \| RCC_AHB1Periph_OTG_HS_ULPI, ENABLE)` | `__HAL_RCC_USB_OTG_HS_CLK_ENABLE(); __HAL_RCC_USB_OTG_HS_ULPI_CLK_ENABLE();` | `RCC->AHB1ENR \|= RCC_AHB1ENR_OTGHSEN \| RCC_AHB1ENR_OTGHSULPIEN;` |
| `RCC_AHB2PeriphClockCmd(RCC_AHB2Periph_OTG_FS, ENABLE)` | `__HAL_RCC_USB_OTG_FS_CLK_ENABLE();` | `RCC->AHB2ENR \|= RCC_AHB2ENR_OTGFSEN;` |
| `RCC_AHB1PeriphClockCmd(RCC_AHB1Periph_GPIOx, ENABLE)` | `__HAL_RCC_GPIOx_CLK_ENABLE();` | `RCC->AHB1ENR \|= RCC_AHB1ENR_GPIOxEN;` |
| `GPIO_Init()` + `GPIO_PinAFConfig(pin, GPIO_AF_OTG2_HS)` | `HAL_GPIO_Init()`，`Alternate = GPIO_AF10_OTG_HS` | `MODER=2 / AFR[n]=0xA / OTYPER / OSPEEDR / PUPDR` |
| `GPIO_Mode_OUT`（PE7 复位） | `GPIO_MODE_OUTPUT_PP` + `HAL_GPIO_WritePin` | `MODER=1` + `BSRR` |
| `USB_OTG_BSP_uDelay()/usDelay()` | `HAL_Delay()` / 空循环 | DWT CYCCNT 忙等（`ramdump_port` 层，**不能用 `rt_thread_mdelay`**） |
| `NVIC_Init()` + `USB_OTG_BSP_EnableInterrupt()` | `HAL_NVIC_SetPriority/EnableIRQ` | 本工程**故意不使能**：`NVIC_DisableIRQ()`，靠 `ramdump_usb_poll()` 手动调 `USBD_IRQHandler(0)` |

### 3.3 配置项对照表

| 概念 | 参考工程（标准库） | 参考工程（HAL / CubeMX） | 本工程（CherryUSB） |
|---|---|---|---|
| 核心选择 | 编译宏 `USE_USB_OTG_FS` / `USE_USB_OTG_HS` → `usb_conf.h` 派生 `USB_OTG_FS_CORE` / `USB_OTG_HS_CORE` | `hpcd.Init` 的 `Instance` + `usbd_conf.h` 的 `DEVICE_FS/DEVICE_HS` | `usbd_initialize(busid, reg_base, cb)` 的 `reg_base`（`0x50000000` / `0x40040000`） |
| 外挂 PHY | `USE_ULPI_PHY` → `usb_conf.h:143 #define USB_OTG_ULPI_PHY_ENABLED` | `hpcd.Init.phy_itface = USB_OTG_ULPI_PHY` | `#define CONFIG_USB_HS` |
| 内置 FS PHY | `USE_EMBEDDED_PHY` | `PCD_PHY_EMBEDDED` | 不定义 `CONFIG_USB_HS`（走 `GUSBCFG \|= PHYSEL`） |
| 速度 | `USB_OTG_SPEED_PARAM_HIGH` / `..._HIGH_IN_FULL` | `hpcd.Init.speed = PCD_SPEED_HIGH` / `PCD_SPEED_FULL` | `DCFG.DSPD`，`usb_dc_dwc2.c:590-600` 自动按 `CONFIG_USB_HS` + `GHWCFG2.hsphy_type` 选 |
| RX FIFO | `usb_conf.h:132 RX_FIFO_HS_SIZE 512`（**字节**） | 写死在 `stm32f4xx_ll_usb.c:1571`：HS `GRXFSIZ=0x200`（word） | `CONFIG_USB_DWC2_RXALL_FIFO_SIZE`（**word**，现为 `512/4`） |
| EP0 TX FIFO | `usb_conf.h:133 TX0_FIFO_HS_SIZE 128`（字节） | `stm32f4xx_ll_usb.c:1572`：HS EP0 `0x100`（word） | `CONFIG_USB_DWC2_TX0_FIFO_SIZE`（现为 `64/4`） |
| bulk IN FIFO | `usb_conf.h:134 TX1_FIFO_HS_SIZE 372`（字节） | 不单独配（走 EP 重配 API） | `CONFIG_USB_DWC2_TX1_FIFO_SIZE` |
| EP0 最大包 | `USB_OTG_MAX_EP0_SIZE 64` | HAL 内部固定 64 | dwc2 端口固定 64 |
| DMA | 无（`USE_USB_OTG_HS` 下默认 slave） | `hpcd.Init.dma_enable = DISABLE` | `// #define CONFIG_USB_DWC2_DMA_ENABLE`（注释理由：F407 slave-only） |
| VBUS 传感 | `VBUS_SENSING_ENABLED` | `hpcd.Init.vbus_sensing_enable = DISABLE` | `usbd_get_dwc2_gccfg_conf()` 返回 `(1<<16)\|(1<<21)` |
| 中断 | `OTG_HS_IRQn` + `USB_OTG_BSP_EnableInterrupt()` | `HAL_NVIC_SetPriority(OTG_HS_IRQn,0,0)` + `EnableIRQ` | **不使能**，`ramdump_usb_poll()` → `USBD_IRQHandler(0)` |

> **FIFO 预算注意**：`usb_conf.h:126-127` 明确写了「In HS case 12 FIFO locations should be reserved for internal DMA registers so total FIFO size should be **1012** Only instead of 1024」。HS 规划 FIFO 时上限按 **1012 word** 算，不要按 1024。

### 3.4 为什么不能同时引入标准库

| 冲突点 | 说明 |
|---|---|
| `assert_param` / `stm32f4xx_conf.h` | 两套库都有同名宏与同名头，`USE_STDPERIPH_DRIVER` 与 HAL 并存会导致重复定义 |
| `SystemInit` / `SystemCoreClockUpdate` | 标准库 `system_stm32f4xx.c` 与 HAL 版同名同义但实现不同，链接期二选一 |
| 启动文件与外设头 | `stm32f4xx.h`（标准库）与 `stm32f4xx.h`（CMSIS 设备头）路径同名 |
| 收益 | 为了 30 行 GPIO 引入一整套库，且和现有 BSP 的 HAL/SConstruct 结构打架 → **不值得** |

---

## 4. USB 协议栈层差异（ST OTG ↔ CherryUSB）

### 4.1 分层对应表

| 概念 | ST `USB_OTG_Driver` + `USB_Device_Library` | CherryUSB（本工程裁剪版） |
|---|---|---|
| 硬件抽象 | `usb_core.c` / `usb_dcd.c` / `usb_hcd.c` | `port/dwc2/usb_dc_dwc2.c` |
| 设备状态机 | `usbd_core.c`（`USBD_Init/Start/LL_*`） | `core/usbd_core.c`（`usbd_initialize/add_interface/ep_start_read...`） |
| 类驱动 | `usbd_cdc.c`（CDC ACM） | `class/cdc/usbd_cdc_acm.c` |
| 板级 glue | `usb_bsp.c` | `usb_dc_low_level_init()`（现内联在 `ramdump_usb_cdc.c`）+ `usbd_get_dwc2_gccfg_conf()` |
| 触发方式 | **中断**：`OTG_HS_IRQHandler → HAL_PCD_IRQHandler / USB_OTG_IRQHandler` | **轮询**：`ramdump_usb_poll() → USBD_IRQHandler(0)` |
| 注册入口 | `MX_USB_DEVICE_Init()` | `INIT_*_EXPORT(ramdump_usb_init)` |

### 4.2 初始化时序对照

```
ST / HAL 版（02_CubeMX生成代码）          本工程 CherryUSB 版
─────────────────────────────────        ─────────────────────────────────
main()                                   ramdump_usb_init()
 ├ MX_GPIO_Init()                        ├ 描述符/接口/端点注册
 │   └ PE7 复位脉冲 ★                     │   usbd_desc_register()
 ├ MX_USB_DEVICE_Init()                  │   usbd_add_interface()/add_endpoint()
 │   ├ USBD_Init(&hUsbDeviceHS)          ├ usbd_initialize(0, reg_base, cb)
 │   ├ USBD_RegisterClass(USBD_CDC)      │   └→ usb_dc_dwc2 初始化
 │   ├ USBD_CDC_RegisterInterface()      │        ├ usb_dc_low_level_init()  ★
 │   └ USBD_Start()                      │        │   GPIO/时钟/PHY/复位
 │        └ USBD_LL_Init()               │        └ dwc2_core_init() 选 PHY
 │             └ HAL_PCD_Init()          └ NVIC_DisableIRQ(...)  ← 轮询模式
 │                  ├ HAL_PCD_MspInit()  ★
 │                  │   ULPI 引脚 + 时钟
 │                  └ LL USB_DevInit()
 │                       FIFO 写死
 └ 主循环 while(1) —— 中断驱动
                                          ramdump_usb_poll()  ← 主循环/dump 循环调用
                                            └ USBD_IRQHandler(0)
```

★ = 板级事实所在处，**这是唯一需要从参考工程搬的东西**。

### 4.3 官方 HAL 参考工程的实际参数

来源：`third-party/STM32F407_OTG_USB3300/01_Code/02_CubeMX生成代码/STM32F407_OTGHS_Device_VirtualPortCom_LoopBack/`【源码】

`USB_DEVICE/Target/usbd_conf.c:377-392`：

```c
  hpcd_USB_OTG_HS.Instance = USB_OTG_HS;
  hpcd_USB_OTG_HS.Init.dev_endpoints = 6;
  hpcd_USB_OTG_HS.Init.speed = PCD_SPEED_HIGH;
  hpcd_USB_OTG_HS.Init.dma_enable = DISABLE;
  hpcd_USB_OTG_HS.Init.phy_itface = USB_OTG_ULPI_PHY;
  hpcd_USB_OTG_HS.Init.Sof_enable = DISABLE;
  hpcd_USB_OTG_HS.Init.low_power_enable = DISABLE;
  hpcd_USB_OTG_HS.Init.lpm_enable = DISABLE;
  hpcd_USB_OTG_HS.Init.vbus_sensing_enable = DISABLE;
  hpcd_USB_OTG_HS.Init.use_dedicated_ep1 = DISABLE;
  hpcd_USB_OTG_HS.Init.use_external_vbus = DISABLE;
  HAL_PCD_Init(&hpcd_USB_OTG_HS);
```

作为对照，FS 版工程（`STM32F407_OTGFS_Device_VirtualPortCom_LoopBack/USB_DEVICE/Target/usbd_conf.c:335-343`）：

```c
  hpcd_USB_OTG_FS.Instance = USB_OTG_FS;
  hpcd_USB_OTG_FS.Init.dev_endpoints = 4;
  hpcd_USB_OTG_FS.Init.speed = PCD_SPEED_FULL;
  hpcd_USB_OTG_FS.Init.dma_enable = DISABLE;
  hpcd_USB_OTG_FS.Init.phy_itface = PCD_PHY_EMBEDDED;
```

→ 本工程当前 FS 配置（`CDC_IN_EP 0x81 / OUT 0x02 / INT 0x83`、`CONFIG_USBDEV_EP_NUM 4`、无 DMA）与此**完全对齐**；切 HS 时把 `dev_endpoints` 语义扩到 6 也完全够用（本工程只要 4）。

### 4.4 CherryUSB 侧需要改动的 4 处

> 全部集中在 `app/ramdump/transport/usb/`。CherryUSB 的 `dwc2_core_init()`（`usb_dc_dwc2.c:172-191`）**已经内置 ULPI 分支**，寄存器序列不用自己写。

#### 改 1：`common/usb_config.h` —— 打开 HS + 调 FIFO

```c
/* ---- PHY 选择：外挂 ULPI（USB3300），等价于 ST 的 USE_USB_OTG_HS + USE_ULPI_PHY ---- */
#define CONFIG_USB_HS

/* ---- HS FIFO 预算上限 1012 word（见 usb_conf.h (vi) 注）---- */
#define CONFIG_USB_DWC2_RXALL_FIFO_SIZE  (1024 / 4)   /* 256 word = 1KB */
#define CONFIG_USB_DWC2_TX0_FIFO_SIZE    (64   / 4)   /* 16  word，EP0 64B */
#define CONFIG_USB_DWC2_TX1_FIFO_SIZE    (512  / 4)   /* 128 word，bulk IN 512B */
#define CONFIG_USB_DWC2_TX2_FIFO_SIZE    (64   / 4)
#define CONFIG_USB_DWC2_TX3_FIFO_SIZE    (64   / 4)
/* 合计 432 word ≤ 1012，安全 */
```

`usb_dc_dwc2.c:666` 的断言 `USB_ASSERT_MSG(!((hsphy_type == 0) && (fifo_num > 320)), ...)` 只对内置 FS PHY（`hsphy_type==0`）生效；ULPI 的 `hsphy_type==2`，不受 320 限制。

#### 改 2：`ramdump_usb_cdc.c` —— 换基址（其余宏全是派生式，一处改动自动传导）

```c
#define USB_OTG_HS_BASE   0x40040000U        /* 原：USB_OTG_FS_BASE 0x50000000U */

#define DWC2_INEP0_BASE   (USB_OTG_HS_BASE + 0x900U)
#define DWC2_INEP1_BASE   (USB_OTG_HS_BASE + 0x900U + 1U * 0x20U)
#define DWC2_DIEPCTL1     (DWC2_INEP1_BASE + 0x00U)
#define DWC2_DIEPINT1     (DWC2_INEP1_BASE + 0x08U)
#define DWC2_DIEPEMPMSK   (USB_OTG_HS_BASE + 0x800U + 0x34U)
#define DWC2_GRSTCTL      (USB_OTG_HS_BASE + 0x10U)
```

同步两处：

```c
#define CDC_MAX_MPS   512        /* 原 64；先留 64 也能跑，只是慢（可作分阶段项） */
usbd_initialize(0, USB_OTG_HS_BASE, usbd_event_handler);
NVIC_DisableIRQ(OTG_HS_IRQn);    /* 原 OTG_FS_IRQn */
void OTG_HS_IRQHandler(void) { USBD_IRQHandler(0); }   /* 原 OTG_FS_IRQHandler；轮询模式下不会触发 */
```

`usb_rx_pkt[]` / `usb_tx_buf[]` 以 `CDC_MAX_MPS` 定长、`ramdump_usb_send()` 的切包也用 `CDC_MAX_MPS`，会**自动跟着变**，无需另改。

#### 改 3：`usb_dc_low_level_init()` —— ULPI 引脚 + PE7 复位 + 时钟

```c
#define ULPI_RST_PORT   GPIOE
#define ULPI_RST_PIN    7U
#define AF_OTG_HS       0xAU          /* F407：OTG_HS/ULPI 全部 AF10 */

static void gpio_af_cfg(GPIO_TypeDef *port, uint32_t pin, uint32_t af)
{
    port->MODER   = (port->MODER   & ~(3U << (pin * 2U))) | (2U << (pin * 2U));  /* AF */
    port->OTYPER &= ~(1U << pin);
    port->OSPEEDR |=  (3U << (pin * 2U));                                        /* very high */
    port->PUPDR   = (port->PUPDR   & ~(3U << (pin * 2U)));                       /* no pull */
    port->AFR[pin >> 3U] = (port->AFR[pin >> 3U] & ~(0xFU << ((pin & 7U) * 4U)))
                         | (af << ((pin & 7U) * 4U));
}

int usb_dc_low_level_init(uint8_t busid)
{
    /* 1) 时钟：GPIOA/B/C/E + OTG_HS + OTG_HS_ULPI */
    RCC->AHB1ENR |= RCC_AHB1ENR_GPIOAEN | RCC_AHB1ENR_GPIOBEN |
                    RCC_AHB1ENR_GPIOCEN | RCC_AHB1ENR_GPIOEEN |
                    RCC_AHB1ENR_OTGHSEN | RCC_AHB1ENR_OTGHSULPIEN;

    /* 2) ULPI 12 根线（与官方 usbd_conf.c:69-123 / usb_bsp.c 完全一致） */
    gpio_af_cfg(GPIOA,  3U, AF_OTG_HS);   /* ULPI_D0  */
    gpio_af_cfg(GPIOA,  5U, AF_OTG_HS);   /* ULPI_CK  (60MHz from USB3300) */
    gpio_af_cfg(GPIOB,  0U, AF_OTG_HS);   /* ULPI_D1  */
    gpio_af_cfg(GPIOB,  1U, AF_OTG_HS);   /* ULPI_D2  */
    gpio_af_cfg(GPIOB,  5U, AF_OTG_HS);   /* ULPI_D7  */
    gpio_af_cfg(GPIOB, 10U, AF_OTG_HS);   /* ULPI_D3  */
    gpio_af_cfg(GPIOB, 11U, AF_OTG_HS);   /* ULPI_D4  */
    gpio_af_cfg(GPIOB, 12U, AF_OTG_HS);   /* ULPI_D5  */
    gpio_af_cfg(GPIOB, 13U, AF_OTG_HS);   /* ULPI_D6  */
    gpio_af_cfg(GPIOC,  0U, AF_OTG_HS);   /* ULPI_STP */
    gpio_af_cfg(GPIOC,  2U, AF_OTG_HS);   /* ULPI_DIR */
    gpio_af_cfg(GPIOC,  3U, AF_OTG_HS);   /* ULPI_NXT */

    /* 3) USB3300 复位：PE7 推挽输出，先高再低（对齐官方 main.c:161-181） */
    ULPI_RST_PORT->MODER = (ULPI_RST_PORT->MODER & ~(3U << (ULPI_RST_PIN * 2U)))
                         | (1U << (ULPI_RST_PIN * 2U));
    ULPI_RST_PORT->BSRR = 1U << ULPI_RST_PIN;              /* 复位有效 */
    for (volatile uint32_t i = 0; i < 0xFFFFU; i++) { }    /* 忙等 ~2ms（同官方 0xffff） */
    ULPI_RST_PORT->BSRR = 1U << (ULPI_RST_PIN + 16U);      /* 释放复位 */

    __DSB();
    __ISB();
    return 0;
}
```

#### 改 4：GCCFG

```c
uint32_t usbd_get_dwc2_gccfg_conf(uint32_t reg_base)
{
    return (1 << 16) | (1 << 21);   /* 与现状一致；切 HS 后保持即可（VBUS 传感必须关闭） */
}
```

> VBUS 传感之所以必须关：原理图上 `USBFS_VBUS` 与 `USART1_TX` 共用 PA9，一旦启用传感，串口 TX 会失效。官方两个参考工程（标准库 `VBUS_SENSING_ENABLED` 未定义、HAL `vbus_sensing_enable = DISABLE`）也是关闭的。

---

## 5. 构建 / 工具链层差异

| 维度 | 参考工程 | 本工程 | 处理 |
|---|---|---|---|
| 构建系统 | MDK-ARM `Project.uvprojx`（双 target：FS / HS） | SCons + GCC（`bsp/stm32/stm32f407-atk-explorer/SConstruct`） | 不做转换，只做人工对号 |
| 编译器宏 | `USE_STDPERIPH_DRIVER, STM32F40_41xxx, USE_USB_OTG_HS, USE_ULPI_PHY` | `CPPDEFINES = ['STM32F407xx']` | 宏语义已由头文件/Kconfig 承担 |
| 器件 | `<Device>STM32F407IGHx</Device>`（BGA176 模板选项，与实际 LQFP100 不符） | `startup_stm32f407xx.s` | 参考工程**不可直接编入本板** |
| 源码编码 | **GBK**（`read` 类工具按 UTF-8 读会报 invalid UTF-8） | UTF-8 | 抄代码时注意注释乱码 |
| 启动/链接 | MDK scatter | `board/linker_scripts/link.lds` | 容量需按 H2 修正 |
| 烧写 | MDK 下载 | `build_and_flash.bat` → pyocd，`PYOCD_TARGET=STM32F407VE` | 需与真实容量对齐 |
| 中断文件 | `Core/Src/stm32f4xx_it.c` 参与编译 | `stm32f4xx_it.c` **不参与编译**（见 H4） | 改中断需注意落点 |

---

## 6. 缺陷与整改清单

| ID | 层 | 现象 | 根因 | 改法 | 验收 |
|---|---|---|---|---|---|
| **H1** | 硬件接口 | 串口/MSH 无输出、ramdump UART 不通（`【推断】`） | `stm32f4xx_hal_msp.c:742` USART1 配 PB6/PB7，本板在 PA9/PA10 | 改 GPIOA + PIN_9/10（§2.4-H1） | COM46 打出 `this is a stm32f407 project` |
| **H2** | 硬件接口 | 固件 >512K 时烧写失败或跑飞 | `link.lds`/`board.h` 写 1M，pyocd target 是 VE | 实测 `0x1FFF7A22` 后统一 | `pyocd flash` 无告警、`lsm` 正常 |
| **H3** | 硬件接口 | USB 只有 FS 12Mbps；HS 通道不可用 | 无 ULPI GPIO / 无 OTG_HS 时钟 / 无 PE7 复位 | §4.4 改 3 | `USB_LOG_INFO` 报 `hsphy type:2`，枚举成功 |
| **H4** | 硬件接口 | 无实际影响 | ATK 板残留 | 不建议动 | — |
| **L1** | 库层 | —（无缺陷） | — | 不引入标准库 | — |
| **S1** | USB 栈 | `CONFIG_USB_HS` 未开 | 沿用 FS 裁剪配置 | §4.4 改 1 | 编译通过、`DCFG.DSPD=0`（HS） |
| **S2** | USB 栈 | 基址/IRQ/MPS 仍是 FS | 硬编码 FS 常量 | §4.4 改 2 | 设备管理器出现 CDC 口 |
| **S3** | USB 栈 | 设备侧 bulk 仅 64B/包 | `CDC_MAX_MPS 64` | 改 512（分阶段） | 传输时间下降 |

---

## 7. 实施步骤与验收

> 分四个阶段，每阶段单独可回滚。**阶段 A 修的是缺陷，阶段 B/C 是能力升级。**

### 阶段 A：修 H1 + H2（不碰 USB，先让板子“能说话”）

| 步 | 动作 | 验收 |
|---|---|---|
| A1 | 改 `stm32f4xx_hal_msp.c` USART1 → PA9/PA10 | `scons -j20` 通过 |
| A2 | `pyocd cmd -c "read32 0x1FFF7A22"` 确认容量，改 `link.lds`/`board.h` 或 pyocd target | `build_and_flash.bat build` 无告警 |
| A3 | 烧写，接 CH340 口开 MSH | 能敲 `help`、`list_device` |
| A4 | 跑现有 FS 版 ramdump 回归 | `cmd_ramdump` → 切 CDC 口 → `vcom` 回环 |

### 阶段 B：跑通 HS 枚举（先不管速度）

| 步 | 动作 | 验收 |
|---|---|---|
| B1 | 硬件：H2 短接 **1-3 / 2-4**，线插 **USBHS-DEVICE（MINI 5P）** | — |
| B2 | `usb_config.h` 加 `CONFIG_USB_HS`，FIFO 按 §4.4 改 1 | 编译通过 |
| B3 | 基址 → `0x40040000`、IRQ → `OTG_HS_IRQn` | — |
| B4 | 补 `usb_dc_low_level_init()`（ULPI + PE7） | 日志出现 `dwc2 fsphy type:x, hsphy type:2` |
| B5 | 烧写，看主机是否枚举（VID:PID `FFFF:FFFF`） | 出现新的 CDC 端口 |

### 阶段 C：提速度

| 步 | 动作 | 验收 |
|---|---|---|
| C1 | `CDC_MAX_MPS` 64 → 512，`TX1_FIFO` 128 word | 枚举仍正常 |
| C2 | 用 `04_USB速度测试` 里的官方测速工程做对照基线 | 记录 FS/HS 实测 MB/s |

### 阶段 D：硬件侧复核清单

- 万用表确认 USB3300 供电（AMS1117-3.3）与 X3 24MHz 起振
- 示波器看 PA5（ULPI_CK）是否有 60MHz（无时钟则核心复位会卡住）
- 确认 PE7 复位脉冲在示波器上可见（高 → 低）

---

## 8. 待确认事项

| # | 事项 | 影响 | 怎么确认 |
|---|---|---|---|
| 1 | 这块板上 CH340 口现在**到底能不能**出 MSH | 能 → 说明实际编译的源不是仓库里这份 msp；不能 → 正是 H1 | 烧现有固件试一次 |
| 2 | 芯片是 F407VE(512K) 还是 F407VG(1M) | 决定改 `link.lds` 还是改 pyocd target | `read32 0x1FFF7A22` |
| 3 | H2 跳线当前短接位置 | ULPI 能否枚举的前提 | 看板子丝印 |
| 4 | 是否需要同时保留 FS 通道 | 两个 USB 座可同时存在，但同一时刻只建议用一个设备实例 | 需求确认 |

---

## 9. 参考资料索引

> 全部位于 `third-party/STM32F407_OTG_USB3300/`，**官方原始资料，未做修改**。

| 路径 | 内容 | 本次用途 |
|---|---|---|
| `02_原理图/STM32F407_OTG_USB3300.pdf` | 3 页原理图（MCU / USB / Others） | §2 全部硬件事实 |
| `04_Datasheet/1-STM32F4xx中文参考手册1.pdf` | RM0090 中文 | 寄存器语义 |
| `04_Datasheet/2-STM32F40x英文数据手册.pdf` | 数据手册 | 封装/容量 |
| `04_Datasheet/USB3300.pdf` | ULPI PHY | 复位时序、时钟 |
| `01_Code/01_基于标准库修改/Project/STM32F407_OTG标准函数库使用说明V1.1.pdf` | 板级使用说明（引脚表、H2 跳线、VBUS/ID 策略） | §2、§3 |
| `01_Code/01_基于标准库修改/Libraries/` | StdPeriph + USB_OTG_Driver + USB_Device/Host_Library | §4 对照 |
| `01_Code/01_基于标准库修改/Project/USB_Device_Examples/VCP_Loopback/inc/usb_conf.h` | FIFO/PHY 宏（`:132-137` FIFO，`:143 ULPI_PHY_ENABLED`，`:126` 1012 word 备注） | §3.3 |
| `01_Code/01_基于标准库修改/Project/USB_Device_Examples/VCP_Loopback/src/usb_bsp.c` | 标准库版板级初始化（含 PE7 复位 0xfff） | §2.4-H3、§3 |
| `01_Code/01_基于标准库修改/Project/USB_Device_Examples/VCP_Loopback/MDK-ARM/Project.uvprojx` | FS/HS 双 target 与编译宏 | §5 |
| `01_Code/02_CubeMX生成代码/STM32F407_OTGHS_Device_VirtualPortCom_LoopBack/` | **HAL 版 HS + ULPI 参考工程**（PE7 复位、ULPI MspInit、PCD 参数） | §4.3、§4.4 — 本次最关键资料 |
| `01_Code/02_CubeMX生成代码/STM32F407_OTGFS_Device_VirtualPortCom_LoopBack/` | HAL 版 FS 参考工程 | §4.3 对照组 |
| `01_Code/02_CubeMX生成代码/{...CustomHID_LoopBack, OTGHS_Host_MSC}` | HID 回环 / Host MSC 例程 | 后续 HID、Host 需求可复用 |
| `01_Code/03_官方标准库/en.stm32_f105-07_f2_f4_usb-host-device_lib_v2.2.1.rar` | ST 官方原版库 | 核对参考工程是否原样 |
| `01_Code/04_USB速度测试/` | 4 个测速工程（FS/HS × HID/VCP） | §7 阶段 C 基线 |
| `03_上位机工具/{HID_RxTx_PC_Tool, HID_Speed_Test_PC_Tool}` | PC 侧工具 | 测速/回环验证 |

---

## 附：本工程相关代码位置速查

| 用途 | 位置 |
|---|---|
| USART1 引脚配置（需改） | `bsp/stm32/stm32f407-atk-explorer/board/CubeMX_Config/Src/stm32f4xx_hal_msp.c:726-781` |
| ULPI/FS 的 `HAL_PCD_MspInit`（死代码） | `bsp/stm32/stm32f407-atk-explorer/board/CubeMX_Config/Src/stm32f4xx_hal_msp.c` 中 `HAL_PCD_MspInit()` |
| 链接脚本 | `bsp/stm32/stm32f407-atk-explorer/board/linker_scripts/link.lds` |
| Flash 容量宏 | `bsp/stm32/stm32f407-atk-explorer/board/board.h` |
| 时钟树 | `bsp/stm32/stm32f407-atk-explorer/board/board.c`（`sys_stm32_clock_init(336, 8, 2, 7)`） |
| 参与编译的 board 源 | `bsp/stm32/stm32f407-atk-explorer/board/SConscript` |
| CherryUSB 配置 | `app/ramdump/transport/usb/common/usb_config.h` |
| DWC2 端口层 | `app/ramdump/transport/usb/port/dwc2/usb_dc_dwc2.c`（`:172-191` PHY 选择，`:590-600` 速度，`:631-648` FIFO，`:666` FIFO 断言） |
| 板级 glue + 轮询调度 | `app/ramdump/transport/usb/ramdump_usb_cdc.c`（`:250-273` low-level init，`:281-287` GCCFG，`:291` ISR） |
| RTT 侧 CherryUSB 配置（当前未启用） | `bsp/stm32/stm32f407-atk-explorer/board/usb_config.h`（`:266 // #define CONFIG_USB_HS`） |
