# Ramdump 实现设计方案 — RT-Thread + STM32F407

> **状态（2026-10 整理时标注）：历史设计稿，已被实际实现超越。**
> 本文档描述的是移植**计划**，不是当前代码现状。三处已知偏差：
> 1. 路径——通篇的 `components/ramdump/` 实际落在 `app/ramdump/`（与上游物理分离）；
> 2. 协议——文中引擎写 XMODEM，实际实现为 YMODEM（`app/ramdump/protocol/ymodem/ramdump_ymodem.c`）；
> 3. 阶段——第 0 章的 13 新增 / 4 PC 端 / 6 修改清单是当时的划分，实际文件以 `app/ramdump/` 为准。
>
> 当前现状请看根目录 `AGENTS.md` 与 `app/ramdump/AGENTS.md`；文首提到的原始框架设计见 `docs/reference/Ramdump方案设计文档.md`。

## 0. 文件变更清单

实现本方案涉及以下文件操作，按新增/修改分类列出。

### 0.1 新增文件（共 13 个）

| 文件路径 | 说明 | 所属阶段 |
|----------|------|---------|
| `components/ramdump/SConscript` | 构建脚本 | P0 |
| `components/ramdump/Kconfig` | 配置选项 | P0 |
| `components/ramdump/ramdump_config.h` | 平台相关配置（内存区域定义、传输方式、开关） | P1 |
| `components/ramdump/ramdump_exception.h` | ARM Cortex-M 异常现场结构体定义 | P2 |
| `components/ramdump/ramdump_exception.c` | 异常现场保存与恢复、魔数防重入 | P2 |
| `components/ramdump/ramdump_engine.h` | 转储引擎接口 | P1 |
| `components/ramdump/ramdump_engine.c` | 内存转储引擎（XMODEM 发送、CRC16） | P1 |
| `components/ramdump/ramdump_io.h` | IO 抽象接口 | P1 |
| `components/ramdump/ramdump_io.c` | IO 抽象（rt_device_t 封装） | P1 |
| `components/ramdump/ramdump_cli.h` | 崩溃后 CLI 接口 | P2 |
| `components/ramdump/ramdump_cli.c` | 崩溃后 CLI 实现（md/mw/ramdump/errorlog/reboot） | P2 |
| `components/ramdump/ramdump_storage.h` | 本地存储接口 | P3 |
| `components/ramdump/ramdump_storage.c` | 本地存储（SD/Flash 保存 dump 镜像） | P3 |

### 0.2 新增 PC 端工具（共 4 个）

| 文件路径 | 说明 | 所属阶段 |
|----------|------|---------|
| `tools/ramdump_analyzer/ramdump_analyzer.py` | 主分析脚本（加载镜像、ELF 符号、生成报告） | P4 |
| `tools/ramdump_analyzer/arm_backtrace.py` | ARM Thumb-2 调用栈回溯 | P4 |
| `tools/ramdump_analyzer/rtthread_parser.py` | RT-Thread 线程列表、栈使用率、IPC 解析 | P5 |
| `tools/ramdump_analyzer/exception_decoder.py` | ARM SCB 寄存器异常解码 | P4 |

### 0.3 修改文件（共 6 个）

| 文件路径 | 修改内容 | 所属阶段 |
|----------|---------|---------|
| `libcpu/arm/cortex-m4/cpuport.c` | 在 `rt_hw_hard_fault_exception()` 末尾插入 `ramdump_exception_save()` + `ramdump_enter()` 调用 | P2 |
| `bsp/stm32/stm32f407-atk-explorer/board/CubeMX_Config/Src/stm32f4xx_it.c` | 删除 `HardFault_Handler` 等 4 个空死循环 handler（或加条件编译保护） | P0 |
| `bsp/stm32/stm32f407-atk-explorer/board/board.c` | 在 `rt_hw_board_init()` 中使能 MemManage/BusFault/UsageFault 异常 | P0 |
| `bsp/stm32/stm32f407-atk-explorer/board/linker_scripts/link.lds` | 新增 `.noinit` 段（NOLOAD），存放异常现场信息 | P0 |
| `components/Kconfig` | 新增 `source "components/ramdump/Kconfig"` | P0 |
| `components/SConscript` | 新增 ramdump 组件的编译引用 | P0 |

### 0.4 不修改的文件

以下文件保持原样，不做任何修改：

| 文件路径 | 原因 |
|----------|------|
| `components/utilities/ymodem/` | 保持现有 YMODEM 实现不变（ramdump 引擎独立实现 XMODEM 发送，避免修改通用组件） |
| `components/finsh/` | 保持现有 MSH 不变（仅通过 `MSH_CMD_EXPORT` 注册命令） |
| `include/rtdef.h` | 不修改内核头文件 |
| `libcpu/arm/cortex-m4/context_gcc.S` | 不修改汇编入口（异常入口逻辑在 C 层 cpuport.c 中处理） |
| `components/drivers/serial/` | 不修改串口驱动（通过 rt_device_t 使用现有驱动） |

---

## 1. 概述

本文档基于根目录 `Ramdump方案设计文档.md` 中描述的 ramdump 框架，针对当前工程（RT-Thread v5.2.0 + STM32F407 Cortex-M4）给出详细的实现设计方案。原始方案运行于自定义 RISC-V 双核芯片，本文档将其核心思想适配到 ARM Cortex-M 单核 + RT-Thread 环境。

ramdump 的核心能力不变：CPU 异常或断言失败时，自动捕获异常现场，通过 UART + YMODEM 将内存镜像传输到 PC，供离线分析工具定位崩溃根因。

## 2. 当前工程现状分析

### 2.1 已有基础设施（可直接复用）

| 组件 | 位置 | 复用方式 |
|------|------|---------|
| **YMODEM 协议栈** | `components/utilities/ymodem/ymodem.c` | 直接使用 `rym_send_on_device()` API，通过 `rt_device_t` 抽象发送 |
| **串口驱动框架** | `components/drivers/serial/dev_serial.c` | 通过 `rt_device_find("uart2")` 获取设备句柄，用于 ramdump 数据传输 |
| **Finsh/MSH Shell** | `components/finsh/` | 在正常模式下注册 ramdump 相关命令（`ramdump`、`ramdump_test` 等） |
| **异常处理框架** | `libcpu/arm/cortex-m4/cpuport.c` | `rt_hw_hard_fault_exception()` 已实现详细的寄存器打印和故障诊断，在其末尾插入 `DTools_Dump()` 入口 |
| **DFS 文件系统** | `components/dfs/dfs_v2/` | 支持将 dump 镜像保存到 SD 卡或 SPI Flash，而非仅通过 UART 传输 |
| **FAL Flash 抽象层** | `components/fal/` | 可指定 dump 存储分区，崩溃后重启可以从 Flash 读取上次的 dump 数据 |
| **RT-Thread 内核对象** | `include/rtdef.h` | 线程遍历（`rt_object_get_information()`）、内存信息等均可直接使用 |

### 2.2 需要修复的问题

| 问题 | 位置 | 修复方式 |
|------|------|---------|
| **BSP 空 HardFault_Handler** | `bsp/stm32/stm32f407-atk-explorer/board/CubeMX_Config/Src/stm32f4xx_it.c` | 删除该文件中的 `HardFault_Handler` 等空死循环，让 libcpu 的版本生效 |
| **MemManage/BusFault/UsageFault 未使能** | SCB->SHCSR | 在 `rt_hw_board_init()` 中使能这些可配置故障异常 |
| **无异常现场保存机制** | 无 | 新增 `ramdump_exception` 结构体，在 `rt_hw_hard_fault_exception` 入口处保存 |
| **无 .noinit 保留区** | 链接脚本 | 新增 `.noinit` 段，存放异常现场信息，确保复位后不丢失 |

### 2.3 与原始方案的差异对比

| 维度 | 原始方案 (RISC-V 双核) | 当前方案 (ARM Cortex-M4) |
|------|----------------------|------------------------|
| **CPU 架构** | RISC-V RV32IMC | ARM Cortex-M4 (ARMv7E-M) |
| **核心数** | 双核 (AP+CP) | 单核 |
| **异常入口** | `exc_entry` (汇编) → `core_exception_handler` | `HardFault_Handler` → `rt_hw_hard_fault_exception` |
| **寄存器保存** | 软件逐条保存 32 个 GPR (IRQ_SAVE_CONTEXT) | 硬件自动压栈 8 个寄存器 (r0-r3, r12, lr, pc, xpsr) |
| **异常原因** | `mcause` / `mdcause` CSR 寄存器 | `SCB->CFSR` / `HFSR` 寄存器 |
| **故障地址** | `mtval` CSR 寄存器 | `SCB->MMFAR` / `BFAR` 寄存器 |
| **OS 类型** | 自定义 RTOS (osThread_t) | RT-Thread (rt_thread_t) |
| **断言机制** | `OS_ASSERT()` → `ecall` | `RT_ASSERT()` → 直接调用 `rt_hw_hard_fault_exception` 或 `while(1)` |
| **传输协议** | YMODEM + DIAG 协议 | YMODEM（优先），DIAG 可选 |
| **PC 端工具** | Trace32 脚本套件 (19 个 .cmm) | Python 脚本 + pyelftools（开源替代） |
| **内存布局** | IRAM/PSRAM/ILM/DLM/XIP | SRAM (128KB) + CCM (64KB) + Flash (1MB) |

## 3. 架构设计

### 3.1 分层架构

```
┌──────────────────────────────────────────────────────────┐
│  Layer 4: PC 端分析工具                                  │
│  ├─ ramdump_analyzer.py (Python + pyelftools)            │
│  │   ├─ 加载内存镜像 + ELF 符号                          │
│  │   ├─ 异常现场解码 (CFSR/HFSR)                         │
│  │   ├─ ARM Thumb-2 调用栈回溯                           │
│  │   ├─ RT-Thread 线程列表解析                           │
│  │   └─ 内存堆分析 (memheap)                             │
│  └─ YMODEM 接收器 (SecureCRT / TeraTerm / minicom)      │
└──────────────────────────────────────────────────────────┘
                          ▲
              YMODEM 协议 / 文件系统
                          ▼
┌──────────────────────────────────────────────────────────┐
│  Layer 3: 传输与存储层                                   │
│  ├─ ymodem_send.c: YMODEM 发送封装（复用 RT-Thread 的    │
│  │   rym_send_on_device，直接指定内存地址发送）           │
│  ├─ dump_storage.c: 本地存储（SD卡/SPI Flash 的镜像保存） │
│  └─ ramdump_io.c: IO 抽象（rt_device_t 统一接口）        │
└──────────────────────────────────────────────────────────┘
                          ▲
                          │
┌──────────────────────────────────────────────────────────┐
│  Layer 2: 核心引擎层                                     │
│  ├─ ramdump_exception.c: 异常现场保存（结构体 + 锁存）   │
│  ├─ ramdump_engine.c: 内存转储引擎（区域定义 + 批量传输） │
│  ├─ ramdump_cli.c: 崩溃后 CLI 命令（md/mw/ramdump/reboot）│
│  └─ ramdump_config.h: 配置（内存区域、传输方式、开关）   │
└──────────────────────────────────────────────────────────┘
                          ▲
                          │
┌──────────────────────────────────────────────────────────┐
│  Layer 1: 触发层                                         │
│  ├─ cpuport.c 修改: rt_hw_hard_fault_exception() 末尾    │
│  │   插入 ramdump_enter() 入口                           │
│  ├─ RT_ASSERT 钩子: 断言失败时记录信息后触发异常          │
│  └─ stm32f4xx_it.c 修改: 删除空 handler，使能故障异常    │
└──────────────────────────────────────────────────────────┘
```

### 3.2 数据流

```
CPU 异常 (HardFault/MemManage/BusFault/UsageFault)
  │
  ▼
HardFault_Handler (context_gcc.S)
  │  ├─ 从 MSP/PSP 获取异常现场
  │  ├─ 压栈 r4-r11 + EXC_RETURN
  │  └─ call rt_hw_hard_fault_exception
  │
  ▼
rt_hw_hard_fault_exception (cpuport.c)
  │  ├─ 打印异常类型/故障地址/寄存器快照 (已有)
  │  ├─ 打印当前线程名和调用栈 (已有)
  │  │
  │  ├─ ★ 新增: ramdump_exception_save() 保存异常现场
  │  │    ├─ 硬件压栈帧指针 (r0-r3,r12,lr,pc,xpsr)
  │  │    ├─ SCB 寄存器 (CFSR/HFSR/MMFAR/BFAR)
  │  │    ├─ 当前线程信息 (rt_thread_t->name/sp/entry)
  │  │    └─ 写入 .noinit 段（确保复位后不丢失）
  │  │
  │  └─ ★ 新增: ramdump_enter() 进入 dump 模式
  │
  ▼
ramdump_enter()
  │  ├─ 关中断
  │  ├─ 打印崩溃摘要
  │  ├─ ramdump_cli_loop()   ← 交互式 CLI
  │  │    ├─ "ramdump" → YMODEM 发送全部区域
  │  │    ├─ "ramdump_storage" → 保存到 SD/Flash
  │  │    ├─ "md <addr> <len>" → 内存查看
  │  │    ├─ "mw <addr> <val>" → 内存写入
  │  │    ├─ "errorlog" → 显示异常信息
  │  │    └─ "reboot" → 系统复位
  │  └─ 永不返回 (除非 reboot 命令)
```

### 3.3 目录结构

```
rt-thread-ros/
├── components/
│   └── ramdump/                          # ★ 新增 ramdump 组件
│       ├── SConscript                     # 构建脚本
│       ├── Kconfig                        # 配置选项
│       ├── ramdump_config.h               # 平台相关配置（内存区域定义）
│       ├── ramdump_exception.h            # 异常现场结构体定义
│       ├── ramdump_exception.c            # 异常现场保存与恢复
│       ├── ramdump_engine.h               # 转储引擎接口
│       ├── ramdump_engine.c               # 转储引擎实现
│       ├── ramdump_io.h                   # IO 抽象接口
│       ├── ramdump_io.c                   # IO 抽象（rt_device_t 封装）
│       ├── ramdump_cli.h                  # 崩溃后 CLI 接口
│       ├── ramdump_cli.c                  # 崩溃后 CLI 实现
│       ├── ramdump_storage.h              # 本地存储接口
│       ├── ramdump_storage.c              # 本地存储（SD/Flash）
│       └── ramdump_ymodem.h               # YMODEM 发送封装
│
├── bsp/stm32/stm32f407-atk-explorer/
│   ├── board/
│   │   ├── linker_scripts/
│   │   │   └── link.lds                   # ★ 修改: 新增 .noinit 段
│   │   └── CubeMX_Config/Src/
│   │       └── stm32f4xx_it.c             # ★ 修改: 删除空 handler
│   └── board.c / board.h                  # ★ 修改: 使能故障异常
│
├── libcpu/arm/cortex-m4/
│   └── cpuport.c                          # ★ 修改: 异常入口插入 ramdump_enter()
│
└── tools/
    └── ramdump_analyzer/                  # ★ 新增 PC 端分析工具
        ├── ramdump_analyzer.py            # 主分析脚本
        ├── arm_backtrace.py               # ARM Thumb-2 调用栈回溯
        ├── rtthread_parser.py             # RT-Thread 结构体解析
        ├── exception_decoder.py           # ARM 异常解码
        └── requirements.txt               # Python 依赖
```

## 4. 详细实现方案

### 4.1 Phase 1: 基础框架搭建（传输通道验证）

**目标**：不依赖异常处理，通过 MSH 命令手动触发内存转储，验证 UART + YMODEM 传输通道。

#### 4.1.1 内存区域配置 (`ramdump_config.h`)

```c
// ramdump_config.h — STM32F407ZG 内存布局
#ifndef RAMDUMP_CONFIG_H__
#define RAMDUMP_CONFIG_H__

#include <rtthread.h>

// ===== STM32F407ZG 内存区域定义 =====
#define RAMDUMP_REGION_SRAM_ADDR    0x20000000
#define RAMDUMP_REGION_SRAM_SIZE    (128 * 1024)    // 128KB SRAM

#define RAMDUMP_REGION_CCM_ADDR     0x10000000
#define RAMDUMP_REGION_CCM_SIZE     (64 * 1024)     // 64KB CCM RAM

#define RAMDUMP_REGION_FLASH_ADDR   0x08000000
#define RAMDUMP_REGION_FLASH_SIZE   (1024 * 1024)   // 1MB Flash

// ===== 转储策略 =====
// 默认转储 SRAM + CCM，Flash 按需指定
#define RAMDUMP_DEFAULT_REGIONS     \
    {                                \
        {RAMDUMP_REGION_SRAM_ADDR,  RAMDUMP_REGION_SRAM_SIZE,  "SRAM.bin"},  \
        {RAMDUMP_REGION_CCM_ADDR,   RAMDUMP_REGION_CCM_SIZE,   "CCM.bin"},   \
    }

// 区域描述结构体
typedef struct {
    uint32_t addr;      // 起始地址
    uint32_t size;      // 区域大小（字节）
    const char *name;   // 文件名（YMODEM 传输时使用）
} ramdump_region_t;

// ===== 传输配置 =====
#define RAMDUMP_UART_DEVICE     "uart2"     // 用于 ramdump 传输的串口设备
#define RAMDUMP_UART_BAUDRATE   921600      // 高速传输波特率

// ===== 功能开关 =====
#define RAMDUMP_ENABLE_LOCAL_STORAGE  1   // 支持保存到 SD/Flash
#define RAMDUMP_ENABLE_EXCEPTION_AUTO 1   // 异常时自动进入 dump

#endif // RAMDUMP_CONFIG_H__
```

#### 4.1.2 IO 抽象层 (`ramdump_io.c`)

利用 RT-Thread 的设备框架，将串口、文件系统等统一抽象：

```c
// ramdump_io.c — 基于 RT-Thread 设备框架的 IO 封装
#include <rtthread.h>
#include <rtdevice.h>
#include "ramdump_io.h"

static rt_device_t g_ramdump_device = RT_NULL;

// 初始化 ramdump IO 通道
int ramdump_io_init(const char *dev_name, uint32_t baudrate)
{
    g_ramdump_device = rt_device_find(dev_name);
    if (g_ramdump_device == RT_NULL) {
        rt_kprintf("[ramdump] device %s not found\n", dev_name);
        return -RT_ERROR;
    }

    // 配置串口参数
    struct serial_configure config = RT_SERIAL_CONFIG_DEFAULT;
    config.baud_rate = baudrate;
    rt_device_control(g_ramdump_device, RT_DEVICE_CTRL_CONFIG, &config);

    // 打开设备（中断模式接收，轮询模式发送）
    rt_device_open(g_ramdump_device, RT_DEVICE_FLAG_INT_RX);

    rt_kprintf("[ramdump] IO channel ready: %s @ %d bps\n", dev_name, baudrate);
    return RT_EOK;
}

// 发送一个字节
void ramdump_putc(uint8_t ch)
{
    if (g_ramdump_device) {
        rt_device_write(g_ramdump_device, 0, &ch, 1);
    }
}

// 接收一个字节（带超时）
int ramdump_getc(uint32_t timeout_ms)
{
    uint8_t ch;
    if (g_ramdump_device) {
        if (rt_device_read(g_ramdump_device, 0, &ch, 1) == 1) {
            return ch;
        }
    }
    rt_thread_mdelay(1);  // 让出 CPU
    return -1;
}

// 批量发送
void ramdump_put_bytes(const uint8_t *data, uint32_t len)
{
    if (g_ramdump_device) {
        rt_device_write(g_ramdump_device, 0, data, len);
    }
}
```

#### 4.1.3 YMODEM 发送封装

RT-Thread 的 YMODEM 组件 `rym_send_on_device()` 需要通过文件系统路径读取文件。对于 ramdump 场景，需要直接从内存地址发送。有两种实现思路：

**方案 A（推荐）**：直接使用 YMODEM 协议底层 API，跳过文件系统中间层。

```c
// ramdump_engine.c — 直接内存到 YMODEM 的发送
#include "ymodem.h"

// 回调：YMODEM 读取数据块
static rt_err_t _ramdump_ymodem_read(rt_uint8_t *buf, rt_size_t offset,
                                      rt_size_t len, void *user_data)
{
    ramdump_region_t *region = (ramdump_region_t *)user_data;
    if (offset + len > region->size) {
        len = region->size - offset;
    }
    rt_memcpy(buf, (void *)(region->addr + offset), len);
    return len;
}

// 发送单个内存区域
static rt_err_t ramdump_send_region(ramdump_region_t *region)
{
    struct rym_ctx ctx;
    rt_err_t res;

    // 初始化 YMODEM 上下文
    res = rym_send_init(&ctx, region->name, region->size,
                         _ramdump_ymodem_read, region);
    if (res != RT_EOK) return res;

    // 等待握手
    // ... 使用 ramdump_getc/ramdump_putc 进行 YMODEM 协议交互
    return res;
}
```

**方案 B**：将内存区域注册为临时块设备，通过文件系统挂载后发送。实现较复杂，不推荐。

#### 4.1.4 MSH 命令注册

在正常运行时通过 MSH 命令手动触发 dump：

```c
// ramdump_cli.c — MSH 命令
#include <finsh.h>

static int cmd_ramdump(int argc, char **argv)
{
    rt_kprintf("[ramdump] Starting manual dump...\n");

    ramdump_io_init(RAMDUMP_UART_DEVICE, RAMDUMP_UART_BAUDRATE);

    ramdump_region_t regions[] = RAMDUMP_DEFAULT_REGIONS;
    int count = sizeof(regions) / sizeof(regions[0]);

    for (int i = 0; i < count; i++) {
        rt_kprintf("[ramdump] Sending %s (0x%08x, %d bytes)...\n",
                   regions[i].name, regions[i].addr, regions[i].size);
        ramdump_send_region(&regions[i]);
    }

    rt_kprintf("[ramdump] Done.\n");
    return 0;
}
MSH_CMD_EXPORT(cmd_ramdump, ramdump: manual memory dump via YMODEM);

static int cmd_ramdump_test(int argc, char **argv)
{
    // 故意触发 HardFault，验证异常入口
    rt_kprintf("[ramdump] Triggering test fault...\n");
    rt_thread_mdelay(100);

    // 触发 UsageFault: 未定义指令
    // 或触发 BusFault: 访问非法地址
    *(volatile uint32_t *)0xFFFFFFFF = 0xDEADBEEF;

    return 0;
}
MSH_CMD_EXPORT(cmd_ramdump_test, ramdump_test: trigger a test fault);
```

### 4.2 Phase 2: 异常入口对接

**目标**：CPU 异常时自动进入 ramdump 模式，PC 端能定位崩溃地址和异常原因。

#### 4.2.1 异常现场保存结构体 (`ramdump_exception.h`)

```c
// ramdump_exception.h — ARM Cortex-M 异常现场记录
#ifndef RAMDUMP_EXCEPTION_H__
#define RAMDUMP_EXCEPTION_H__

#include <rtthread.h>

// ARM Cortex-M 硬件自动压栈的帧结构（8 个寄存器，32 字节）
typedef struct __attribute__((packed)) {
    uint32_t r0;
    uint32_t r1;
    uint32_t r2;
    uint32_t r3;
    uint32_t r12;
    uint32_t lr;       // 链接寄存器（EXC_RETURN 值在进入 handler 时在此）
    uint32_t pc;       // 崩溃指令地址
    uint32_t xpsr;     // 程序状态寄存器
} arm_hw_stack_frame_t;

// 异常现场记录（存放在 .noinit 段，确保复位后不丢失）
typedef struct __attribute__((packed)) {
    uint32_t magic;                // 魔数: 0x52414D44 ("RAMD")
    uint32_t fault_type;           // 异常类型: 0=HardFault, 1=MemManage, 2=BusFault, 3=UsageFault
    uint32_t cfsr;                 // SCB->CFSR (可配置故障状态寄存器)
    uint32_t hfsr;                 // SCB->HFSR (硬故障状态寄存器)
    uint32_t mmfar;                // SCB->MMFAR (MemManage 故障地址)
    uint32_t bfar;                 // SCB->BFAR (BusFault 故障地址)
    uint32_t fpscr;                // FPSCR (浮点状态，如果启用了 FPU)
    uint32_t hw_frame_ptr;        // 硬件压栈帧指针（MSP/PSP 在异常入口时的值）
    uint32_t current_thread_sp;   // 当前线程的 SP（崩溃时的栈位置）
    char     thread_name[RT_NAME_MAX];  // 崩溃线程名称
    uint32_t tick;                 // 崩溃时的系统 tick
    uint32_t checksum;            // 校验和
} ramdump_exception_t;

// 异常类型枚举
enum {
    RAMDUMP_FAULT_HARD      = 0,
    RAMDUMP_FAULT_MEMMANAGE = 1,
    RAMDUMP_FAULT_BUS       = 2,
    RAMDUMP_FAULT_USAGE     = 3,
    RAMDUMP_FAULT_ASSERT    = 4,  // 软件断言
};

// 全局异常现场指针（由链接脚本固定在 .noinit 段）
extern ramdump_exception_t g_ramdump_exception;

// API
void ramdump_exception_save(uint32_t fault_type,
                             uint32_t hw_frame_ptr,
                             rt_thread_t current_thread);
int  ramdump_exception_is_valid(void);
void ramdump_exception_print(void);
void ramdump_exception_clear(void);

#endif // RAMDUMP_EXCEPTION_H__
```

#### 4.2.2 异常现场保存实现 (`ramdump_exception.c`)

```c
// ramdump_exception.c
#include "ramdump_exception.h"
#include <rtthread.h>

// 放置在 .noinit 段，确保复位后数据不丢失
#if defined(__CC_ARM) || defined(__CLANG_ARM)
    __attribute__((section(".noinit")))
#elif defined(__GNUC__)
    __attribute__((section(".noinit")))
#endif
ramdump_exception_t g_ramdump_exception;

// 保存异常现场
void ramdump_exception_save(uint32_t fault_type,
                             uint32_t hw_frame_ptr,
                             rt_thread_t current_thread)
{
    // 防重入
    if (g_ramdump_exception.magic == 0x52414D44) {
        return;  // 已保存过，不覆盖第一次的现场
    }

    g_ramdump_exception.magic      = 0x52414D44;
    g_ramdump_exception.fault_type = fault_type;
    g_ramdump_exception.cfsr       = SCB->CFSR;
    g_ramdump_exception.hfsr       = SCB->HFSR;
    g_ramdump_exception.mmfar      = SCB->MMFAR;
    g_ramdump_exception.bfar       = SCB->BFAR;
    g_ramdump_exception.fpscr      = 0;  // FPU 状态后续扩展
    g_ramdump_exception.hw_frame_ptr = hw_frame_ptr;
    g_ramdump_exception.tick       = rt_tick_get();

    if (current_thread) {
        g_ramdump_exception.current_thread_sp = (uint32_t)current_thread->sp;
        rt_strncpy(g_ramdump_exception.thread_name,
                   current_thread->name, RT_NAME_MAX);
    }

    // 计算校验和
    uint32_t sum = 0;
    uint32_t *p = (uint32_t *)&g_ramdump_exception;
    for (int i = 0; i < sizeof(ramdump_exception_t) / 4 - 1; i++) {
        sum ^= p[i];
    }
    g_ramdump_exception.checksum = sum;
}

// 检查异常现场是否有效
int ramdump_exception_is_valid(void)
{
    if (g_ramdump_exception.magic != 0x52414D44) return 0;

    uint32_t sum = 0;
    uint32_t *p = (uint32_t *)&g_ramdump_exception;
    for (int i = 0; i < sizeof(ramdump_exception_t) / 4 - 1; i++) {
        sum ^= p[i];
    }
    return (sum == g_ramdump_exception.checksum);
}

// 打印异常信息
void ramdump_exception_print(void)
{
    if (!ramdump_exception_is_valid()) {
        rt_kprintf("[ramdump] No valid exception record.\n");
        return;
    }

    const char *fault_names[] = {
        "HardFault", "MemManage", "BusFault", "UsageFault", "Assert"
    };

    rt_kprintf("\n===== RAMDUMP EXCEPTION RECORD =====\n");
    rt_kprintf("Fault Type : %s\n", fault_names[g_ramdump_exception.fault_type]);
    rt_kprintf("Thread     : %s\n", g_ramdump_exception.thread_name);
    rt_kprintf("Tick       : %d\n", g_ramdump_exception.tick);
    rt_kprintf("CFSR       : 0x%08x\n", g_ramdump_exception.cfsr);
    rt_kprintf("HFSR       : 0x%08x\n", g_ramdump_exception.hfsr);
    rt_kprintf("MMFAR      : 0x%08x\n", g_ramdump_exception.mmfar);
    rt_kprintf("BFAR       : 0x%08x\n", g_ramdump_exception.bfar);
    rt_kprintf("Frame @    : 0x%08x\n", g_ramdump_exception.hw_frame_ptr);

    // 解码硬件压栈帧
    arm_hw_stack_frame_t *frame =
        (arm_hw_stack_frame_t *)g_ramdump_exception.hw_frame_ptr;
    rt_kprintf("  r0=0x%08x r1=0x%08x r2=0x%08x r3=0x%08x\n",
               frame->r0, frame->r1, frame->r2, frame->r3);
    rt_kprintf("  r12=0x%08x lr=0x%08x pc=0x%08x xpsr=0x%08x\n",
               frame->r12, frame->lr, frame->pc, frame->xpsr);
    rt_kprintf("=====================================\n\n");
}

void ramdump_exception_clear(void)
{
    rt_memset(&g_ramdump_exception, 0, sizeof(ramdump_exception_t));
}
```

#### 4.2.3 修改 cpuport.c（异常入口）

在 `rt_hw_hard_fault_exception()` 末尾，`while(1)` 之前插入 ramdump 入口：

```c
// libcpu/arm/cortex-m4/cpuport.c — 修改点

void rt_hw_hard_fault_exception(struct exception_stack_frame *exception_stack)
{
    // ... 现有的冗长异常诊断代码保持不变 ...

    // ★★★ 新增: 保存 ramdump 异常现场 ★★★
    #ifdef RT_USING_RAMDUMP
    {
        extern void ramdump_exception_save(uint32_t, uint32_t, rt_thread_t);
        ramdump_exception_save(RAMDUMP_FAULT_HARD,
                               (uint32_t)exception_stack,
                               rt_thread_self());
    }
    #endif

    // ★★★ 新增: 进入 ramdump 模式 ★★★
    #ifdef RT_USING_RAMDUMP
    {
        extern void ramdump_enter(void);
        ramdump_enter();
    }
    #endif

    // 如果 ramdump 未启用或返回了，进入死循环
    while (1);
}
```

#### 4.2.4 修改 stm32f4xx_it.c（删除空 handler）

删除 `stm32f4xx_it.c` 中的空死循环 handler，让 libcpu 的弱符号版本生效：

```c
// bsp/stm32/stm32f407-atk-explorer/board/CubeMX_Config/Src/stm32f4xx_it.c

// 删除以下函数（或注释掉，保留为弱引用）：
// void HardFault_Handler(void) { while(1); }
// void MemManage_Handler(void) { while(1); }
// void BusFault_Handler(void) { while(1); }
// void UsageFault_Handler(void) { while(1); }
```

同时在 `board.c` 的 `rt_hw_board_init()` 中使能可配置故障异常：

```c
// board.c — 使能 MemManage/BusFault/UsageFault
void rt_hw_board_init(void)
{
    // ... 现有初始化代码 ...

    // ★ 新增: 使能可配置故障异常
    SCB->SHCSR |= SCB_SHCSR_MEMFAULTENA_Msk   // MemManage
               | SCB_SHCSR_BUSFAULTENA_Msk    // BusFault
               | SCB_SHCSR_USGFAULTENA_Msk;   // UsageFault
}
```

#### 4.2.5 修改链接脚本（新增 .noinit 段）

```ld
/* link.lds — 新增 .noinit 段 */
SECTIONS
{
    /* ... 现有段 ... */

    .noinit (NOLOAD) :
    {
        . = ALIGN(4);
        PROVIDE(__noinit_start = .);
        KEEP(*(.noinit))
        KEEP(*(.noinit*))
        . = ALIGN(4);
        PROVIDE(__noinit_end = .);
    } > RAM

    /* ... 其余段 ... */
}
```

### 4.3 Phase 3: 崩溃后 CLI 与转储引擎

**目标**：崩溃后提供交互式命令行，支持内存查看、按需转储、系统复位。

#### 4.3.1 崩溃后 CLI (`ramdump_cli.c`)

```c
// ramdump_cli.c — 崩溃后交互式命令行
#include <rtthread.h>
#include "ramdump_cli.h"
#include "ramdump_exception.h"
#include "ramdump_engine.h"
#include "ramdump_io.h"
#include "ramdump_config.h"

#define CLI_PROMPT     "@ramdump> "
#define CLI_BUF_SIZE   128
#define CLI_MAX_ARGS   8

static char cli_buf[CLI_BUF_SIZE];

// 命令处理函数
static int cli_cmd_md(int argc, char **argv);
static int cli_cmd_mw(int argc, char **argv);
static int cli_cmd_ramdump(int argc, char **argv);
static int cli_cmd_errorlog(int argc, char **argv);
static int cli_cmd_ramdump_storage(int argc, char **argv);
static int cli_cmd_reboot(int argc, char **argv);
static int cli_cmd_help(int argc, char **argv);

typedef struct {
    const char *name;
    const char *desc;
    int (*func)(int argc, char **argv);
} cli_cmd_t;

static const cli_cmd_t cli_commands[] = {
    {"md",     "md <addr> [len]          - Memory display (hex dump)",      cli_cmd_md},
    {"mw",     "mw <addr> <val>          - Memory write (32-bit)",          cli_cmd_mw},
    {"ramdump","ramdump                  - YMODEM send all memory regions", cli_cmd_ramdump},
    {"ramdump_storage",
               "ramdump_storage          - Save dump to local storage",     cli_cmd_ramdump_storage},
    {"errorlog","errorlog                - Show exception info",            cli_cmd_errorlog},
    {"reboot", "reboot                   - Reset system",                   cli_cmd_reboot},
    {"help",   "help                     - Show this help",                 cli_cmd_help},
    {NULL, NULL, NULL}
};

// 崩溃后 CLI 主循环
void ramdump_cli_loop(void)
{
    ramdump_io_init(RAMDUMP_UART_DEVICE, RAMDUMP_UART_BAUDRATE);

    // 打印崩溃摘要
    ramdump_exception_print();

    // 主循环
    while (1) {
        ramdump_put_bytes((uint8_t *)CLI_PROMPT, sizeof(CLI_PROMPT) - 1);

        // 读取一行
        int idx = 0;
        while (idx < CLI_BUF_SIZE - 1) {
            int ch = ramdump_getc(1000);  // 1 秒超时
            if (ch < 0) continue;         // 超时，继续等待

            if (ch == '\r' || ch == '\n') {
                ramdump_putc('\r');
                ramdump_putc('\n');
                break;
            }
            if (ch == '\b' || ch == 0x7F) {
                if (idx > 0) {
                    idx--;
                    ramdump_putc('\b');
                    ramdump_putc(' ');
                    ramdump_putc('\b');
                }
                continue;
            }
            cli_buf[idx++] = (char)ch;
            ramdump_putc((uint8_t)ch);
        }
        cli_buf[idx] = '\0';

        if (idx == 0) continue;

        // 解析命令
        char *argv[CLI_MAX_ARGS];
        int argc = 0;
        char *tok = cli_buf;
        while (*tok == ' ') tok++;  // 跳过前导空格
        while (*tok && argc < CLI_MAX_ARGS) {
            argv[argc++] = tok;
            while (*tok && *tok != ' ') tok++;
            if (*tok) { *tok = '\0'; tok++; }
            while (*tok == ' ') tok++;
        }

        if (argc == 0) continue;

        // 查找并执行命令
        int found = 0;
        for (const cli_cmd_t *cmd = cli_commands; cmd->name; cmd++) {
            if (rt_strcmp(argv[0], cmd->name) == 0) {
                cmd->func(argc, argv);
                found = 1;
                break;
            }
        }
        if (!found) {
            ramdump_put_bytes((uint8_t *)"Unknown command. Type 'help'.\r\n", 34);
        }
    }
}
```

#### 4.3.2 转储引擎 (`ramdump_engine.c`)

```c
// ramdump_engine.c — 内存转储引擎
#include "ramdump_engine.h"
#include "ramdump_config.h"
#include "ramdump_io.h"

// 默认转储区域（编译时确定，可在运行时扩展）
static const ramdump_region_t g_default_regions[] = RAMDUMP_DEFAULT_REGIONS;
#define DEFAULT_REGION_COUNT  (sizeof(g_default_regions) / sizeof(g_default_regions[0]))

// 发送单个内存区域（YMODEM 方式）
// 此处使用简化的 XMODEM-1K 协议，可替换为完整 YMODEM
static int ramdump_send_region_xmodem(const ramdump_region_t *region)
{
    uint8_t buf[1024 + 5];  // STX + seq + ~seq + 1KB data + CRC16
    uint32_t offset = 0;
    uint8_t seq = 1;

    // 等待接收方发送 'C' 启动传输
    ramdump_put_bytes((uint8_t *)"Waiting for XMODEM receiver...\r\n", 33);
    int ch;
    do {
        ch = ramdump_getc(100);
        if (ch < 0) {
            ramdump_putc('.');
            continue;
        }
    } while (ch != 'C' && ch != 'c');

    // 发送文件信息包（Block 0）
    rt_memset(buf, 0, 128);
    rt_snprintf((char *)buf, 128, "%s%c%d", region->name, 0, region->size);
    buf[0] = 0x01;  // SOH
    buf[1] = 0x00;  // Block 0
    buf[2] = 0xFF;  // ~Block 0
    ramdump_put_bytes(buf, 128 + 3 + 2);  // SOH + 128 + CRC16

    // 等待 ACK
    ch = ramdump_getc(5000);
    if (ch != 0x06) return -1;

    // 逐块发送数据
    while (offset < region->size) {
        uint32_t chunk_size = (region->size - offset > 1024) ?
                               1024 : (region->size - offset);

        buf[0] = 0x02;  // STX (1024 字节块)
        buf[1] = seq;
        buf[2] = (uint8_t)(~seq);

        rt_memcpy(&buf[3], (void *)(region->addr + offset), chunk_size);

        // 不足 1024 字节时填充 0x1A (CPM EOF)
        if (chunk_size < 1024) {
            rt_memset(&buf[3 + chunk_size], 0x1A, 1024 - chunk_size);
        }

        // CRC16 计算
        uint16_t crc = ramdump_crc16(&buf[3], 1024);
        buf[1027] = (crc >> 8) & 0xFF;
        buf[1028] = crc & 0xFF;

        ramdump_put_bytes(buf, 1029);

        // 等待 ACK
        ch = ramdump_getc(5000);
        if (ch != 0x06) {
            return -1;  // NAK 或超时
        }

        offset += 1024;
        seq++;
    }

    // 发送 EOT
    buf[0] = 0x04;  // EOT
    ramdump_put_bytes(buf, 1);
    ch = ramdump_getc(5000);
    if (ch != 0x06) return -1;

    return 0;
}

// 转储所有默认区域
int ramdump_dump_all(void)
{
    ramdump_region_t regions[] = RAMDUMP_DEFAULT_REGIONS;
    int count = sizeof(regions) / sizeof(regions[0]);

    ramdump_put_bytes((uint8_t *)"\r\n=== RAMDUMP START ===\r\n", 25);

    for (int i = 0; i < count; i++) {
        char msg[64];
        rt_snprintf(msg, sizeof(msg), "\r\n[%d/%d] Sending %s (0x%08x, %d bytes)...\r\n",
                    i + 1, count, regions[i].name, regions[i].addr, regions[i].size);
        ramdump_put_bytes((uint8_t *)msg, rt_strlen(msg));

        int ret = ramdump_send_region_xmodem(&regions[i]);
        if (ret != 0) {
            ramdump_put_bytes((uint8_t *)"FAILED!\r\n", 9);
            return -1;
        }
        ramdump_put_bytes((uint8_t *)"OK\r\n", 4);
    }

    ramdump_put_bytes((uint8_t *)"=== RAMDUMP COMPLETE ===\r\n", 27);
    return 0;
}

// 转储指定区域
int ramdump_dump_region(uint32_t addr, uint32_t size)
{
    ramdump_region_t region = {
        .addr = addr,
        .size = size,
        .name = "custom.bin"
    };
    return ramdump_send_region_xmodem(&region);
}

// CRC16 计算（XMODEM 标准）
static uint16_t ramdump_crc16(const uint8_t *data, uint32_t len)
{
    uint16_t crc = 0;
    while (len--) {
        crc ^= (uint16_t)(*data++) << 8;
        for (int i = 0; i < 8; i++) {
            if (crc & 0x8000) {
                crc = (crc << 1) ^ 0x1021;
            } else {
                crc <<= 1;
            }
        }
    }
    return crc;
}
```

### 4.4 Phase 4: 本地存储与高级功能

**目标**：支持将 dump 镜像保存到 SD 卡或 SPI Flash，崩溃后重启可从本地读取。

#### 4.4.1 本地存储 (`ramdump_storage.c`)

```c
// ramdump_storage.c — 将 dump 保存到本地存储
#include <rtthread.h>
#include <dfs.h>
#include <dfs_file.h>
#include "ramdump_storage.h"
#include "ramdump_config.h"

// 保存 dump 到文件系统（SD 卡）
int ramdump_storage_save_to_fs(const char *mount_point)
{
    char path[256];
    char timestamp[32];
    time_t now = rt_tick_get() / RT_TICK_PER_SECOND;

    rt_snprintf(timestamp, sizeof(timestamp), "%d", (int)now);
    rt_snprintf(path, sizeof(path), "%s/ramdump_%s", mount_point, timestamp);

    // 创建目录
    mkdir(path, 0);

    ramdump_region_t regions[] = RAMDUMP_DEFAULT_REGIONS;
    int count = sizeof(regions) / sizeof(regions[0]);

    for (int i = 0; i < count; i++) {
        char filepath[300];
        rt_snprintf(filepath, sizeof(filepath), "%s/%s", path, regions[i].name);

        int fd = open(filepath, O_WRONLY | O_CREAT | O_TRUNC, 0666);
        if (fd < 0) {
            rt_kprintf("[ramdump] Failed to create %s\n", filepath);
            continue;
        }

        write(fd, (void *)regions[i].addr, regions[i].size);
        close(fd);

        rt_kprintf("[ramdump] Saved %s (%d bytes) to %s\n",
                   regions[i].name, regions[i].size, filepath);
    }

    // 保存异常信息文本文件
    {
        char errfile[300];
        rt_snprintf(errfile, sizeof(errfile), "%s/exception.txt", path);
        int fd = open(errfile, O_WRONLY | O_CREAT | O_TRUNC, 0666);
        if (fd >= 0) {
            char buf[512];
            ramdump_exception_t *e = &g_ramdump_exception;
            int len = rt_snprintf(buf, sizeof(buf),
                "Fault Type: %d\n"
                "Thread: %s\n"
                "Tick: %d\n"
                "CFSR: 0x%08x\n"
                "HFSR: 0x%08x\n"
                "MMFAR: 0x%08x\n"
                "BFAR: 0x%08x\n"
                "Frame @: 0x%08x\n",
                e->fault_type, e->thread_name, e->tick,
                e->cfsr, e->hfsr, e->mmfar, e->bfar,
                e->hw_frame_ptr);
            write(fd, buf, len);
            close(fd);
        }
    }

    rt_kprintf("[ramdump] All files saved to %s\n", path);
    return RT_EOK;
}
```

### 4.5 Kconfig 配置

```kconfig
# components/ramdump/Kconfig
menu "Ramdump Configuration"

config RT_USING_RAMDUMP
    bool "Enable ramdump support"
    default n
    help
        Enable ramdump to capture memory dumps on system crashes.
        Requires YMODEM component and UART device.

if RT_USING_RAMDUMP

config RAMDUMP_UART_DEVICE
    string "UART device name for ramdump"
    default "uart2"
    help
        The UART device used for ramdump data transfer.

config RAMDUMP_UART_BAUDRATE
    int "UART baudrate for ramdump"
    default 921600
    help
        High baudrate recommended for faster dump transfer.

config RAMDUMP_ENABLE_STORAGE
    bool "Enable local storage (SD/Flash) for dump"
    default n
    depends on RT_USING_DFS
    help
        Save dump images to local storage instead of UART only.

config RAMDUMP_STORAGE_PATH
    string "Local storage mount point"
    default "/sd"
    depends on RAMDUMP_ENABLE_STORAGE
    help
        Mount point where dump files will be saved.

config RAMDUMP_AUTO_ENTER
    bool "Auto enter ramdump on exception"
    default y
    help
        Automatically enter ramdump CLI when a fault occurs.
        If disabled, exception info is saved but system reboots directly.

config RAMDUMP_ENABLE_CLI
    bool "Enable ramdump MSH commands"
    default y
    help
        Register ramdump and ramdump_test commands in MSH shell.

endif  # RT_USING_RAMDUMP

endmenu
```

### 4.6 SConscript 构建脚本

```python
# components/ramdump/SConscript
from building import *

cwd = GetCurrentDir()
src = []
CPPPATH = [cwd]

if GetDepend('RT_USING_RAMDUMP'):
    src += [
        'ramdump_exception.c',
        'ramdump_engine.c',
        'ramdump_io.c',
        'ramdump_cli.c',
    ]

    if GetDepend('RAMDUMP_ENABLE_STORAGE'):
        src += ['ramdump_storage.c']

group = DefineGroup('ramdump', src, depend=['RT_USING_RAMDUMP'],
                    CPPPATH=CPPPATH)

Return('group')
```

## 5. 关键设计决策

### 5.1 为什么用 .noinit 段而非全局变量

异常发生时，系统可能处于任意状态。全局变量（在 .bss 或 .data 段）在复位后会被清零或重新初始化，之前的异常现场信息会丢失。.noinit 段在复位后保持不变，即使系统在 dump 过程中崩溃并复位，PC 端仍可通过 JTAG/SWD 读取上次的异常现场。

### 5.2 为什么检查魔数防重入

双重故障（在 HardFault 处理过程中再次发生异常）是 Cortex-M 上常见的场景。如果 `g_ramdump_exception.magic` 已被设置，说明当前异常是嵌套的，应保留第一次的现场（最原始的错误现场），不覆盖。

### 5.3 为什么用 MSH 命令而非独立的 CLI 线程

崩溃后操作系统已经不可靠（调度器暂停、中断关闭、其他线程栈可能损坏），此时不能依赖 RT-Thread 的线程调度。ramdump CLI 运行在异常上下文中（关中断），使用轮询方式直接读写 UART 寄存器，不依赖任何 OS 服务。

### 5.4 PC 端分析工具选择

原始方案使用 Trace32（商业软件，昂贵）。本方案采用 Python 开源替代：

| 功能 | Trace32 脚本 | Python 替代 |
|------|------------|------------|
| 加载镜像 | restore.cmm (Data.LOAD.Binary) | `numpy.memmap()` / 直接读取 `.bin` 文件 |
| 符号恢复 | Data.LOAD.Elf | `pyelftools` 解析 ELF 符号表 |
| 栈帧恢复 | frame.cmm (Register.Set) | `struct.unpack` 解析硬件压栈帧 |
| 异常解码 | errinfo.cmm (mcause 查表) | `exception_decoder.py` (SCB 寄存器解码) |
| 调用栈回溯 | backtrace.cmm (JAL/JALR 解析) | `arm_backtrace.py` (BL/BLX 指令解析) |
| 线程分析 | show_thread.cmm | `rtthread_parser.py` (遍历 rt_object_container) |

优点：开源免费、跨平台、可扩展、可集成到 CI/CD 流程中自动分析。

## 6. 实现计划（分阶段执行）

### 6.1 阶段划分与里程碑

| 阶段 | 任务 | 预计工作量 | 里程碑 |
|------|------|-----------|--------|
| **P0: 基础设施** | Kconfig、SConscript、.noinit 段、删除 BSP 空 handler | 0.5 天 | 编译通过，无死循环 handler |
| **P1: IO 与传输** | ramdump_io.c、ramdump_engine.c（XMODEM 发送）、ramdump_config.h | 1 天 | 手动 `ramdump` 命令成功发送 SRAM.bin |
| **P2: 异常对接** | ramdump_exception.c、修改 cpuport.c、ramdump_cli.c | 1 天 | 触发异常后自动进入 CLI |
| **P3: 本地存储** | ramdump_storage.c（SD/Flash 保存） | 0.5 天 | 崩溃后 dump 文件保存到 SD 卡 |
| **P4: PC 工具** | ramdump_analyzer.py（加载镜像、异常解码、调用栈回溯） | 2 天 | PC 端能定位崩溃地址和调用栈 |
| **P5: 线程分析** | rtthread_parser.py（线程列表、栈使用率、IPC 分析） | 1 天 | 全线程状态分析 |
| **P6: 完善测试** | 边界测试、文档、CI 集成 | 1 天 | 完整可用 |

### 6.2 文件变更清单

| 操作 | 文件 | 说明 |
|------|------|------|
| **新增** | `components/ramdump/` (全部文件) | ramdump 组件 |
| **新增** | `tools/ramdump_analyzer/` (全部文件) | PC 端分析工具 |
| **修改** | `libcpu/arm/cortex-m4/cpuport.c` | 在 `rt_hw_hard_fault_exception` 末尾插入 ramdump 入口 |
| **修改** | `bsp/stm32/stm32f407-atk-explorer/board/CubeMX_Config/Src/stm32f4xx_it.c` | 删除空死循环 handler |
| **修改** | `bsp/stm32/stm32f407-atk-explorer/board/board.c` | 使能 MemManage/BusFault/UsageFault |
| **修改** | `bsp/stm32/stm32f407-atk-explorer/board/linker_scripts/link.lds` | 新增 .noinit 段 |
| **修改** | `components/Kconfig` | 新增 `source "components/ramdump/Kconfig"` |
| **修改** | `components/SConscript` | 新增 ramdump 组件的编译 |

### 6.3 不修改的文件

- `components/utilities/ymodem/` — 保持现有 YMODEM 实现不变（ramdump 引擎独立实现 XMODEM 发送，避免修改通用组件）
- `components/finsh/` — 保持现有 MSH 不变（仅通过 MSH_CMD_EXPORT 注册命令）
- `include/rtdef.h` — 不修改内核头文件
- `libcpu/arm/cortex-m4/context_gcc.S` — 不修改汇编入口（异常入口逻辑在 C 层 cpuport.c 中处理）

## 7. 测试验证方案

### 7.1 Phase 1 验证

```
# 在 MSH 中执行
msh /> ramdump

# 预期输出
[ramdump] IO channel ready: uart2 @ 921600 bps
[ramdump] [1/2] Sending SRAM.bin (0x20000000, 131072 bytes)...
OK
[ramdump] [2/2] Sending CCM.bin (0x10000000, 65536 bytes)...
OK
[ramdump] Done.

# PC 端 SecureCRT → Transfer → Receive YMODEM
# 验证: 收到 SRAM.bin (131072 bytes) 和 CCM.bin (65536 bytes)
```

### 7.2 Phase 2 验证

```
# 在 MSH 中执行
msh /> ramdump_test

# 预期: 触发异常后自动进入 ramdump CLI
===== RAMDUMP EXCEPTION RECORD =====
Fault Type : BusFault
Thread     : tshell
Tick       : 12345
CFSR       : 0x00008200
HFSR       : 0x40000000
...
@ramdump> errorlog
@ramdump> ramdump
@ramdump> reboot
```

### 7.3 Phase 3 验证

触发异常后，检查 SD 卡目录：

```
/sd/ramdump_12345/
├── SRAM.bin         (131072 bytes)
├── CCM.bin          (65536 bytes)
└── exception.txt    (异常信息)
```

### 7.4 Phase 4 验证

```
# PC 端
python tools/ramdump_analyzer/ramdump_analyzer.py \
    --sram SRAM.bin \
    --ccm CCM.bin \
    --elf rtthread.elf \
    --output report.html

# 预期: 生成 HTML 报告，包含:
# - 异常类型和故障地址
# - 崩溃时的寄存器值
# - 崩溃线程的调用栈（函数名 + 源文件行号）
# - 所有线程列表和状态
```

## 8. 附录

### 8.1 ARM Cortex-M 异常类型解码表

```c
// CFSR (Configurable Fault Status Register) 位域解码
// 位于 SCB->CFSR，地址 0xE000ED28

// MemManage Fault Status Register (MMFSR) — bits [7:0]
#define CFSR_MMFSR_IACCVIOL    (1 << 0)   // 指令访问违例
#define CFSR_MMFSR_DACCVIOL    (1 << 1)   // 数据访问违例
#define CFSR_MMFSR_MUNSTKERR   (1 << 3)   // 异常返回时出栈错误
#define CFSR_MMFSR_MSTKERR     (1 << 4)   // 异常入栈时压栈错误
#define CFSR_MMFSR_MLSPERR     (1 << 5)   // 浮点惰性状态保存错误
#define CFSR_MMFSR_MMARVALID   (1 << 7)   // MMFAR 有效

// BusFault Status Register (BFSR) — bits [15:8]
#define CFSR_BFSR_IBUSERR      (1 << 8)   // 指令总线错误
#define CFSR_BFSR_PRECISERR    (1 << 9)   // 精确数据总线错误
#define CFSR_BFSR_IMPRECISERR  (1 << 10)  // 不精确数据总线错误
#define CFSR_BFSR_UNSTKERR     (1 << 11)  // 异常返回时出栈总线错误
#define CFSR_BFSR_STKERR       (1 << 12)  // 异常入栈时压栈总线错误
#define CFSR_BFSR_LSPERR       (1 << 13)  // 浮点惰性状态保存总线错误
#define CFSR_BFSR_BFARVALID    (1 << 15)  // BFAR 有效

// UsageFault Status Register (UFSR) — bits [25:16]
#define CFSR_UFSR_UNDEFINSTR   (1 << 16)  // 未定义指令
#define CFSR_UFSR_INVSTATE     (1 << 17)  // 无效状态（ARM/Thumb 切换错误）
#define CFSR_UFSR_INVPC        (1 << 18)  // 无效 PC 加载
#define CFSR_UFSR_NOCP         (1 << 19)  // 无协处理器
#define CFSR_UFSR_UNALIGNED    (1 << 24)  // 未对齐访问
#define CFSR_UFSR_DIVBYZERO    (1 << 25)  // 除零（如果启用）
```

### 8.2 RT-Thread 线程状态枚举

```c
// 来自 rtdef.h — 线程状态位掩码
#define RT_THREAD_INIT        0x00   // 初始状态
#define RT_THREAD_READY       0x01   // 就绪
#define RT_THREAD_SUSPEND     0x02   // 挂起
#define RT_THREAD_RUNNING     0x03   // 运行中
#define RT_THREAD_CLOSE       0x04   // 关闭
#define RT_THREAD_STAT_MASK   0x0F   // 状态掩码

#define RT_THREAD_STAT_SIGNAL         0x10   // 信号等待
#define RT_THREAD_STAT_SIGNAL_READY   (RT_THREAD_STAT_SIGNAL | RT_THREAD_READY)
#define RT_THREAD_STAT_SIGNAL_WAIT    0x20
#define RT_THREAD_STAT_SIGNAL_PENDING 0x40
```

### 8.3 关键寄存器地址速查

| 寄存器 | 地址 | 说明 |
|--------|------|------|
| SCB->CFSR | 0xE000ED28 | 可配置故障状态寄存器 |
| SCB->HFSR | 0xE000ED2C | 硬故障状态寄存器 |
| SCB->MMFAR | 0xE000ED34 | MemManage 故障地址 |
| SCB->BFAR | 0xE000ED38 | BusFault 故障地址 |
| SCB->SHCSR | 0xE000ED24 | 系统处理程序控制和状态寄存器 |
| SCB->AIRCR | 0xE000ED0C | 应用中断和复位控制寄存器 |
| NVIC->ISER | 0xE000E100 | 中断使能设置寄存器 |
| SCB->FPCCR | 0xE000EF34 | 浮点上下文控制寄存器 |