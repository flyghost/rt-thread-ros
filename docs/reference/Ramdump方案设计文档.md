## 1. 概述

Ramdump 是设备崩溃后的内存转储诊断框架。当 CPU 异常或断言失败时，系统进入 ramdump 模式，通过 UART 将内存镜像传输到 PC，供 Trace32 等工具进行离线分析。

### 1.1 核心能力

| 能力    | 说明                              |
| ----- | ------------------------------- |
| 崩溃捕获  | 自动捕获 CPU 异常和断言，保存异常现场           |
| 内存转储  | 支持 YMODEM 批量传输和 DIAG 协议逐块读取     |
| 交互调试  | 崩溃后提供命令行，支持内存读写、寄存器访问           |
| 双核协同  | 异常时停止对端核心，转储双核内存镜像              |
| 多传输通道 | UART（带 HDLC 成帧）、UART、MUX 代理 |

---

## 2. 内存 Dump 原理

### 2.1 直接内存映射方式

不同于传统方案需要先将内存拷贝到缓冲区再发送，本方案利用嵌入式系统的**物理内存直接可寻址**特性：

```c
// YMODEM 模式：直接指向内存基地址，零拷贝传输
testYmodemFiles[0].buf  = (uint8_t *)BASE_SH_RAM0;  // 共享 RAM 基地址
testYmodemFiles[0].size = LEN_SH_RAM;                 // 区域长度

// DIAG 协议模式：通过 osMemcpy 从任意地址读取
osMemcpy((uint8_t *)dumpRsp->data, (uint8_t *)addr, req->len);
```

**核心思想**：嵌入式设备没有 MMU 隔离，所有物理内存（IRAM、PSRAM、ILM、DLM、XIP Flash）都映射到统一的地址空间。直接强制转换地址为指针即可读取。

### 2.2 触发链与数据流

以下完整流程图覆盖从芯片崩溃到 PC 端分析的端到端路径：

```
                      ┌──────────────────────────────────────┐
                      │  CPU 硬件异常 (mcause/mdcause)        │
                      │  或 OS_ASSERT(0) → ecall 指令         │
                      └──────────────┬───────────────────────┘
                                     │
                      ┌──────────────┴──────────────┐
                      │  exc_entry (汇编入口)         │
                      │  · IRQ_SAVE_CONTEXT 保存寄存器│
                      │  · 切换到异常栈               │
                      │  · 调用 core_exception_handler│
                      └──────────────┬──────────────┘
                                     │
                ┌────────────────────┼────────────────────┐
                │                    │                    │
                ▼                    ▼                    ▼
        ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
        │ 保存异常信息   │    │ 发送 ICP 中断  │    │ 格式化错误日志 │
        │ g_osException │    │ 停止对端核     │    │ g_osErrorLog  │
        │ ·core/mcause  │    │ (仅双核场景)   │    │ (含文件名行号) │
        │ ·mepc/mtval   │    └──────────────┘    └──────────────┘
        │ ·sp/ra 等     │
        └──────────────┘
                │
                ▼
        ┌──────────────┐
        │ SLOG_ExpFlush │  刷新残留日志到 UART
        │ Log()         │
        └──────┬───────┘
               │
               ▼
        ┌──────────────┐
        │ DTools_Dump() │  仅 AP 执行；CP 核停在 while(1)
        └──────┬───────┘
               │
    ┌──────────┴──────────┐
    │                     │
    ▼                     ▼
┌──────────┐      ┌──────────────┐
│ 单核平台    │      │ 双核平台      │
└────┬─────┘      └──────┬───────┘
     │                   │
     ▼                   ▼
┌──────────┐      ┌──────────────┐
│uart_init()│      │ 发送 UE Panic │
│          │      │ (3空包+DIAG_  │
│          │      │  PANIC_MSG)   │
└────┬─────┘      └──────┬───────┘
     │                   │
     ▼                   ▼
┌──────────────────────────────────┐
│          DTools_Loop()           │
│          DIAG 协议主循环          │
│                                  │
│  COMM_Header → HDLC_Decode       │
│  → SLOG_Header → SLOG_DiagHeader │
│  → 命令分发:                     │
│    · DIAG_DUMP   → 内存读写      │
│    · DIAG_REG    → 寄存器访问    │
│    · DIAG_VERSION → 版本查询     │
│    · DIAG_REBOOT → 系统复位      │
│    · DIAG_PANIC_MSG → 异常上报   │
│    · DIAG_SET_DUMP_MODE → 切模式 │
│    · DIAG_PARTITION_MSG → 分区   │
└──────┬───────────────┬───────────┘
       │               │
       │  模式切换      │
       │  dtoolsdump   │
       │  命令/DIAG     │
       │               │
┌──────┴──┐     ┌──────┴──────────┐
│DTools_  │     │   ramdump()     │
│Loop()   │     │   Cli_Loop()    │
│(DIAG)   │     │   (CLI 控制台)   │
│         │     │                 │
│PC工具驱动│     │ @ramdump: 提示符 │
│逐块请求  │     │ · md/mw 命令    │
│+CRC校验  │     │ · ramdump 命令  │
│         │     │ · errorlog 命令 │
│         │     │ · reboot 命令   │
└────┬────┘     └──────┬──────────┘
     │                 │
     │ DIAG 响应        │ YMODEM 文件流
     │ (SLOG_DiagDump  │ (SOH/STX + 1KB
     │  Rsp 逐块+CRC)   │  + CRC16)
     │                 │
     │                 │  6 个 .bin 文件:
     │                 │  IRAM/PSRAM/
     │                 │  ap_ilm/ap_dlm/
     │                 │  cp_ilm/cp_dlm
     │                 │
     └────────┬────────┘
              │
              ▼
    ┌─────────────────────────────────┐
    │          PC 端                  │
    │                                 │
    │  ┌───────────────────────────┐  │
    │  │ Trace32 脚本套件 (19.cmm) │  │
    │  │                          │  │
    │  │ LM620_Restore.cmm (GUI)   │  │
    │  │ restore.cmm   加载镜像+ELF│  │
    │  │ errinfo.cmm   异常分析    │  │
    │  │ frame.cmm     寄存器恢复  │  │
    │  │ backtrace.cmm 调用栈回溯  │  │
    │  │ show_all_backtrace.cmm    │  │
    │  │ show_thread.cmm  线程列表 │  │
    │  │ show_mailbox.cmm  IPC分析 │  │
    │  │ print_dlmalloc_heap.cmm   │  │
    │  │ print_smallheap.cmm       │  │
    │  │ ...                       │  │
    │  └───────────────────────────┘  │
    │                                 │
    │  ┌───────────────────────────┐  │
    │  │ DIAG Dump 工具             │  │
    │  │ 主动请求逐块读取内存        │  │
    │  └───────────────────────────┘  │
    └─────────────────────────────────┘
```

#### 2.2.1 软件断言 vs 硬件异常：两条触发路径详解

ramdump 的触发有两种来源：软件断言（`OS_ASSERT`）和硬件异常（CPU 执行非法操作）。两者入口不同，但通过 `ecall` 指令汇合到同一处理链。

**路径 A：软件断言（OS_ASSERT）**

```
OS_ASSERT(EX)                              // os_debug.h:114
  │  if (!(EX))
  └─→ osAssertHandler(__FILE__, __LINE__)  // kservice.c:1822
        │
        ├─ 1. 保存断言信息到 IRAM 共享区:
        │      g_osAssert->core = SELF_CORE_ID    // 1=AP, 2=CP
        │      g_osAssert->file = file             // 触发断言的源文件名
        │      g_osAssert->line = line             // 行号
        │      g_osAssert->pc   = __builtin_return_address(0)
        │         // __builtin_return_address(0) 返回 osAssertHandler 的调用者地址
        │         // 即 OS_ASSERT 宏展开后调用 osAssertHandler 的下一条指令
        │
        └─ 3. __asm__("ecall")           ← 主动触发同步异常
              │
              ▼ 硬件 CSR 自动设置:
              │   mcause = ECALL 异常码
              │   mepc   = ecall 指令地址
              │
              ▼
         exc_entry (汇编) → core_exception_handler (C)
```

**`g_osAssert` 结构体**：

```c
// os_internal.h:84-90，存放于 IRAM 固定地址 (IRAM_BASE_ADDR_ASSERT_SHARE_NC)
typedef struct {
    ubase_t     core;   // 核心 ID: 1=AP, 2=CP
    const char *file;   // 触发文件（如 "cpuport.c"）
    ubase_t     line;   // 行号
    void       *pc;     // 调用者 PC
} osAssert_t;

osAssert_t *g_osAssert = (osAssert_t *)IRAM_BASE_ADDR_ASSERT_SHARE_NC;
```

> `ecall` 的作用：RISC-V 的"环境调用"指令触发同步异常，硬件自动将 mcause 设为 ECALL 码并跳转到 `CSR_MTVEC`→`exc_entry`。断言路径通过此指令"借用"硬件异常的分发机制，此后与硬件异常路径完全合并。

**路径 B：硬件异常**

```
CPU 执行非法操作（空指针访问、非法指令、未对齐访问、总线错误...）
  │
  ├─ 硬件自动设置 CSR:
  │    mcause  = 异常类型码 (0=指令未对齐, 2=非法指令, 5=Load access fault, ...)
  │    mepc    = 故障指令地址
  │    mtval   = 故障附加信息（访问违例的目标地址 / 非法指令的编码）
  │    mdcause = 详细原因 (1=PMP 违规, 2=总线错误, 3=NICE 长指令)
  │
  └─ 硬件自动跳转 CSR_MTVEC → exc_entry
```

**汇合：core_exception_handler 中的判断**

两条路径在 `exc_entry` 汇合后进入 `core_exception_handler`，通过 **`g_osAssert->core` 是否为 0** 区分来源：

```c
// cpuport.c:906-982 (简化)

void core_exception_handler(ubase_t mcause, ubase_t sp,
                             ubase_t mdcause, ubase_t mtval)
{
    // ===== 第1步: 保存异常现场到 g_osException (两条路径共用) =====
    if (g_osException->core == 0) {         // 防重入
        g_osException->core   = SELF_CORE_ID;
        g_osException->trace  = (struct rt_hw_stack_frame *)sp;
        g_osException->mcause = mcause;      // 断言路径: ECALL 码
        g_osException->mdcause = mdcause;    // 断言路径: 0
        g_osException->mepc   = g_osException->trace->epc;
        g_osException->mtval  = mtval;
        // 附加信息: 线程名 + IRQ嵌套深度 → IRAM 共享区
        osSnprintf(IRAM_BASE_ADDR_EXCEPTION_INFO_NC + 4, ...,
                   "T[%s] I[%d] N[%d]", thread_name, irq_no, irq_nest);
    }

    // ===== 第2步: ICP 中断停止对端核心 (共用) =====
    ICP_SendInterrupt(ICP_INT_ID_RAMDUMP);

    // ===== 第3步: 格式化错误日志 — 区分来源 =====
    if (exc_trace == OS_NULL) {             // 首次进入
        exc_trace  = (struct rt_hw_stack_frame *)sp;
        exc_mcause = mcause;

        if (g_osAssert->core == 0) {
            // ← 硬件异常路径: g_osAssert 未被设置
            // 查表解码 mcause(低5位) → "Load access fault"
            // 查表解码 mdcause(低2位) → "Bus"
            osSnprintf(g_osErrorLog, sizeof(g_osErrorLog),
                "\r\n%s Exception: %s(%s). PC: 0x%08x, mtval: 0x%08x\r\n",
                CORE_NAME, mcause_type, mdcause_type, mepc, mtval);
        } else {
            // ← 断言路径: g_osAssert 已被 osAssertHandler 设置
            osSnprintf(g_osErrorLog, sizeof(g_osErrorLog),
                "\r\n%s Assert. File: %s.c, Line: %d, PC: 0x%08x\r\n",
                CORE_NAME, g_osAssert->file, g_osAssert->line, g_osAssert->pc);
        }
    }

    // ===== 第4步: 进入 DTools_Dump (共用) =====
    DTools_Dump();
}
```

**两条路径对比表**：

| | 软件断言 | 硬件异常 |
|---|---|---|
| **触发者** | 代码中 `OS_ASSERT(EX)` 条件为假 | CPU 执行非法操作 |
| **第一现场** | `osAssertHandler()` 先保存 file/line/pc 到 `g_osAssert`，再 `ecall` | 硬件直接跳转 `exc_entry` |
| **mcause 值** | ECALL 异常码 (由硬件设置) | 具体故障码 (2=非法指令, 5=Load fault, 7=Store fault...) |
| **PC 含义** | `g_osAssert->pc` = `__builtin_return_address(0)` (OS_ASSERT 调用位置) | `mepc` = 故障指令地址本身 |
| **区分标志** | `g_osAssert->core != 0` | `g_osAssert->core == 0` |
| **错误日志格式** | `Assert. File: xxx.c, Line: 123, PC: 0x...` | `Exception: Load access fault(Bus). PC: 0x..., mtval: 0x...` |
| **Trace32 显示** | errinfo.cmm 先读 `g_osAssert`，有值则走断言路径 | errinfo.cmm 读 `g_osAssert` 无值，读 `g_osException` 走异常路径 |
| **DTools_Dump** | 进入（与异常路径完全相同） | 进入 |

**完整汇合流程图**：

```
软件断言 (OS_ASSERT)                         硬件异常 (空指针等)
─────────────────────                       ──────────────────

osAssertHandler()                           CPU 硬件
  ├─ g_osAssert->core = 1                    ├─ mcause 自动设置
  ├─ g_osAssert->file = "xxx.c"              ├─ mepc  自动设置
  ├─ g_osAssert->line = 123                  ├─ mtval 自动设置
  ├─ g_osAssert->pc   = 调用者地址           └─ mdcause 自动设置
  └─ ecall ─────────────┐                    ┌─ 自动跳转 ─────┘
                         │                    │
                         └────────┬───────────┘
                                  ▼
                            exc_entry (汇编)
                              ├─ IRQ_SAVE_CONTEXT (32 个寄存器 → 栈帧)
                              ├─ 切换 sp → __excp_stack_end
                              └─ call core_exception_handler(mcause, sp, mdcause, mtval)
                                  │
                                  ├─ 保存 g_osException (mcause/mdcause/mepc/mtval + trace指针)
                                  ├─ ICP_INT_ID_RAMDUMP → 冻结 CP
                                  ├─ 格式化 g_osErrorLog
                                  │    ├─ g_osAssert->core != 0? → "Assert. File: xxx.c, Line: 123"
                                  │    └─ g_osAssert->core == 0? → "Exception: Load access fault(Bus)"
                                  │
                                  └─ DTools_Dump() → ramdump 模式
```

---

## 3. 系统架构

### 3.1 分层架构

```
┌─────────────────────────────────────────────────────────┐
│  Layer 5: PC 端工具                                     │
│  ├─ Trace32 脚本套件 (19 个 .cmm + 2 个 Python 工具)    │
│  ├─ YMODEM 接收器 (SecureCRT, TeraTerm)                 │
│  └─ DIAG Dump 工具 (迭代读取内存)                       │
└─────────────────────────────────────────────────────────┘
                          ▲
          YMODEM / DIAG 协议
                          ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 4: 协议层（平台无关）                             │
│  ├─ ymodem.c: YMODEM 发送/接收，CRC16 校验             │
│  └─ dtools_dump.c: DIAG 协议循环                        │
└─────────────────────────────────────────────────────────┘
                          ▲
          g_Getc / g_Putc / g_PutBytes 函数指针
                          ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 3: IO 抽象层                                     │
│  ├─ console.c: Putc/Puts/Getc/rdPrintf/Console_Init     │
│  └─ 全局函数指针: g_Getc, g_Putc, g_PutBytes           │
└─────────────────────────────────────────────────────────┘
                          ▲
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 2: 传输层（芯片相关）                             │
│  ├─ uart.c: LP-UART 寄存器级驱动                        │
│  └─ mux.c: MUX 代理透传                                 │
└─────────────────────────────────────────────────────────┘
                          ▲
                           │
                          ▼
┌─────────────────────────────────────────────────────────┐
│  Layer 1: 触发层（OS 相关）                              │
│  ├─ cpuport.c: core_exception_handler()                 │
│  ├─ ramdump_notify.c: ramdump() 入口 + shell 命令       │
│  └─ cli.c / command.c: 交互式命令行                     │
└─────────────────────────────────────────────────────────┘
```

### 3.2 目录结构

```

├── CMakeLists.txt                 # 按传输路径选择源文件
├── Kconfig                        # CONFIG_RAMDUMP 开关
│
├── include/
│   ├── cli.h / clitype.h         # CLI 框架声明
│   ├── command.h                  # 命令返回码定义
│   ├── console.h                  # 控制台 IO 抽象 (Putc/Puts/Getc)
│   ├── dtools_dump.h              # DTools_Dump 模式接口
│   ├── mux.h                      # MUX 代理初始化
│   ├── ramdump_notify.h           # ramdump() 弱函数声明
│   ├── uart.h                     # UART 硬件抽象
│   └── ymodem.h                   # YMODEM 协议定义
│
├── console/console.c              # 控制台实现（使用 g_Getc/g_Putc 函数指针）
├── notify/ramdump_notify.c        # ramdump() 入口 + icp_ramdump shell 命令
├── simple_cli/cli.c               # 命令行循环 (Cli_Loop)
├── simple_cli/command.c           # 命令表 (md/mw/reboot/ramdump/baud/errorlog/dtoolsdump)
│
├── ymodem/ymodem.c                # YMODEM 协议（UART 版，使用函数指针）
├── mux/mux.c                      # MUX 透传模式
├── uart/uart.c                    # LP-UART 寄存器驱动
│
├── dtools_dump/
│   ├── dtools_dump.c              # DTools_Dump — UART 路径
│

```

## 4. Dump 代码执行对内存的影响及防护

### 4.1 问题本质

Ramdump 代码本身也是运行在目标设备上的程序，执行期间必然消耗栈空间、使用全局缓冲区。这会导致崩溃时刻的部分内存被覆盖，产生"观察者效应"——测量行为本身改变了被测对象。

### 4.2 会被污染的区域

**栈区域（影响有限）**

`DTools_Dump()` → `Cli_Loop()` → YMODEM/DIAG 的函数调用链会从当前 SP 向下增长，覆盖崩溃时刻调用栈的下半部分：

```
高地址  ┌──────────────────┐
        │  崩溃前调用栈      │  ← 保持原样（已保存到 g_osException）
        ├──────────────────┤
  SP →  │  ramdump 函数栈帧  │  ← 被覆盖
        │  Cli_Loop()       │
        │  DTools_Loop()    │
        │  ...              │
低地址  └──────────────────┘
```

**全局/静态缓冲区（影响可忽略）**

以下静态变量覆盖了其原始内存位置：

| 变量 | 所属文件 | 说明 |
|------|----------|------|
| `data_save[1032]` | ymodem.c send_packet() | YMODEM 发包缓冲 |
| `console_buffer[]` | cli.c | CLI 输入缓冲 |

但这些缓冲区在正常运行时的内容是日志或临时数据，对崩溃分析无意义。

### 4.3 不受影响的区域

| 区域 | 原因 |
|------|------|
| **异常现场（寄存器快照）** | 已提前保存到 `g_osException` 结构体，后续代码无法覆盖 |
| **g_osErrorLog** | 错误日志在调用 DTools_Dump 前已格式化完毕 |
| **堆内存** | ramdump 代码不调用 malloc，不触碰堆 |
| **其他线程栈** | 不切换线程，不影响其他线程空间 |
| **代码段/只读数据段** | 只读，物理上不可写 |
| **CP 核心内存** | CP 已停在 `while(1)`，ramdump 只在 AP 运行 |
| **YMODEM 传输中的源数据** | 只读操作：`osMemcpy(pkt_buf, source_addr, len)` |
| **DIAG 读取的源数据** | 只读操作：`osMemcpy(rsp, addr, len)` |

### 4.4 防护策略

**核心原则：先保存现场，再跑逻辑**

```
core_exception_handler() [cpuport.c]
        │
        ├── 第1步: 保存寄存器快照到 g_osException   ← 崩溃现场凝固
        │          · mepc   (异常 PC)
        │          · mcause (异常原因)
        │          · mtval  (异常附加信息)
        │          · sp + 通用寄存器
        │          · 当前核心 ID
        │
        ├── 第2步: 格式化错误日志到 g_osErrorLog    ← 文本信息凝固
        │
        ├── 第3步: ICP 中断通知对端核心              ← 冻结 CP
        │
        └── 第4步: 调用 DTools_Dump()               ← 此时才开始污染内存
```

**关键设计**：
1. 崩溃的第一现场（寄存器、异常码、当前指令地址）在第一步就存到 `g_osException`，后续代码无论怎么跑都不会丢失
2. Trace32 恢复分析时，通过 `g_osException` 中保存的寄存器快照重建调用栈，不依赖被污染的栈内存
3. `backtrace.cmm` 脚本从保存的 SP 开始向上遍历，只读不写，不受栈污染影响

### 4.5 实际影响评估

| 场景 | 影响程度 | 说明 |
|------|----------|------|
| 查看异常原因（mcause） | 无 | 已保存到 g_osException |
| 查看崩溃时的 PC 指针 | 无 | 已保存到 g_osException |
| 查看当前线程调用栈 | 轻微 | 崩溃点以下的栈帧被覆盖，但 Trace32 从保存的 SP 向上回溯，不影响上层帧 |
| 查看全局变量 | 无 | 代码不写全局变量（除自身静态缓冲外） |
| 查看堆内存 | 无 | 不调用 malloc |
| 查看其他线程 | 无 | 不切换线程 |

**结论**：代价是当前线程栈的下半部分帧和少量静态缓冲区被覆盖，但崩溃分析所需的全部关键信息（寄存器快照、异常码、调用栈上层、堆、其他线程）均完好无损。这是"先凝固现场、再执行逻辑"设计的正确结果。

---

### 4.6 双核处理

#### 4.6.1 整体流程

- **AP 核心**：执行完整的 DTools_Dump() 流程
- **CP 核心**：收到 `ICP_INT_ID_RAMDUMP` 中断后触发 `ecall`，进入 `core_exception_handler()`，停止在 `while(1)` 循环
- **防重入**：通过 `g_osException->core` 字段记录已处理的核心 ID
- **YMODEM 转储**：同时包含 AP 和 CP 的 ILM/DLM 区域
- **Trace32 恢复时**：两个核心的内存镜像分别加载到对应地址，通过 `cpu-ap.elf` 和 `cpu-cp.elf` 分别加载符号表

#### 4.6.2 CP 侧入口路径详解

CP 核的异常入口机制与 AP 核完全相同（都执行自己的 `exc_entry` → `core_exception_handler`），但最终行为由编译时 `#ifdef _CPU_AP` 分支控制。

**CP 的汇编入口**：CP 拥有独立的 `interrupt_gcc.S` 和 `start.S`（位于 ``），两核共用同一套源码，通过 `#ifdef _CPU_AP` / `#else` 分支区分 CSR 基地址：

```asm
; interrupt_gcc.S — AP 和 CP 共用 exc_entry
#ifdef _CPU_AP
    csrr t0, BASE_APCPU_CSR           ; AP: 读 AP 的 trace RAM CSR
#else
    csrr t0, BASE_CPCPU_CSR           ; CP: 读 CP 的 trace RAM CSR
#endif
```

其他汇编逻辑（`IRQ_SAVE_CONTEXT`、切换到 `__excp_stack_end`、传参并调用 `core_exception_handler`）完全相同。

**CP 崩溃为发起方**：当 CP 核先发生异常时：

```
CP 硬件异常
  └─→ CP exc_entry → CP core_exception_handler
        ├─ g_osException->core = CP_CORE_ID (2)    // 标记 CP 先崩溃
        ├─ ICP_SendInterrupt(ICP_INT_ID_RAMDUMP)    // 通知 AP
        ├─ 格式化 g_osErrorLog: "CP Exception: ..."
        │
        ├─ #ifdef _CPU_AP → (不执行，CP 编译中没有此分支)
        ├─ CleanAllDCache()
        └─ #else → while(1)                         // CP 在此永久等待
```

**AP 崩溃为发起方**：当 AP 核先发生异常时：

```
AP 硬件异常
  └─→ AP exc_entry → AP core_exception_handler
        ├─ g_osException->core = AP_CORE_ID (1)    // 标记 AP 先崩溃
        ├─ ICP_SendInterrupt(ICP_INT_ID_RAMDUMP)    // 通知 CP → 见下方
        ├─ 格式化 g_osErrorLog: "AP Exception: ..."
        │
        └─ #ifdef _CPU_AP → DTools_Dump()           // AP 执行 dump
```

**CP 收到 ICP_INT_ID_RAMDUMP 后的路径**（`drv_icp.c`）：

这是 CP 被 AP 通知"对端已崩溃"时的响应路径，也是整个双核协调中最精妙的部分：

```c
case ICP_INT_ID_RAMDUMP:
    // 1. 清除中断状态
    WRITE_U32(g_icpHandle.pIcpRes->regBase + ICP_CLRREG_OFFSET, 0x1 << intBit);

    // 2. 主动触发 ecall → 进入 CP 自己的 exc_entry
    //    利用 RISC-V 的同步异常机制，让 CP "伪造"一次异常
    //    从而进入 core_exception_handler 保存自己的现场
    __asm__ __volatile__("ecall\n" : : :);

    // 3. 如果 ecall 返回（正常不会），死循环兜底
    while(1);
```

此时 CP 重新进入 `core_exception_handler`，mcause = ECALL 异常码。由于 AP 已先设置了 `g_osException->core = AP_CORE_ID(1)`，CP 侧的防重入检查 `g_osException->core != 0` 为真，不会覆盖 AP 保存的异常信息。CP 走完错误日志格式化（以 ECALL 异常类型）后，最终停在 `while(1)`。

#### 4.6.3 双核协调的关键设计

| 设计点 | 实现方式 | 作用 |
|--------|---------|------|
| **发起方识别** | `g_osException->core` 记录先崩溃的核心 ID | errinfo.cmm 依此判断显示 AP 还是 CP 异常 |
| **防重入** | `if (g_osException->core == 0)` 检查 | 确保先崩溃核的现场不被后进入核覆盖 |
| **CP 停转** | `#else → while(1)` 编译时分支 | CP 不执行 dump（无 IO 通道），由 AP 代为转储 |
| **CP 现场捕获** | ICP 中断 → `ecall` → `exc_entry` | 利用 CPU 异常机制自然保存 CP 寄存器现场 |
| **转储 CP 内存** | `do_ramdump()` 中硬编码 `cp_ilm.bin` / `cp_dlm.bin` | AP 通过物理地址直接读取 CP 的 TCM |
| **CP 双重崩溃** | CP 先崩 → 通知 AP 崩 → CP 自身也进入 `core_exception_handler` | 两个 g_osException（AP 版 + CP 版各自在各自 IRAM 中）|

> **关键结论**：CP 的 `ecall` 路径意味着无论哪个核先崩溃，**两个核最终都会进入各自的 `core_exception_handler`**，各自的寄存器现场都被保存到各自的 `g_osException` 中。只是 CP 侧不执行 IO 操作（无 UART），由 AP 统一完成内存转储。

---

## 5. 板侧实现
### 5.1 汇编入口与链接脚本

ramdump 的触发链最底层依赖汇编入口和链接脚本，两者定义了异常如何捕获、现场如何保存、内存区域如何布局。

#### 5.1.1 异常入口（interrupt_gcc.S）

`exc_entry` 是 CPU 异常的**第一着陆点**（汇编级），在 C 代码执行前完成关键工作：

```asm
; interrupt_gcc.S

exc_entry:                          ; CSR_MTVEC 指向此处
    IRQ_SAVE_CONTEXT                ; ① 保存全部 32 个 RISC-V 寄存器到栈帧
    ...
    csrr t0, BASE_APCPU_CSR         ; ② 切换 trace RAM 为可读模式
    ...
    la   sp, __excp_stack_end       ; ③ 切换到专用异常栈
    ...
    mv   a0, mcause                 ; ④ 传参: 异常原因
    mv   a1, sp                     ;       寄存器帧指针（→ g_osException 数据来源）
    mv   a2, mdcause                ;       详细异常原因
    mv   a3, mtval                  ;       异常地址
    call core_exception_handler     ; ⑤ 调用 C 层处理函数
```

**IRQ_SAVE_CONTEXT 宏**保存的寄存器布局即 `struct rt_hw_stack_frame`：

```
栈顶(高地址)
┌──────────┐
│  mstatus  │  ← 机器状态寄存器
│  mepc     │  ← 异常 PC（崩溃指令地址）
│  x1 (ra)  │  ← 返回地址
│  x4 (tp)  │  ← 线程指针
│  x5-x31   │  ← 通用寄存器（t0-t6, a0-a7, s0-s11, gp）
│  ...      │
└──────────┘
栈底(低地址)  ← sp (a1 参数，即 exc_trace 的值)
```

**与 ramdump 的关联**：

| 汇编行为                          | ramdump 依赖                                                     |
| ----------------------------- | -------------------------------------------------------------- |
| `la sp, __excp_stack_end`     | 切换到专用异常栈，保证 `DTools_Dump()` 的调用栈不覆盖崩溃任务栈                       |
| `mv a1, sp`（传入寄存器帧指针）         | 最终存为 `exc_trace` 变量，`restore.cmm` 通过 `Var.Value(exc_trace)` 获取 |
| `IRQ_SAVE_CONTEXT` 的寄存器顺序     | 定义 `struct rt_hw_stack_frame` 字段偏移，`frame.cmm` 据此恢复寄存器         |
| `call core_exception_handler` | C 层入口，保存 `g_osException`，发送 ICP 中断，调用 `DTools_Dump()`          |

#### 5.1.2 向量表初始化（start.S）

`__start` 在系统启动时配置 CSR 寄存器，建立异常/中断的分发路径：

```asm
; start.S

__start:
    ...
    la t0, vector_base
    csrw CSR_MTVT, t0              ; 向量中断表基址
    la t0, irq_entry
    csrw CSR_MTVT2, t0             ; 非向量中断入口
    la t0, exc_entry
    csrw CSR_MTVEC, t0             ; 异常入口 = exc_entry（最关键）
    ...
    la sp, __stack_end             ; 启动栈
    ...
    ; 初始化异常栈（填入哨兵值 0x24242424）
    la t0, __excp_stack_start
    la t1, __excp_stack_end
1:  sw zero, 0(t0)
    addi t0, t0, 4
    bltu t0, t1, 1b
    ...
    call osStartup
```

**关键 CSR 寄存器**：

| CSR         | 设置值           | 作用                         |
| ----------- | ------------- | -------------------------- |
| `CSR_MTVEC` | `exc_entry`   | 异常入口地址（同步异常：指令故障、断点、ECALL） |
| `CSR_MTVT`  | `vector_base` | 向量中断表基址                    |
| `CSR_MTVT2` | `irq_entry`   | 非向量中断统一入口                  |

**异常栈哨兵**：启动时将异常栈全部填入 `0x24242424`，与任务栈使用相同的哨兵值。`show_thread.cmm` 的 `stack_used` 子程序通过扫描非 `0x23` 字节计算栈使用率。

#### 5.1.3 上下文切换（context_gcc.S）

`osContextSwitch` 的保存/恢复格式与 `exc_entry` 的 `IRQ_SAVE_CONTEXT` 完全一致：

```asm
; context_gcc.S

osContextSwitch:
    SAVE_CONTEXT                   ; 保存当前线程全部寄存器
    sw sp, (a0)                    ; 保存 sp 到 old_thread->sp
    lw sp, (a1)                    ; 加载 new_thread->sp
    RESTORE_CONTEXT                ; 恢复目标线程全部寄存器
    mret                           ; 返回目标线程

osContextSwitch_exit:
    RESTORE_CONTEXT
    mret
```

**与 ramdump 的关联**：Trace32 的 `show_thread.cmm` 遍历 `g_osThreadList` 时，通过 `osThread_t->sp` 找到每个非运行态线程的寄存器帧，然后调用 `backtrace.cmm` 回溯其调用栈。sp 指向的帧格式必须与 `SAVE_CONTEXT` 一致才能正确解析。

#### 5.1.4 链接脚本（cpu-ap.lds / cpu-cp.lds）

链接脚本定义了所有内存区域的起始地址和长度，是 ramdump "dump 什么"的权威来源：

```ld
/* cpu-ap.lds */

MEMORY {
    INTENAL_CODE  (wxa!ri) : ORIGIN = 0x00008000, LENGTH = 16K      /* ILM (TCM 指令) */
    INTENAL_DATA  (wxa!ri) : ORIGIN = 0x00010000, LENGTH = 16K      /* DLM (TCM 数据) */
    IRAM0_PSM_RE  (wxa!ri) : ORIGIN = 0xC0200800, LENGTH = 10K      /* PSM 保留区 */
    IRAM2         (wxa!ri) : ORIGIN = 0xC0264800, LENGTH = 78K      /* AP IRAM */
    XIP           (wxa!ri) : ORIGIN = AP_XIP_START, ...             /* XIP Flash */
    DRAM          (wxa!ri) : ORIGIN = 0x800FE800, LENGTH = 3078K    /* PSRAM */
}

SECTIONS {
    ...
    .bss : {
        ...
        __excp_stack_start = .;                     /* 异常栈起始 */
        . = . + __stack_size;
        __excp_stack_end = .;                       /* 异常栈结束 */
    }
}
```

**CP 链接脚本的差异**：

| 区域 | AP | CP |
|------|-----|-----|
| ILM (INTENAL_CODE) | 16K @ 0x00008000 | **32K** @ 0x00008000 |
| DLM (INTENAL_DATA) | 16K @ 0x00010000 | **32K** @ 0x00010000 |
| PSM 保留区 | 10K @ 0xC0200800 | 10K @ 0xC0203800 |
| IRAM | 78K @ 0xC0264800 | **103K+64K** @ 0xC0206400 |
| DRAM | 3078K @ 0x800FE800 | **352K** @ 0x80000000 |
| XIP | AP_XIP_START | CP_XIP_START (300K) |

#### 5.1.5 头文件地址定义

**chip_reg_base.h** — 硬件基地址宏，必须与链接脚本一致：

```c
// chip_reg_base.h
#define BASE_ILM            0x00008000    // = 链接脚本 INTENAL_CODE ORIGIN
#define BASE_DLM            0x00010000    // = 链接脚本 INTENAL_DATA ORIGIN
#define BASE_SH_RAM0        0xC0200000    // = 链接脚本 IRAM 段首地址
#define BASE_PSRAM          0x80000000    // = 链接脚本 DRAM 段首地址（CP 视角）
#define LEN_ILM_AP          (16 * 1024)
#define LEN_ILM_CP          (32 * 1024)
#define LEN_DLM_AP          (16 * 1024)
#define LEN_DLM_CP          (32 * 1024)
#define LEN_SH_RAM          (512 * 1024)
```

**iram_layout.h** — IRAM 内异常共享区的精确布局：

```c
// iram_layout.h
IRAM_BASE_ADDR_EXCEPTION_SHARE_NC    // g_osException 存放地址（双核均可读取）
IRAM_BASE_ADDR_EXCEPTION_INFO_NC     // 异常附加信息（线程名、IRQ 嵌套深度）
IRAM_BASE_ADDR_AP_TRACE_RAM          // AP trace RAM 快照（exc_entry 中拷贝）
IRAM_BASE_ADDR_CP_TRACE_RAM          // CP trace RAM 快照
IRAM_BASE_ADDR_ASSERT_SHARE_NC       // 断言信息共享区
IRAM_BASE_ADDR_WDT_TIMEOUT_FLAG      // 看门狗超时标记
IRAM_BASE_ADDR_EXCEPTION_RESET_FLAG  // 异常复位标记
```

**psram_layout.h** — PSRAM/DRAM 内 AP/CP 分区：

```c
// psram_layout.h
DRAM_BASE_ADDR_CP    0x80000000      // CP DRAM 起始
DRAM_BASE_ADDR_AP    0x800FE800      // AP DRAM 起始（= 链接脚本 DRAM ORIGIN）
```

#### 5.1.6 一致性约束

**ramdump 正确工作的前提是：链接脚本、chip_reg_base.h、command.c 三者地址一致。**

```
链接脚本 MEMORY ORIGIN  ≡  chip_reg_base.h BASE_*  ≡  command.c do_ramdump() 地址
```

如果修改链接脚本中 ILM 的起始地址，必须同步修改：

| 序号 | 需修改的位置 | 内容 |
|------|------------|------|
| 1 | `cpu-ap.lds` / `cpu-cp.lds` | `INTENAL_CODE ORIGIN` |
| 2 | `chip_reg_base.h` | `BASE_ILM` 宏 |
| 3 | `command.c` | `do_ramdump()` 中 `ap_ilm.bin` 的 `buf` 地址 |
| 4 | `restore.cmm` | `Data.LOAD.Binary <ilm> 0x...` 加载地址 |
| 5 | `chip_reg_base.h` | `LEN_ILM_AP` 宏（如果大小也变了） |

任何一处不一致都会导致：dump 出错误的内存区域 → Trace32 加载到错误地址 → 符号解析全部失效。

#### 5.1.7 完整触发链（从汇编到 Trace32）

```
CPU 硬件异常
  │
  ▼
CSR_MTVEC → exc_entry (interrupt_gcc.S)
  │         ├─ IRQ_SAVE_CONTEXT (保存 32 个寄存器)
  │         ├─ 切换 sp → __excp_stack_end (专用异常栈)
  │         └─ call core_exception_handler (cpuport.c)
  │
  ▼
core_exception_handler (cpuport.c)
  │         ├─ 保存 g_osException (→ IRAM 共享区)
  │         ├─ 发送 ICP_INT_ID_RAMDUMP → 冻结 CP
  │         ├─ 格式化 g_osErrorLog
  │         └─ 调用 DTools_Dump()
  │
  ▼
DTools_Dump() → DTools_Loop() → DIAG / ramdump CLI
  │
  ▼
PC 端: 接收内存镜像 (.bin)
  │
  ▼
restore.cmm: Var.Value(exc_trace) → 获取异常帧地址
frame.cmm: 从栈帧恢复 32 个寄存器到 Trace32
errinfo.cmm: 解码 mcause/mdcause
backtrace.cmm: 从 sp 向上回溯调用栈
```

### 5.2 寄存器保存与 Trace32 恢复详解

本节详细说明两类寄存器（通用寄存器 + CSR 寄存器）从硬件异常到 Trace32 显示的完整路径，以及非崩溃线程栈的保存和恢复机制。

#### 5.2.1 寄存器分类与各自的保存路径

| 寄存器类别     | 包含      | 保存位置                     | 保存者                   | dump 所在文件 |
| --------- | ------- | ------------------------ | --------------------- | --------- |
| **通用寄存器** | x1-x31  | 栈帧 (`rt_hw_stack_frame`) | 汇编 `IRQ_SAVE_CONTEXT` | PSRAM.bin |
| **PC**    | mepc    | 栈帧 `[+0x00]`             | 汇编 `csrr mepc`        | PSRAM.bin |
| **机器状态**  | mstatus | 栈帧 `[+0x08]`             | 汇编 `csrr mstatus`     | PSRAM.bin |
| **异常原因**  | mcause  | `g_osException->mcause`  | C 层 a0 参数写入           | IRAM.bin  |
| **详细原因**  | mdcause | `g_osException->mdcause` | C 层 a2 参数写入           | IRAM.bin  |
| **故障地址**  | mtval   | `g_osException->mtval`   | C 层 a3 参数写入           | IRAM.bin  |
| **核心 ID** | core    | `g_osException->core`    | C 层 `SELF_CORE_ID` 写入 | IRAM.bin  |
| **帧指针**   | trace   | `g_osException->trace`   | C 层 sp 参数写入           | IRAM.bin  |

#### 5.2.2 通用寄存器：栈帧格式

**异常帧**（`IRQ_SAVE_CONTEXT` 保存，在 `interrupt_gcc.S`）：

```asm
; 32 个 slot，每 slot 4 字节，共 128 字节
addi sp, sp, -32 * REGBYTES

csrr  x1, mstatus              ; 读 mstatus 完整值
STORE x1,  2*4(sp)             ; [+0x08]

csrr  x1, mepc                 ; 读 mepc（崩溃指令地址）
STORE x1,  0*4(sp)             ; [+0x00]

STORE x1,  1*4(sp)             ; [+0x04] ra (x1 原值)
STORE x3,  3*4(sp)             ; [+0x0C] gp
STORE x4,  4*4(sp)             ; [+0x10] tp
STORE x5,  5*4(sp)             ; [+0x14] t0
... (x5-x31 依次)
STORE x31, 31*4(sp)            ; [+0x7C] t6
```

**上下文切换帧**（`osContextSwitch` 保存，在 `context_gcc.S`）：

```asm
; 同样的 32 个 slot 布局，但内容有差异
addi  sp, sp, -32 * REGBYTES
STORE sp,  (a0)                ; 保存 sp 到 old_thread->sp

STORE x1,  0*4(sp)             ; [+0x00] 保存 ra 到 epc 槽位（作为返回地址）
STORE x1,  1*4(sp)             ; [+0x04] ra

; 只保存 MIE 位，非完整 mstatus
csrr a0, mstatus
andi a0, a0, 8                 ; 仅取 MIE 位
beqz a0, save_mpie
li   a0, 0x80
STORE a0,  2*4(sp)             ; [+0x08] mstatus.MIE

STORE x4,  4*4(sp)             ; [+0x10] tp
; x5-x31 与异常帧相同
; 注意：不保存 gp (x3) —— 全局指针在线程间不变
```

**两帧的关键差异**：

| 字段 | 异常帧 (IRQ_SAVE_CONTEXT) | 上下文切换帧 (osContextSwitch) |
|------|--------------------------|-------------------------------|
| `[+0x00]` epc | `mepc`(CSR 读) | `ra`（调用 `osContextSwitch` 时的返回地址） |
| `[+0x04]` ra | x1 原值 | x1 原值（与 epc 槽位相同） |
| `[+0x08]` mstatus | 完整的 `mstatus` 值 | 仅 MIE 位（bit 3） |
| `[+0x0C]` gp | x3 (gp) | **未保存**（跳过此槽位） |
| `[+0x10]` tp | x4 (tp) | x4 (tp) |

> 尽管内容有差异，但帧格式是兼容的——总大小 128 字节，同一槽位的语义一致。因此 `frame.cmm` 可以用同一套偏移量解析异常帧和上下文切换帧。

#### 5.2.3 CSR 寄存器：g_osException 结构体

```c
// cpuport.c
typedef struct {
    ubase_t core;                        // 1=AP, 2=CP
    struct rt_hw_stack_frame *trace;     // 指向栈帧
    ubase_t mcause;                      // 异常原因码
    ubase_t mdcause;                     // 详细原因码
    ubase_t mepc;                        // 异常指令地址
    ubase_t mtval;                       // 故障地址
} osException_t;

// 存放在 IRAM 固定地址（双核共享）
osException_t *g_osException = (osException_t *)IRAM_BASE_ADDR_EXCEPTION_SHARE_NC;
```

**保存时机**（在 `core_exception_handler` 中，早于 `DTools_Dump()`）：

```c
if (g_osException->core == 0) {         // 防止重入
    g_osException->core   = SELF_CORE_ID;
    g_osException->trace  = (struct rt_hw_stack_frame *)sp;  // a1
    g_osException->mcause = mcause;                           // a0
    g_osException->mdcause = mdcause;                         // a2
    g_osException->mepc   = g_osException->trace->epc;        // 从栈帧取
    g_osException->mtval  = mtval;                            // a3
}
```

#### 5.2.4 崩溃线程在 Trace32 上的恢复

**Step 1: restore.cmm 获取帧指针**

```cmm
; 加载镜像
Data.LOAD.Binary IRAM.bin   0xC0200000    ; g_osException 在此
Data.LOAD.Binary PSRAM.bin  0x80000000    ; 栈帧在此
Data.LOAD.Elf    cpu-ap.elf  /NoCODE

; 获取异常帧地址 (exc_trace 是 C 层的全局变量)
&frame = Var.Value(exc_trace)
do frame.cmm &frame
```

**Step 2: frame.cmm 恢复全部通用寄存器**

```cmm
ENTRY &cpu_frame

; SP 需要计算：帧底 + 帧大小
&sp = &cpu_frame + 0x80            ; sizeof(rt_hw_stack_frame) = 128

; 从帧中逐字段恢复到 Trace32 模拟 CPU
Register.Set PC  Var.Value(((struct rt_hw_stack_frame*)&cpu_frame)->epc)
Register.Set X1  Var.Value(ra)       ; 返回地址
Register.Set X2  &sp                 ; SP = 计算的栈顶
Register.Set X3  Var.Value(gp)       ; 全局指针
Register.Set X4  Var.Value(tp)       ; 线程指针
Register.Set X5  Var.Value(t0)
... (x5-x31 全部恢复)
Register.Set X31 Var.Value(t6)
```

恢复后，Trace32 的 `Register.view` 窗口显示崩溃瞬间全部 32 个寄存器值。

**Step 3: errinfo.cmm 解码并显示异常原因**

```cmm
; 读 g_osException 结构体
&mcause  = Var.Value(g_osException->mcause) & 0x1f
&mdcause = Var.Value(g_osException->mdcause) & 0x3
&pc      = Var.Value(g_osException->mepc)
&mtval   = Var.Value(g_osException->mtval)

; mcause 解码表 (低 5 位)
0 → "Instruction address misaligned"
1 → "Instruction access fault"
2 → "Illegal instruction"
3 → "Breakpoint"
4 → "Load address misaligned"
5 → "Load access fault"
6 → "Store/AMO address misaligned"
7 → "Store/AMO access fault"

; mdcause 解码表 (低 2 位)
1 → "PMP"        ; 物理内存保护违规
2 → "Bus"        ; 总线错误
3 → "NICE"       ; 长指令异常

; 最终输出到 GUI 界面 ERRINFO 行
"AP Exception: Load access fault(Bus). PC: 0x8020AB12, Access Addr: 0x00000000"
```

**Step 4: backtrace.cmm 回溯调用栈**

从帧的 SP 向上（高地址方向）扫描栈内存，通过 RISC-V 指令编码识别返回地址，逐帧还原调用链。详见 [7.4 调用栈回溯](#74-调用栈回溯)。

#### 5.2.5 非崩溃线程在 Trace32 上的恢复

当 CPU 异常发生时，**只有崩溃线程**的寄存器被 `exc_entry` 保存。其他线程的寄存器现场是**之前被调度器切换出去时**保存在各自栈上的。

**设备端：调度器保存（osContextSwitch）**

```asm
; context_gcc.S — 线程切换时保存当前线程现场
osContextSwitch:
    addi  sp, sp, -32 * REGBYTES    ; 栈上开 128 字节帧
    STORE sp,  (a0)                  ; 保存 sp 到 old_thread->sp ← 关键
    ; ... 保存 x1,x4-x31, mstatus.MIE ...
    LOAD  sp,  (a1)                  ; 加载 new_thread->sp
    j osContextSwitch_exit           ; 恢复目标线程现场
```

每个线程的 `osThread_t->sp` 指向其栈上保存的寄存器帧。线程被切出时 SP 已经指向帧底，切回时从 `osThread_t->sp` 加载 SP 再逐寄存器恢复。

**Trace32 端：遍历线程恢复**

```
LM620_Restore.cmm 中的线程恢复按钮:

┌─ BackTrace 按钮（崩溃线程）
│   └─ do backtrace.cmm <exc_trace> <exc_trace+0x1000>
│   └─ do frame.cmm <exc_trace>
│
├─ ThreadBT 按钮（用户选择线程）
│   ├─ do select_thread.cmm
│   │   └─ 遍历 g_osThreadList → 下拉框选线程 → 返回 &thread_struct
│   └─ do backtrace.cmm <sp> <stackAddr+stackSize>
│   └─ do frame.cmm <sp>
│
├─ AllThreadBT 按钮（全部线程）
│   └─ do show_all_backtrace.cmm
│       └─ 遍历 g_osThreadList，每个线程:
│           sp    = ((osThread_t*)&thread_struct)->sp        ← 调度器保存的
│           start = ((osThread_t*)&thread_struct)->stackAddr
│           size  = ((osThread_t*)&thread_struct)->stackSize
│           do backtrace.cmm <sp> <start+size>
│
└─ ShowThread 按钮（线程概览）
    └─ do show_thread.cmm
        └─ 遍历 g_osThreadList，打印:
            · sp 值 (osThread_t->sp)
            · 栈使用率 (扫描 0x23 哨兵)
            · 状态/优先级/剩余 tick
```

**关键数据结构**：

```
g_osThreadList (双向链表头)
    │
    ├─ osThread_t [idle]
    │   ├─ sp        → 0x8010F600  (切出时的寄存器帧地址)
    │   ├─ stackAddr → 0x8010E000  (栈底)
    │   └─ stackSize → 8192
    │
    ├─ osThread_t [ymodem_test]
    │   ├─ sp        → 0x80112000
    │   ├─ stackAddr → 0x80110000
    │   └─ stackSize → 4096
    │
    └─ osThread_t [...]
```

**frame.cmm 用于非崩溃线程时的行为**：

- 传入的 `&cpu_frame` 是 `osThread_t->sp`（而非 `exc_trace`）
- 恢复的 PC 是 `ra`（上次函数调用返回地址），而非 `mepc`
- 恢复的寄存器反映了该线程被切出瞬间的状态
- 恢复后可以独立查看该线程当时的局部变量和调用栈

#### 5.2.6 在 LM620_Restore.cmm GUI 中的呈现

```
┌──────────────────────────────────────────────────────────────┐
│  LM620 Ramdump Tool                                          │
├──────────────────────────────────────────────────────────────┤
│  Ramdump : [C:\ramdump\]  [...]   Elf File: [cpu-ap.elf] [.]│
│  SYSINFO: THREAD[idle]  IRQNEST[0]                           │
│  ERRINFO: AP Exception: Load access fault(Bus).              │
│           PC: 0x8020AB12, Access Addr: 0x00000000            │
├──────────────────────────────────────────────────────────────┤
│  [ShowThread] [BackTrace] [ThreadBT] [AllThreadBT] [MSG Box]│
│  [MemTrace] [MemSummary] [ThreadSwap]                        │
└──────────────────────────────────────────────────────────────┘

点 BackTrace → Frame.view 显示崩溃线程的全部寄存器:
  PC  = 0x8020AB12    ← 从栈帧 epc 字段 (csrr mepc)
  X1  = 0x80123456    ← 从栈帧 ra 字段
  X2  = 0x8010F800    ← 计算: &frame + 0x80
  ... (31 个通用寄存器全部恢复)

点 ThreadBT → 选 "ymodem_test" 线程:
  PC  = 0x80102000    ← 从栈帧 epc 字段 (保存的 ra)
  X2  = 0x80111FFC    ← 计算: thread->sp + 0x80

ERRINFO 行: errinfo.cmm 解码结果显示崩溃直接原因
SYSINFO 行: show_sysinfo.cmm 显示崩溃时的线程名和中断嵌套深度
```

#### 5.2.7 总结：寄存器从芯片到 Trace32 的完整路径

```
设备端 ──────────────────────────────────────────── PC 端 Trace32

┌─ 通用寄存器组 ───────────────────────────────────────────────┐
│                                                               │
│  exc_entry                   内存 dump          restore.cmm  │
│  IRQ_SAVE_CONTEXT ──────→ PSRAM.bin ──────→ Data.LOAD.Binary│
│  (保存到栈帧)                   │                +            │
│                              IRAM.bin       frame.cmm        │
│  core_exception_handler ──→ (g_osException  Register.Set Xn  │
│  (trace 指针)                在 IRAM 中)     → Register.view │
│                                                               │
│  osContextSwitch ──────→ PSRAM.bin ──────→ backtrace.cmm     │
│  (其他线程栈帧)                   │         + frame.cmm       │
│                              thread->sp    → 每个线程的       │
│                                              独立寄存器视图   │
└──────────────────────────────────────────────────────────────┘

┌─ CSR 寄存器组 ───────────────────────────────────────────────┐
│                                                               │
│  core_exception_handler     内存 dump          errinfo.cmm    │
│  a0=mcause, a2=mdcause ──→ IRAM.bin ──────→ Var.Value(      │
│  a3=mtval               g_osException 在      g_osException  │
│  存到 g_osException      IRAM 固定地址        ->mcause)       │
│                                              → 解码显示      │
│                                              → ERRINFO 行    │
└──────────────────────────────────────────────────────────────┘
```

---

## 6. 传输与协议

本章描述 dump 数据的**传输通道和通信协议**。这些协议与 dump 的核心逻辑（异常捕获、现场保存、内存读取）相互独立——它们是连接板卡和 PC 工具的"管道"，任何传输方式只要实现了对应的 IO 接口即可接入。

---

### 6.1 IO 函数指针接口（传输抽象层）

整个 ramdump 子系统使用三个全局函数指针实现可重定向 IO：

```c
typedef int32_t (*F_ConGetc)(uint32_t timeout);        // 接收一个字节
typedef void    (*F_ConPutc)(uint8_t ch);              // 发送一个字节
typedef void    (*F_ConPutBytes)(uint8_t *bytes,       // 批量发送
                                  uint32_t bytesLen,
                                  uint32_t timeout);
```

不同模式下指向不同实现：

| 模式                | g_Getc    | g_Putc    | g_PutBytes   |
| ----------------- | --------- | --------- | ------------ |
| Ramdump CLI（UART） | Uart_Getc | Uart_Putc | NULL         |
| Ramdump CLI（MUX）  | Mux_Getc  | Mux_Putc  | Mux_PutBytes |
| DTools_Dump（UART） | Uart_Getc | Uart_Putc | HDLC 发送      |


---

### 6.2 YMODEM 协议（批量文件传输）

```
PC 端 (SecureCRT/TeraTerm)              设备端 (ramdump CLI)
       |                                       |
       |  <──── CRC ('C') ──────────────────   |  握手请求
       |  ───── CRC ('C') ────────────────>    |  握手响应
       |                                       |
       |  <──── SOH 00 FF [文件名+大小...] ──   |  Block0（文件信息包）
       |  ───── ACK ──────────────────────>    |
       |  ───── CRC ──────────────────────>    |  请求数据
       |                                       |
       |  <──── STX 01 FE [1KB 数据 + CRC] ──   |  Block1（数据包）
       |  ───── ACK ──────────────────────>    |
       |                                       |
       |  ...（重复直到数据发送完毕）...        |
       |                                       |
       |  <──── EOT ────────────────────────   |  文件传输结束
       |  ───── ACK ──────────────────────>    |
       |  ───── CRC ──────────────────────>    |  请求下一个文件
       |                                       |
       |  ...（下一个文件）...                  |
       |                                       |
       |  <──── SOH 00 FF [全零...] ────────   |  空文件名包（批次结束）
       |  ───── ACK ──────────────────────>    |
```

**6 个默认转储区域**（在 `command.c` 的 `do_ramdump` 中定义）：

| 序号  | 文件名        | 内存区域         | 典型地址                    |
| --- | ---------- | ------------ | ----------------------- |
| 0   | IRAM.bin   | 共享 RAM（双核可见） | 0x10200000 / 0xC0200000 |
| 1   | PSRAM.bin  | 伪静态 RAM      | 0x40000000 / 0x80000000 |
| 2   | ap_ilm.bin | AP 指令本地内存    | 0x00008000              |
| 3   | ap_dlm.bin | AP 数据本地内存    | 0x00010000              |
| 4   | cp_ilm.bin | CP 指令本地内存    | 芯片相关                    |
| 5   | cp_dlm.bin | CP 数据本地内存    | 芯片相关                    |
| 6   | <addr>.xip | XIP 闪存分区（可选） | 动态                      |

> **注意**：IRAM 和 PSRAM 在地址空间中存在两个别名映射（如 IRAM 同时出现在 0x10200000 和 0xC0200000），两个地址都会 dump。Trace32 恢复时也会加载到两个地址，确保无论代码通过哪个别名访问内存都能正确解析。


---

### 6.3 DIAG 协议（命令-响应逐块传输）

```
PC 工具                                    设备 (DTools_Loop)
       |                                       |
       |  ───── [COMM|SLOG|DIAG_DUMP_REQ] ──>  |  读取请求（地址+长度）
       |                                       |  ├─ osMemcpy(buf, addr, len)
       |                                       |  ├─ CRC16 校验
       |  <──── [COMM|SLOG|DIAG_DUMP_RSP] ────  |  响应（数据+CRC）
       |
       |  （PC 工具迭代读取所有区域，重建镜像）
```

协议栈结构：
```
┌──────────────────────┐
│    COMM_Header        │  4 字节: msgType, pad, reserved, srcMdlNo, ...
├──────────────────────┤
│    SLOG_Header        │  版本号, msgType=SLOG_DIAG_MSG, 长度
├──────────────────────┤
│    SLOG_DiagHeader    │  diagId, len
├──────────────────────┤
│    载荷（Payload）    │  DIAG_DUMP_Req / DIAG_DUMP_Rsp / ...
└──────────────────────┘
```

DIAG 支持的命令：

| 命令 ID | 功能 |
|---------|------|
| DIAG_DUMP | 内存读写（最大 512 字节/次） |
| DIAG_REG | 寄存器读写（32 位） |
| DIAG_VERSION | 获取 SDK 版本 |
| DIAG_PARTITION_MSG | 获取 Flash 分区表 |
| DIAG_PANIC_MSG | 获取 Panic 通知（含异常日志） |
| DIAG_LOG_MSG | 获取残留日志 |
| DIAG_REBOOT | 正常重启 |
| DIAG_REBOOT_TO_DOWNLOAD | 重启到下载模式 |
| DIAG_SET_DUMP_MODE | 切换 DTools_Dump ↔ RAMDUMP CLI 模式 |

---


---

### 6.4 协议交互详解

#### 6.4.1 两种协议栈对比

设备端支持两种独立的协议栈完成内存转储，它们物理上共用 UART VCOM 通道，但协议层次完全不同：

```
DIAG 协议栈（逐块读取）                YMODEM 协议栈（批量传输）
==============================      ==============================
SLOG_DiagDumpReq / SLOG_DiagDumpRsp  YMODEM (SOH/STX + 1KB data + CRC16)
        ▲                                      ▲
SLOG_DiagHeader (diagId + len)              （无中间层）
        ▲
SLOG_Header (version + msgType + length)
        ▲
COMM_Header (12字节, 含模块路由)
        ▲
HDLC 成帧 (0x7E, 仅 UART 路径)            （无成帧，裸字节流）
```

| 维度 | DIAG 协议 | YMODEM 协议 |
|------|----------|-------------|
| 用途 | PC 工具逐块读取内存 | 批量传输完整镜像文件 |
| 成帧 | UART: HDLC 0x7E | 无（依赖 SOH/STX/EOT 控制字符） |
| 路由 | COMM_Header 模块号路由 (MDL_SLOG) | 无路由（点对点） |
| 粒度 | 最大 512 字节/次 (`SLOG_DIAG_DUMP_MAX_LEN`) | 128 或 1024 字节/包 |
| 校验 | CRC16 per chunk | CRC16 per packet |
| 双向 | 请求-响应模式（支持内存写入） | 单向推送（仅发送） |
| 错误恢复 | 请求重试 | NAK 重传当前包 |

> **关键设计点**：DIAG 协议在 UART 路径上使用 HDLC 成帧以在字节流中界定消息边界。YMODEM 协议则通过控制字符（SOH/STX/EOT）自身实现帧同步，无需额外的成帧层。

#### 6.4.2 DIAG 消息格式详解

以 PC 工具请求读取内存地址 `0xC0200000` 处 256 字节为例，完整的请求消息：

```
字节偏移  字段              示例值          说明
─────────────────────────────────────────────────────────────
[0]     msgType            0x01           COMM_MSG_TYPE（普通消息）
[1]     pad                0xAA           固定填充值
[2-3]   reserved           0xAAAA         固定魔数
[4]     tgtMdlNo           0x01           MDL_PHONE（目标：手机模块）
[5]     tgtSubMdlNo        0x55           SUBMDL_SLOG_AGENT（目标：SLOG 子模块）
[6]     srcMdlNo            0x73          MDL_SLOG（源：SLOG 模块，PC 工具模拟）
[7]     srcSubMdlNo         0x55          SUBMDL_SLOG_AGENT
[8-11]  bufLen              0x00000014    载荷长度 = 20 字节
─────── COMM_Header 结束（12 字节）──────────────────────────
[12]    version             0x01          SLOG 协议版本
[13]    msgType             0x08          SLOG_DIAG_MSG（诊断消息）
[14-15] length              0x0010        内层载荷长度 = 16 字节
─────── SLOG_Header 结束（4 字节）───────────────────────────
[16-17] diagId              0x0008        DIAG_DUMP
[18-19] len                 0x000C        data[] 长度 = 12 字节
─────── SLOG_DiagHeader 结束（4 字节）───────────────────────
[20-23] sequence            0x00000001    请求序列号
[24]    target              0x00          DIAG_TARGET_TYPE_AP
[25]    operation            0x00          DIAG_DUMP_OP_TYPE_READ
[26-27] crc                  0x0000       请求中 CRC 为 0
[28-31] address             0xC0200000    读取起始地址
[32-35] len                  0x00000100    读取长度 = 256 字节
─────── SLOG_DiagDumpReq 结束（16 字节）─────────────────────
```

设备端响应（`data[]` 中包含实际的 256 字节内存内容）：

```
[20-23] sequence            0x00000001    原样返回
[24]    target              0x00
[25]    operation            0x00
[26]    result               0x00          0 = 成功
[27]    reserved1            0x00
[28-29] crc                  0xXXXX        data[] 的 CRC16
[30-31] reserved2            0x0000
[32-35] address             0xC0200000
[36-39] len                  0x00000100
[40+]   data[]               <256 bytes>  实际内存数据
```

**校验流程**：
- 请求端：PC 工具逐次请求 512 字节块，设备侧 `osMemcpy(buf, addr, len)` 读取内存，计算 CRC16 填入 `SLOG_DiagDumpRsp.crc`
- 校验端：PC 工具收到后重新计算 data[] 的 CRC16，与 `crc` 字段比对。不匹配时重发请求
- 单次失败重试上限由 PC 工具控制，超过上限中止本次 dump 会话

#### 6.4.3 DTools_Loop 主循环与命令分发

`DTools_Loop()` 是设备端 DIAG 协议的处理主循环（位于 `dtools_dump.c`），其命令分发树如下：

```
DTools_Loop()
  │
  ├─ DTools_DumpRead()          // 从通道读取数据
  ├─ HDLC_Decode()              // HDLC解码
  ├─ 校验 COMM_Header:
  │    pad == 0xAA && reserved == 0xAAAA
  │
  ├─ msgType == COMM_MSG_TYPE (1):
  │    └─ SLOG_Header.msgType == SLOG_DIAG_MSG (8):
  │         ├─ DIAG_PANIC_MSG        → DTools_SendUePanicMsg()
  │         ├─ DIAG_DUMP             → DTools_DumpProcessMsg()    // 内存读写
  │         ├─ DIAG_RAMDUMP_MSG      → (预留，当前为空)
  │         ├─ DIAG_REG              → DTools_RegProcessMsg()     // 寄存器读写
  │         ├─ DIAG_REBOOT           → DRV_Reboot(RESET_TO_NORMAL)
  │         ├─ DIAG_REBOOT_TO_DOWNLOAD → DRV_Reboot(RESET_TO_DOWNLOAD)
  │         ├─ DIAG_VERSION          → DTools_VersionProcessMsg()
  │         ├─ DIAG_DBG_MSG          → DTools_DbgProcessMsg()
  │         ├─ DIAG_PARTITION_MSG    → DTools_PartitionProcessMsg()
  │
  └─ msgType == COMM_MSG_UE_QUERY (6):
       └─ DTools_QueryProcessMsg()  // 查询芯片类型/HDLC标志等
```

#### 6.4.4 模式切换

设备有两种运行模式，通过 `g_dtoolsDumpMode` 全局变量控制：

| 模式 | `g_dtoolsDumpMode` | 行为 |
|------|-------------------|------|
| DTools_Dump 模式 | `true` | DTools_Loop() 处理 DIAG 命令 |
| RAMDUMP CLI 模式 | `false` | 进入 ramdump 命令行，支持 YMODEM 发送 |

主循环 `DTools_Dump()` 根据模式决定走哪条路径：

```c
while (1) {
    if (IsDtoolsDumpMode()) {
        DTools_Loop();    // DIAG 协议模式
    } else {
        ramdump();        // YMODEM CLI 模式
    }
}
```

模式切换通过 DIAG 命令 `DIAG_SET_DUMP_MODE`（diagId=0x10）触发，PC 工具发送 `SLOG_DiagSetDumpModeRequest.dumpMode` 指定目标模式：

- `DIAG_DTOOLS_DUMP_MODE` (1) → 切换到 DIAG 逐块读取模式
- `DIAG_RAMDUMP_MODE` (0) → 切换到 YMODEM 批量传输模式

**典型交互场景**：
1. 设备崩溃后，默认进入 DTools_Dump 模式，PC 工具通过 DIAG 协议获取异常信息（`DIAG_PANIC_MSG`）
2. PC 工具判断需要完整镜像，发送 `DIAG_SET_DUMP_MODE(DIAG_RAMDUMP_MODE)`
3. `DTools_Loop()` 返回，`IsDtoolsDumpMode()` 变为 false，下次循环进入 `ramdump()` 
4. 用户在 PC 端启动 YMODEM 接收（SecureCRT → Transfer → Receive YMODEM），设备发送完整内存镜像
5. 传输完成后，设备可再次切回 DIAG 模式继续交互

#### 6.4.5 转储地址由谁指定

**YMODEM 模式**：地址完全由**设备端**在 `do_ramdump()` 中硬编码决定，PC 端只是被动接收。6 个固定区域（IRAM/PSRAM/ap_ilm/ap_dlm/cp_ilm/cp_dlm）的基地址和长度定义在 `ramdump_config.h` 中，与链接脚本的 ORIGIN 保持一致。PC 端的 Trace32 脚本 (`restore.cmm`) 必须使用完全相同的地址加载镜像。

**DIAG 模式**：地址由 **PC 工具侧**指定。PC 工具发送 `SLOG_DiagDumpReq` 时填入 `address` 和 `len` 字段，设备侧以 `osMemcpy()` 从指定地址读取。PC 工具负责维护完整的地址映射表，逐块请求所有需要转储的区域。

| 维度 | YMODEM 模式 | DIAG 模式 |
|------|------------|----------|
| 地址决定方 | 设备端（硬编码） | PC 工具端（动态请求） |
| 灵活性 | 低（固定区域） | 高（可按任意粒度读取） |
| 适用场景 | 首次崩溃，无 PC 工具交互 | PC 工具主动诊断，按需探查 |
| 一致性保证 | 设备端编译时校验（链接脚本 + NMI 回调） | PC 工具维护地址映射表 |


---

### 6.5 命令行接口（@ramdump: CLI）

崩溃后通过 UART VCOM 进入 CLI，提示符为 `@ramdump:`。

| 命令                     | 用法                           | 功能                      |
| ---------------------- | ---------------------------- | ----------------------- |
| `md <addr> [len]`      | `md 0x10200000 10`           | 十六进制显示内存（32 位字）         |
| `mw <addr> <val>`      | `mw 0x40000000 0xDEAD`       | 写入内存（32 位字）             |
| `ramdump`              | `ramdump`                    | YMODEM 批量转储全部 6~7 个内存区域 |
| `ramdump <addr> <len>` | `ramdump 0x80000000 0x10000` | YMODEM 转储指定地址+长度的单个区域   |
| `baud <rate>`          | `baud 921600`                | 切换控制台波特率                |
| `errorlog`             | `errorlog`                   | 显示异常错误信息和调用栈            |
| `dtoolsdump`           | `dtoolsdump`                 | 切回 DIAG 协议模式            |
| `reboot`               | `reboot`                     | 复位系统                    |


---


## 7. PC 侧分析（Trace32 集成）

PC 端收到内存镜像后，通过 Trace32 脚本套件进行离线分析。本章基于 `~/claude/tools/trace32/` 目录下的实际脚本（共 19 个 `.cmm` 文件 + 2 个 Python 辅助工具）进行详细分析。

### 7.1 脚本文件总览

#### 7.1.1 完整清单

```
~/claude/tools/trace32/
├── LM620_Restore.cmm              # GUI 主界面（11 个分析按钮）
├── restore.cmm                    # 镜像加载 + ELF 符号恢复 + 寄存器重建
├── frame.cmm                      # 从栈帧恢复 RISC-V 全部 31 个通用寄存器
├── errinfo.cmm                    # 异常原因解码（断言 + 硬件异常双路径）
├── backtrace.cmm                  # RISC-V 调用栈回溯（JAL/JALR 指令解析）
├── show_thread.cmm                # 线程列表（含栈使用率、邮箱关联）
├── select_thread.cmm              # 交互式线程选择对话框
├── show_all_backtrace.cmm         # 全部线程批量调用栈回溯
├── show_thread_swap.cmm           # 线程切换历史 + IRQ 耗时分析
├── show_sysinfo.cmm               # 当前线程名 + 中断嵌套深度
├── show_mailbox.cmm               # 邮箱/消息队列状态
├── show_ap_meminfo.cmm            # AP 内存聚合（dlmalloc + smallheap）
├── show_cp_meminfo.cmm            # CP 内存聚合（smallheap × 3）
├── show_ap_meminfo_sum.cmm        # AP 按文件汇总内存分配
├── print_dlmalloc_heap.cmm        # dlmalloc 堆遍历 + 泄漏检测 + 按模块统计
├── print_smallheap.cmm            # smallheap 双池分析 + 泄漏检测
├── print_mem_summary_by_file.cmm  # 按 .c 源文件聚合 dlmalloc 分配量
├── dwarf_enum_to_cmm.py           # ELF DWARF 枚举 → .cmm 字符串表
└── CLAUDE.md                      # Trace32 PRACTICE 脚本编码规范
```

#### 7.1.2 脚本分类

| 类别 | 脚本 | 用途 |
|------|------|------|
| **加载恢复** | restore.cmm, frame.cmm | 加载镜像、ELF 符号、恢复寄存器 |
| **异常分析** | errinfo.cmm | 解码异常原因（断言/硬件异常） |
| **调用栈** | backtrace.cmm, show_all_backtrace.cmm | 单线程/全线程回溯 |
| **线程分析** | show_thread.cmm, select_thread.cmm, show_thread_swap.cmm, show_sysinfo.cmm | 线程状态、切换历史、当前上下文 |
| **内存分析** | print_dlmalloc_heap.cmm, print_smallheap.cmm, print_mem_summary_by_file.cmm, show_ap_meminfo.cmm, show_cp_meminfo.cmm, show_ap_meminfo_sum.cmm | 堆使用率、泄漏检测、按文件汇总 |
| **IPC 分析** | show_mailbox.cmm | 邮箱状态 |
| **辅助工具** | dwarf_enum_to_cmm.py, dwarf_trace_to_cmm.py | 从 ELF 自动生成字符串表 |

---

### 7.2 镜像加载与符号恢复

#### 7.2.1 restore.cmm — 主加载脚本

**入口参数**：`do restore.cmm <ramdump_path> <elf_file>`

**执行流程**：

```
restore.cmm (&ramdump_path, &elf_file)
│
├── 1. RESet / SYStem.RESet         # 重置 Trace32 状态
├── 2. SYStem.CPU RV32              # 设置为 RISC-V 32 位模式
├── 3. SYStem.Up                    # 启动仿真 CPU
│
├── 4. 解析 CPU 类型
│   └── 从 elf_file 路径提取：cpu-ap.elf → "ap" / cpu-cp.elf → "cp"
│
├── 5. 构造 ILM/DLM 路径
│   └── &ilm = "<path>/<cpu>_ilm.bin"  (如 ap_ilm.bin / cp_ilm.bin)
│   └── &dlm = "<path>/<cpu>_dlm.bin"
│
├── 6. XIP 文件动态加载（可选）
│   └── 扫描 <path>/0x????????.xip 模式的文件
│   └── 从文件名提取地址，Data.LOAD.Binary 到该地址
│
├── 7. 加载内存镜像（两个别名地址）
│   ├── Data.LOAD.Binary IRAM.bin   0x10200000
│   ├── Data.LOAD.Binary IRAM.bin   0xC0200000    # 别名映射
│   ├── Data.LOAD.Binary PSRAM.bin  0x40000000
│   ├── Data.LOAD.Binary PSRAM.bin  0x80000000    # 别名映射
│   ├── Data.LOAD.Binary <ilm>      0x00008000
│   └── Data.LOAD.Binary <dlm>      0x00010000
│
├── 8. Data.LOAD.Elf <elf_file> /NoCODE /RelPath  # 仅加载符号表
│
├── 9. Register.Set PRV 0x3          # 设置特权级为 Machine Mode
│
├── 10. 调用 frame.cmm
│    └── &frame = Var.Value(exc_trace)
│    └── do frame.cmm &frame         # 从异常帧恢复寄存器
│
└── 11. Print "Restore RISC-V Ramdump Files!!"
```

**关键设计点**：

1. **双别名加载**：IRAM 和 PSRAM 在两个地址别名处加载，因为代码可能通过任一别名访问同一物理内存。

   | 物理内存 | Cache 别名（指令/数据可缓存） | Non-Cache 别名（直接访问） |
   |---------|---------------------------|-------------------------|
   | IRAM (512KB) | `0xC0200000` | `0x10200000` |
   | PSRAM | `0x80000000` | `0x40000000` |
   | ILM (TCM) | — | `0x00008000` |
   | DLM (TCM) | — | `0x00010000` |

   双别名存在的根因是芯片地址映射：同一物理 IRAM 被映射到两个 AHB 地址窗口——一个经过 Cache（0xC0200000），一个绕过 Cache（0x10200000）。代码中可能混用两个别名访问同一物理地址（如 `IRAM_BASE_ADDR_EXCEPTION_SHARE_NC` 通过 non-cache 别名写入，但 Crash 时的指针可能指向 cache 别名）。Trace32 必须两个地址都加载，否则符号解析会半数失效。

2. **/NoCODE 选项**：`Data.LOAD.Elf` 仅加载符号表（不加载 ELF 中的代码段），因为代码已经在内存镜像中
3. **PRV=3**：设置为 Machine Mode，确保可以访问所有 CSR 寄存器
4. **XIP 动态发现**：通过 `OS.FIRSTFILE("0x????????.xip")` 通配符匹配，自动加载所有 XIP 分区
5. **按 CPU 分离**：`ap_ilm.bin` / `cp_ilm.bin` 区分 AP 和 CP 的本地内存

> 这些加载地址必须与板子侧 `command.c` 中 `do_ramdump()` 的 `T_YModemFile[].buf` 地址严格一致。一致性约束详见 [5.1.6 节](#516-一致性约束)。

#### 7.2.2 frame.cmm — 寄存器恢复

**入口参数**：`do frame.cmm <cpu_frame>` （指向 `struct rt_hw_stack_frame` 的地址）

**核心逻辑**：

```cmm
&sp = &cpu_frame + sizeof(struct rt_hw_stack_frame)  // SP = 帧结束位置

Register.Set PC  Var.Value(((struct rt_hw_stack_frame*)&cpu_frame)->epc)
Register.Set X1  Var.Value(ra)
Register.Set X2  &sp                                   // 计算出的 SP
Register.Set X3  Var.Value(gp)
Register.Set X4  Var.Value(tp)
Register.Set X5  Var.Value(t0)
...（依次恢复 X5-X31：t0-t6, s0_fp, s1-s11, a0-a7, gp, tp）
Register.Set X31 Var.Value(t6)
```

**恢复的寄存器清单**（RISC-V 全部 31 个通用寄存器 + PC）：

| 寄存器 | ABI 名称 | 来源字段 | 用途 |
|--------|----------|----------|------|
| PC | pc | epc | 异常 PC |
| X1 | ra | ra | 返回地址 |
| X2 | sp | **计算值** | 栈指针 = frame + sizeof(frame) |
| X3 | gp | gp | 全局指针 |
| X4 | tp | tp | 线程指针 |
| X5-X7 | t0-t2 | t0-t2 | 临时寄存器 |
| X8 | s0/fp | s0_fp | 帧指针 |
| X9 | s1 | s1 | 保存寄存器 |
| X10-X17 | a0-a7 | a0-a7 | 函数参数 |
| X18-X27 | s2-s11 | s2-s11 | 保存寄存器 |
| X28-X31 | t3-t6 | t3-t6 | 临时寄存器 |

> **SP 的特殊计算**：SP 不是直接从 `rt_hw_stack_frame` 字段读取的，而是通过 `&cpu_frame + sizeof(struct rt_hw_stack_frame)` 计算得到。这与 RISC-V 异常入口处硬件不自动压栈的特性有关——异常帧是软件在入口处手动构建的，SP 指向异常帧之后。

---

### 7.3 异常现场分析

#### 7.3.1 errinfo.cmm — 异常类型解码

**双路径检测**：脚本首先尝试断言路径，再回退到硬件异常路径。

```
errinfo.cmm
│
├── 路径 1：断言检测
│   └── IF sYmbol.EXIST(g_osAssert)
│       ├── &core_id = g_osAssert->core
│       ├── IF core_id == 1 → "AP Assert"
│       ├── IF core_id == 2 → "CP Assert"
│       └── 输出："<AP/CP> Assert. File: xxx.c, Line: N, PC: 0x..."
│
└── 路径 2：硬件异常检测
    └── IF sYmbol.EXIST(g_osException)
        ├── &core_id = g_osException->core
        ├── mcause 解码 (低 5 位):
        │   ├── 0: "Instruction address misaligned"
        │   ├── 1: "Instruction access fault"
        │   ├── 2: "Illegal instruction"
        │   ├── 3: "Breakpoint"
        │   ├── 4: "Load address misaligned"
        │   ├── 5: "Load access fault"
        │   ├── 6: "Store/AMO address misaligned"
        │   └── 7: "Store/AMO access fault"
        │
        ├── mdcause 解码 (低 2 位):
        │   ├── 1: "PMP"       (物理内存保护违规)
        │   ├── 2: "Bus"       (总线错误)
        │   └── 3: "NICE long instruction"  (自定义长指令异常)
        │
        └── 输出："<AP/CP> Exception: <mcause_type>(<mdcause_type>). PC: <mepc>, Access Addr: <mtval>"
```

**支持的异常类型汇总**：

| mcause | 类型 | 说明 |
|--------|------|------|
| 0 | Instruction address misaligned | 指令地址未对齐 |
| 1 | Instruction access fault | 指令访问故障（PMP/总线） |
| 2 | Illegal instruction | 非法指令 |
| 3 | Breakpoint | 断点异常（EBREAK） |
| 4 | Load address misaligned | 加载地址未对齐 |
| 5 | Load access fault | 加载访问故障 |
| 6 | Store/AMO address misaligned | 存储地址未对齐 |
| 7 | Store/AMO access fault | 存储访问故障 |

| mdcause | 类型 | 说明 |
|---------|------|------|
| 1 | PMP | 物理内存保护违规 |
| 2 | Bus | 总线错误（AHB/AXI 异常响应） |
| 3 | NICE | 自定义长指令异常 |

**返回值**：脚本通过 `ENDDO "<info_string>"` 返回格式化的错误描述字符串，供 `LM620_Restore.cmm` 在 ERRINFO 区域显示。

---

### 7.4 调用栈回溯

#### 7.4.1 backtrace.cmm — RISC-V 单线程回溯

**入口参数**：`do backtrace.cmm <stack_start> <stack_end>`

**算法**：在栈范围 `[stack_start, stack_end)` 内，以 `sizeof(void*)` 为步长扫描每个字：

```
for addr = stack_start; addr < stack_end; addr += 4:
    value = Data.Long(D:addr)          // 读栈上的每个值
    func_name = sYmbol.FUNCTION(value) // 检查是否指向已知函数
    
    if func_name != "":
        检查 value 前一条指令是否为跳转并链接类指令:
        
        情况 1: 4 字节指令 (instr1 == 0xEF/0xE7/0x67)
            → JAL / JALR 类指令，确认是调用点
            → 打印: "func_name    ADDR:stack_addr -> code_addr"
        
        情况 2: 2 字节压缩指令 (op == 0x01)
            → C.JAL / C.JALR (压缩指令)
            → 检查 imm != 0 且 funct3 == 0x2000
            → 打印调用点
        
        情况 3: 2 字节压缩指令 (op == 0x02)
            → C.JALR (压缩指令，rs1 != x0)
            → 检查 rs1 != 0 且 funct3 == 0x8000
            → 打印调用点
```

**RISC-V 指令编码识别**：

| 场景 | 检查条件 | 对应指令 | 说明 |
|------|---------|---------|------|
| 4B 指令 | `(instr1 & 0x7F) ∈ {0x6F, 0x67}` | JAL / JALR | opcode 匹配 |
| 2B C.JAL | `(instr2 & 0x3) == 0x1, imm != 0, funct3 == 0x2000` | C.JAL | 压缩跳转并链接 |
| 2B C.JALR | `(instr2 & 0x3) == 0x2, rs1 != 0, funct3 == 0x8000` | C.JALR | 压缩间接跳转并链接 |

**原理**：RISC-V 的调用约定中，`JAL`/`JALR` 指令会将返回地址（PC+4 或 PC+2）写入 `ra` 寄存器。栈上保存的返回地址，其前一条指令必然是一个跳转并链接指令。脚本通过检查 `value-4` 或 `value-2` 处的指令编码来确认该地址确实是调用返回点，避免将普通函数指针误认为栈帧。

#### 7.4.2 show_all_backtrace.cmm — 全线程批量回溯

遍历 `g_osThreadList` 链表，对每个线程调用 `backtrace.cmm`：

```cmm
WHILE &thread_head != &thread_next
    &thread_struct = &thread_next - &thread_offset
    &start = ((osThread_t*)&thread_struct)->stackAddr
    &size  = ((osThread_t*)&thread_struct)->stackSize
    &sp    = ((osThread_t*)&thread_struct)->sp
    
    PRINTF "=>THREAD: %16s  Struct: 0x%08x" name &thread_struct
    do backtrace.cmm &sp &end       // 从线程当前的 SP 开始回溯
    
    &thread_next = next
```

> **注意**：对非运行态线程，回溯的是线程被切换出去时的调用栈。调度器在上下文切换时将寄存器现场保存在线程栈上，`osThread_t->sp` 指向保存的现场。

---

### 7.5 线程分析

#### 7.5.1 show_thread.cmm — 线程列表

遍历 `g_osThreadList` 链表，打印每个线程的详细信息：

**输出字段**：

| 字段 | 来源 | 说明 |
|------|------|------|
| Name | `osThread_t->name` | 线程名称 |
| Pri | `osThread_t->currentPriority` | 当前优先级 |
| State | `osThread_t->stat & 0x0F` | Init/Ready/Suspend/Running/Close |
| maxStack | 遍历栈查找 0x23 填充字节 | 栈使用百分比（0x23 是栈初始化填充值） |
| rmanTick | `osThread_t->remainingTick` | 剩余 tick 数 |
| osThread_t | 结构体地址 | 线程控制块地址 |
| MsgCount | `osMb_t->entry` | 邮箱当前消息数（仅当 userData 是邮箱时） |
| MaxMsgCount | `osMb_t->max_entry` | 邮箱最大容量 |

**栈使用率计算**（`stack_used` 子程序）：从栈底向栈顶扫描，找到第一个不是 `0x23` 的字节，用剩余空间除以总空间得到使用率。`0x23` 是 RTOS 在创建线程时填充的栈哨兵值。

**当前线程识别**：如果 `&thread_struct == g_osCurrentThread`，状态强制设为 `Running`。

**附加功能**：如果 `osThreadSwapArray` 符号存在，追加打印最近 100 条线程切换记录（线程名 + 时间戳 + 时间差）。

#### 7.5.2 select_thread.cmm — 线程选择器

交互式下拉对话框，列出所有线程名，用户选择后返回该线程的 `osThread_t` 地址。

**调用方式**：
```cmm
do select_thread.cmm
ENTRY &thread_struct      // 获取返回值
```

**用途**：供 `LM620_Restore.cmm` 的 **ThreadBT** 按钮使用——用户选择一个线程后，对该线程执行 `backtrace.cmm` + `frame.cmm`。

#### 7.5.3 show_sysinfo.cmm — 系统概览

简洁的状态摘要（显示在 `LM620_Restore.cmm` 顶部）：

```
SYSINFO: THREAD[idle]  IRQNEST[0]
```

从 `g_osCurrentThread->name` 和 `g_osInterruptNest` 读取，快速显示崩溃时正在执行的线程和中断嵌套深度。

#### 7.5.4 show_thread_swap.cmm — 调度历史

分析两个数组：

1. **osThreadSwapArray**（100 条记录，8B/条）：
   - `+0`: 线程指针
   - `+4`: 时间戳
   - 输出：线程名 + 切换时间 + 时间间隔

2. **osIrqSwapArray**（100 条记录，12B/条）：
   - `+0`: IRQ 号
   - `+4`: 进入时间
   - `+8`: 退出时间
   - 输出：IRQ 号 + 持续时间 + 空闲间隔

#### 7.5.5 依赖的 OS 符号与字段映射

线程分析脚本依赖以下 OS 全局变量和结构体字段，它们必须在 ELF 符号表中存在才能正常工作。

**全局符号**：

| 符号 | 类型 | 使用者 | 说明 |
|------|------|--------|------|
| `g_osThreadList` | `osList_t` | show_thread / select_thread / show_all_backtrace / show_mailbox | 线程链表头，通过 `&g_osThreadList` 取头节点地址，`g_osThreadList.next` 取第一个线程的 `resource_node` |
| `g_osCurrentThread` | `osThread_t*` | show_thread / show_sysinfo | 当前运行线程指针。show_thread 用它标记 Running 状态；show_sysinfo 读 `->name` 显示"SYSINFO: THREAD[xxx]" |
| `g_osInterruptNest` | `volatile uint8_t` | show_sysinfo | 中断嵌套深度，定义在 `irq.c`，显示"SYSINFO: IRQNEST[N]" |

**线程链表遍历算法**：

所有线程脚本通过统一的链表遍历模式访问线程：

```cmm
; 1. 读取 resource_node 到 osThread_t 的偏移量
&thread_offset = offsetof(osThread_t, resource_node)

; 2. 取链表第一个节点
&thread_next = Var.Value(g_osThreadList.next)

; 3. 遍历直到回到链表头
WHILE &thread_next != Var.Value((void*)&g_osThreadList)
    ; 4. 从节点地址反推线程结构体地址
    &thread_struct = &thread_next - &thread_offset
    
    ; 5. 读取各字段
    &name  = Var.String(((osThread_t*)&thread_struct)->name)
    &stat  = Var.Value(((osThread_t*)&thread_struct)->stat) & 0x0F
    &sp    = Var.Value(((osThread_t*)&thread_struct)->sp)
    ...
    
    ; 6. 识别当前线程
    IF &thread_struct == Var.Value((void*)g_osCurrentThread)
        ; 状态强制设为 Running
    
    ; 7. 移动到下一节点
    &thread_next = Var.Value(((osThread_t*)&thread_next)->resource_node.next)
```

**`osThread_t` 字段使用矩阵**：

| 字段 | show_thread | select_thread | show_all_backtrace | show_mailbox | show_sysinfo | show_thread_swap |
|------|:---:|:---:|:---:|:---:|:---:|:---:|
| `resource_node` (节点地址→结构体偏移) | ✓ | ✓ | ✓ | ✓ | | |
| `resource_node.next` (遍历) | ✓ | ✓ | ✓ | ✓ | | |
| `name` (线程名) | ✓ | ✓ | ✓ | | ✓ | ✓ |
| `stat` (状态, & 0x0F) | ✓ | | | | | |
| `currentPriority` (优先级) | ✓ | | | | | |
| `remainingTick` (剩余tick) | ✓ | | | | | |
| `stackAddr` (栈基址) | ✓ | | ✓ | | | |
| `stackSize` (栈大小) | ✓ | | ✓ | | | |
| `sp` (当前栈指针) | | | ✓ | | | |
| `userData` (→ osMb_t) | ✓ | | | ✓ | | |

**`stackAddr`/`stackSize`/`sp` 的区别**：

- `stackAddr`：线程栈的**基地址**（低地址），由 `osThreadCreate` 时分配
- `stackSize`：栈总大小（字节），如 4096
- `sp`：线程被切出时保存的**当前栈指针**（上下文切换帧地址）
- `backtrace.cmm` 以 `sp` 为扫描起点，`stackAddr + stackSize` 为扫描终点
- `show_thread.cmm` 的 `stack_used` 子程序从 `stackAddr` 向 `sp` 方向扫描 0x23 哨兵值计算使用率

---

### 7.6 内存分析

#### 7.6.1 AP 内存分析链路

```
LM620_Restore.cmm
├── MemTrace 按钮 → show_ap_meminfo.cmm  (AP 详细)
│   ├── do print_dlmalloc_heap.cmm &g_osApSystemMem     # 系统堆
│   ├── do print_dlmalloc_heap.cmm &g_osApShareBuf      # 共享缓冲
│   ├── do print_smallheap.cmm    &g_osApUpNode         # UpNode 堆
│   └── do print_smallheap.cmm    g_osApModemShareBufPtr # Modem 共享缓冲
│
└── MemSummary 按钮 → show_ap_meminfo_sum.cmm (AP 按文件汇总)
    └── do print_mem_summary_by_file.cmm &g_osApSystemMem
```

#### 7.6.2 CP 内存分析链路

```
LM620_Restore.cmm
└── MemTrace 按钮 (CP) → show_cp_meminfo.cmm
    ├── do print_smallheap.cmm &g_osCpSystemMem         # CP 系统堆
    ├── do print_smallheap.cmm &g_osCpHarqBuf           # HARQ 缓冲
    └── do print_smallheap.cmm g_osCpModemShareBufPtr   # Modem 共享缓冲
```

#### 7.6.3 print_dlmalloc_heap.cmm — dlmalloc 堆分析

**入口参数**：`do print_dlmalloc_heap.cmm <memheap>`（指向 `osDlmalloc_t` 结构体的地址）

**分析内容**：

1. **基本统计**：
   - `total`: 堆总大小
   - `max_used`: 历史最大使用量
   - `used`: 当前使用量 = total - 可用空间
   - `user_used`: 用户实际分配量（含 chunk 头开销）
   - `top_size`: top chunk 大小
   - `max_chunk`: 最大空闲块
   - `navail`: 空闲块数量
   - 使用率百分比（最大、当前、用户）

2. **内存泄漏检测**（需 `osMallocTrace` 符号存在）：
   - 遍历所有已分配的 chunk
   - 读取 `osMemTrace_t` 信息：`file`（源文件名）、`line`（行号）、`size`（分配大小）、`user`（调用者标识）
   - 按模块分类统计：

   | 模块 | 统计变量 |
   |------|---------|
   | slog_helper | 日志辅助模块 |
   | l2com_mem | L2 通信内存 |
   | pool_caching | 缓存池 |
   | osi_rt_thread | RT 线程 |
   | ipc | 核间通信 |
   | thread | 线程管理 |
   | ip4_nat | IPv4 NAT |
   | ps_com | PS 通信 |
   | drv_i2s | I2S 驱动 |
   | other_sum | 其他所有模块 |

**输出示例**：
```
=================== Mem Summary Info ==================
total: 262144, max Used: 189456, used: 145632, user used: 132104, top: 116512, max chunk: 98240, free chunks: 47
max used rate: 72%, used rate: 55%, user used rate: 50%
slog_helper: 12340, l2com_mem: 45600, pool_caching: 8900, osi_rt_thread: 12300
ipc: 34500, thread: 5600, ip4_nat: 2300, ps_com: 6700, drv_i2s: 3400
```

#### 7.6.4 print_smallheap.cmm — smallheap 双池分析

**入口参数**：`do print_smallheap.cmm <memheap>`（指向 `memHeap_t` 结构体的地址）

**双池结构**：smallheap 分为 big pool 和 small pool（可选），分别管理不同大小的内存块。

**分析内容**：

1. **基本统计**（每个 pool）：
   - `total` / `max_used` / `used` / `user_used`
   - `bitmap`: 空闲位图
   - 使用率百分比

2. **按大小桶统计**（32 个桶）：
   ```
   alloc size[00016] times: 23, max times: 45
   alloc size[00032] times: 156, max times: 200
   ...
   ```
   每个桶对应 `(i+1) << min_shift` 字节的分配大小。

3. **内存泄漏检测**（需 `osMallocTrace` 存在）：
   - 遍历每个 `memUnit_t`
   - 检查 `cur_size & 0x8000`（bit15 标记已分配）
   - 输出：文件名、行号、大小、调用者、地址

#### 7.6.5 print_mem_summary_by_file.cmm — 按文件汇总

遍历 dlmalloc 所有已分配 chunk，按源文件名聚合总分配量，输出每个 `.c` 文件的累计分配字节数。用于快速定位哪个模块消耗内存最多。

---

### 7.7 邮箱/消息队列分析

#### show_mailbox.cmm

遍历所有线程，找到 `userData` 指向邮箱对象的线程，打印邮箱状态：

| 字段          | 来源                   | 说明      |
| ----------- | -------------------- | ------- |
| Name        | 线程名                  | 邮箱所属线程  |
| capacity    | `osMb_t->size`       | 邮箱容量    |
| count       | `osMb_t->entry`      | 当前消息数   |
| write_index | `osMb_t->in_offset`  | 写指针偏移   |
| read_index  | `osMb_t->out_offset` | 读指针偏移   |
| osMb_t      | 地址                   | 邮箱控制块地址 |

**用途**：诊断线程间通信问题——查看消息是否堆积（count 接近 capacity）、是否有消息丢失等。

---

### 7.8 GUI 主界面

#### LM620_Restore.cmm — 分析工作台

**界面布局**：

```
┌──────────────────────────────────────────────────────────────────┐
│  LM620 Ramdump Tool                                              │
├──────────────────────────────────────────────────────────────────┤
│  Ramdump : [________________________] [...]                      │
│  Elf File: [________________________] [...]    [LOAD]            │
│  SYSINFO: THREAD[idle]  IRQNEST[0]                               │
│  ERRINFO: AP Exception: Load access fault(Bus). PC: 0x..., ...   │
├──────────────────────────────────────────────────────────────────┤
│  [ShowThread] [BackTrace] [ThreadBT] [AllThreadBT] [MSG Box]    │
│  [MemTrace]   [MemSummary] [ThreadSwap]                         │
│                                            [Clear] [Close]       │
└──────────────────────────────────────────────────────────────────┘
```

**11 个分析按钮及其功能**：

| 按钮 | 执行脚本 | 功能 |
|------|---------|------|
| **ShowThread** | show_thread.cmm | 显示全部线程状态 + 栈使用率 + 线程切换历史 |
| **BackTrace** | backtrace.cmm + frame.cmm | 对异常线程（`exc_trace` 指向的栈帧）回溯调用栈并恢复寄存器 |
| **ThreadBT** | select_thread.cmm → backtrace + frame | 交互式选择线程 → 回溯其调用栈 |
| **AllThreadBT** | show_all_backtrace.cmm | 所有线程批量调用栈回溯 |
| **MSG Box** | show_mailbox.cmm | 显示全部邮箱/消息队列状态 |
| **MemTrace** | show_ap_meminfo.cmm 或 show_cp_meminfo.cmm | 按 CPU 类型显示内存分析（堆使用率 + 泄漏检测） |
| **MemSummary** | show_ap_meminfo_sum.cmm 或 show_cp_meminfo.cmm | 按源文件汇总内存分配 |
| **ThreadSwap** | show_thread_swap.cmm | 显示线程切换和 IRQ 耗时历史 |
| **Clear** | AREA.CLEAR | 清空输出区域 |
| **Close** | DIALOG.END | 关闭界面 |

**LOAD 流程**：
1. 校验 ramdump_path 和 elf_file 非空
2. 解析 CPU 类型（`cpu-ap.elf` → "ap" / `cpu-cp.elf` → "cp"）
3. 打开输出文件：`<path>/<cpu>_PrintData.txt`
4. 调用 `restore.cmm` 加载镜像和符号
5. 启用所有分析按钮（初始全部禁用）
6. 打开 `Frame.view /Locals /Args` 显示局部变量和参数
7. 调用 `show_sysinfo.cmm` 和 `errinfo.cmm` 显示顶部状态行

---

### 7.9 辅助工具

#### 7.9.1 dwarf_enum_to_cmm.py

从 ELF DWARF 调试信息中提取枚举值，自动生成 `.cmm` 字符串表。

**用法**：`python3 dwarf_enum_to_cmm.py <elf_file> [enum_type_name]`

**工作原理**：
```
readelf --debug-dump=info <elf> → 解析 DWARF
    → 查找 DW_TAG_enumeration_type
    → 提取 DW_TAG_enumerator (name + DW_AT_const_value)
    → 过滤以 _TRACE_EVENT_MAX 结尾的枚举
    → 生成: &_st_0="EVENT_NAME" 格式的 .cmm 代码
```

---

### 7.10 脚本调用关系图

```
LM620_Restore.cmm (GUI 主界面)
│
├── LOAD 按钮
│   └── restore.cmm
│       └── frame.cmm                        # 恢复 CPU 寄存器
│
├── ShowThread 按钮
│   └── show_thread.cmm                     # 线程列表 + 栈使用率
│
├── BackTrace 按钮
│   ├── backtrace.cmm <exc_trace>           # 异常线程回溯
│   └── frame.cmm <exc_trace>               # 恢复异常现场寄存器
│
├── ThreadBT 按钮
│   ├── select_thread.cmm                   # 交互式选线程 → &thread_struct
│   ├── backtrace.cmm <sp> <end>            # 选中线程回溯
│   └── frame.cmm <sp>                      # 恢复选中线程寄存器
│
├── AllThreadBT 按钮
│   └── show_all_backtrace.cmm
│       └── backtrace.cmm (× N threads)     # 每线程回溯
│
├── MSG Box 按钮
│   └── show_mailbox.cmm                    # 邮箱状态
│
├── MemTrace 按钮
│   ├── show_ap_meminfo.cmm (AP)
│   │   ├── print_dlmalloc_heap.cmm         # dlmalloc 堆分析
│   │   └── print_smallheap.cmm (×2)        # smallheap 分析
│   └── show_cp_meminfo.cmm (CP)
│       └── print_smallheap.cmm (×3)        # smallheap 分析
│
├── MemSummary 按钮
│   └── show_ap_meminfo_sum.cmm
│       └── print_mem_summary_by_file.cmm   # 按文件汇总
│
├── ThreadSwap 按钮
│   └── show_thread_swap.cmm                # 调度历史
│
│
├── 顶部状态栏
│   ├── show_sysinfo.cmm                    # SYSINFO 行
│   └── errinfo.cmm                         # ERRINFO 行
│
└── 辅助工具（离线运行）
    └── dwarf_enum_to_cmm.py                # 生成枚举字符串表
```

---

## 8. 移植指南

本章以 **STM32F4（ARM Cortex-M4）+ RT-Thread** 为目标平台，按四个阶段逐步推进 ramdump 的移植。每个阶段有明确的输入、输出和验证方式，不依赖后续阶段即可独立验证。

### 8.1 移植总览与阶段规划

```
Phase 1: 裸机 UART 传输         Phase 2: 异常入口对接          Phase 3: 线程感知               Phase 4: 内存分析
(不依赖 OS)                     (+ RT-Thread 异常框架)        (+ RT-Thread 线程管理)         (+ RT-Thread 分配器)


 实现 UART 驱动                  接入 HardFault_Handler        遍历 RT-Thread 线程列表         适配 memheap/slab 堆分析
 实现 YMODEM 发送                保存 ARM 异常现场             实现 ARM Thumb-2 调用栈回溯      适配 mailbox IPC 分析
 实现 CLI (md/ramdump)          调用 DTools_Dump()           适配 show_thread.cmm            适配 show_mailbox.cmm
                                适配 errinfo.cmm              适配 backtrace.cmm
                                适配 frame.cmm / restore.cmm
    │                              │                             │                              │
    ▼                              ▼                             ▼                              ▼
 手动调用 ramdump()              人为触发空指针                 多线程场景崩溃                  内存泄漏诊断
 → PC 收到 SRAM.bin              → 自动进入 dump               → 全线程回溯正确                → 堆分析报告正确
```

**阶段依赖关系**：Phase 1 是所有后续阶段的基础（传输通道必须先通）。Phase 2 依赖 Phase 1 的 IO 能力。Phase 3 和 Phase 4 彼此独立，但都依赖 Phase 2 的异常入口。Phase 4 可按需裁剪。

**每个阶段的共同模式**：① 板子侧实现 → ② PC 侧 Trace32 脚本适配 → ③ 验证测试。

---

### 8.2 Phase 1: 裸机 UART 传输验证

**目标**：不依赖任何 OS 功能，仅通过 UART + YMODEM 将指定内存区域传输到 PC。

**输入**：STM32 开发板、USB 转串口适配器、SecureCRT 终端。

**不需要**：异常处理、线程调度、堆分配器。bare-metal 即可运行。

#### 8.2.1 需要实现的内容

**A. 内存区域定义**

```c
// chip_reg_base.h — STM32F407 内存布局（单核）
#define BASE_SRAM        0x20000000
#define LEN_SRAM         (128 * 1024)    // STM32F407 有 128KB SRAM
#define BASE_CCM         0x10000000      // CCM RAM（内核紧耦合内存，可选）
#define LEN_CCM          (64 * 1024)
#define BASE_FLASH       0x08000000      // 内部 Flash

// 双核平台兼容宏（单核 STM32 无对应硬件的填 0 即可）
#define BASE_SH_RAM0     BASE_SRAM
#define LEN_SH_RAM       LEN_SRAM
#define BASE_PSRAM       0
#define LEN_PSRAM        0
#define BASE_ILM         0
#define LEN_ILM_AP       0
#define BASE_DLM         0
#define LEN_DLM_AP       0
#define BASE_CP_ILM      0
#define LEN_ILM_CP       0
#define BASE_CP_DLM      0
#define LEN_DLM_CP       0
```

**B. UART 驱动**

基于 STM32 HAL 库实现三个 IO 函数：

```c
#include "stm32f4xx_hal.h"

// 使用 USART2 作为 ramdump 控制台（PA2=TX, PA3=RX）
static UART_HandleTypeDef g_ramdump_uart;

void Uart_Init(uint32_t baudrate, uint32_t nPORT, bool_t rtsCtsEnable)
{
    if (baudrate == 0) baudrate = 115200;
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_USART2_CLK_ENABLE();

    GPIO_InitTypeDef gpio = {
        .Pin = GPIO_PIN_2 | GPIO_PIN_3,
        .Mode = GPIO_MODE_AF_PP,
        .Pull = GPIO_NOPULL,
        .Speed = GPIO_SPEED_FREQ_HIGH,
        .Alternate = GPIO_AF7_USART2,
    };
    HAL_GPIO_Init(GPIOA, &gpio);

    g_ramdump_uart.Instance        = USART2;
    g_ramdump_uart.Init.BaudRate   = baudrate;
    g_ramdump_uart.Init.WordLength = UART_WORDLENGTH_8B;
    g_ramdump_uart.Init.StopBits   = UART_STOPBITS_1;
    g_ramdump_uart.Init.Parity     = UART_PARITY_NONE;
    g_ramdump_uart.Init.Mode       = UART_MODE_TX_RX;
    HAL_UART_Init(&g_ramdump_uart);
}

int32_t Uart_Getc(uint32_t timeout)
{
    uint8_t ch;
    uint32_t start = HAL_GetTick();
    while (HAL_UART_Receive(&g_ramdump_uart, &ch, 1, 1) != HAL_OK) {
        if (HAL_GetTick() - start > timeout) return -1;
    }
    return ch;
}

void Uart_Putc(uint8_t ch)
{
    HAL_UART_Transmit(&g_ramdump_uart, &ch, 1, HAL_MAX_DELAY);
}
```

**C. 转储区域定义**

```c
// do_ramdump() 中 — 仅转储 SRAM（单核，无 ILM/DLM/PSRAM）
static int32_t do_ramdump(int32_t argc, char *const argv[])
{
    T_YModemFile files[3];
    int32_t count = 0;

    if (BASE_SRAM && LEN_SRAM) {
        files[count].buf  = (uint8_t *)BASE_SRAM;
        files[count].size = LEN_SRAM;
        files[count].name = "SRAM.bin";
        count++;
    }
    if (BASE_CCM && LEN_CCM) {
        files[count].buf  = (uint8_t *)BASE_CCM;
        files[count].size = LEN_CCM;
        files[count].name = "CCM.bin";
        count++;
    }
    return ymodem_send(files, count, 1);
}
```

**D. 复位实现**

```c
static int32_t do_reboot(int32_t argc, char *const argv[])
{
    NVIC_SystemReset();         // ARM Cortex-M 标准复位
    return 0;
}
```

#### 8.2.2 IO 函数指针注册

YMODEM / DIAG / CLI 等上层协议不关心传输通道的具体实现，只通过三个函数指针完成 IO：

```c
g_Getc     = Uart_Getc;      // 接收
g_Putc     = Uart_Putc;      // 发送
g_PutBytes = NULL;           // YMODEM 不需要批量发送（逐字节 Putc 即可）
```

如果后续要换成其他传输通道（如 SPI），只需替换这三个函数指针的赋值，上层协议代码完全不动。详见 [6.1 节](#61-io-函数指针接口传输抽象层)。

#### 8.2.3 需要实现的模块清单

此阶段需要从零实现的模块：

```
├── ymodem.c / ymodem.h        # YMODEM 协议栈（标准 X/YMODEM 协议，CRC16 校验）
├── console.c / console.h      # 控制台格式化输出
├── cli.c / clitype.h          # 命令行解析循环
├── command.c / command.h      # 命令表（按 STM32 内存布局定义转储区域）
├── dtools_dump.c / .h         # DIAG 协议处理循环（UART 路径）
├── uart.c / uart.h            # UART 驱动（HAL 实现，平台相关）
├── chip_reg_base.h            # 内存区域基地址宏（平台相关）
└── CMakeLists.txt             # 构建配置（平台相关）
```

#### 8.2.4 构建配置

```cmake
# CMakeLists.txt — STM32 目标
if(BUILD_TARGET STREQUAL "STM32F4")
    target_sources(ramdump PRIVATE
        uart/uart_stm32.c
        dtools_dump/dtools_dump.c        # UART 路径
    )
endif()
```

#### 8.2.5 验证方式

1. `main()` 中初始化 UART 后直接调用 `ramdump()`（不进 CLI）
2. PC 端 SecureCRT 连接串口 → Transfer → Receive YMODEM
3. 确认接收到 `SRAM.bin`，文件大小 = 128KB（`LEN_SRAM`）

**验收标准**：PC 端成功接收到完整的 SRAM 镜像文件。

---

### 8.3 Phase 2: 异常入口对接

**目标**：CPU 异常时自动进入 dump 流程，PC 端能定位崩溃地址和异常原因。

**新增依赖**：RT-Thread 的异常处理框架（或裸机的 `startup_xxx.s` 异常向量表）。

#### 8.3.1 ARM Cortex-M 异常入口原理

与 RISC-V 的核心区别：**硬件自动压栈**。

```
RISC-V:                           ARM Cortex-M:
  软件逐条保存 32 个 GPR             硬件自动压栈 8 个寄存器
  sw ra, 124(sp)                    {r0, r1, r2, r3, r12, lr, pc, xpsr}
  sw sp, 120(sp)                    SP 自动偏移 -32 字节
  ...                               软件只需保存剩余寄存器 (r4-r11)
  sw x1, 0(sp)

  软件保存 mcause/mepc/mstatus       异常原因从 SCB 寄存器读取:
  到栈帧中                               CFSR / HFSR / MMFAR / BFAR
```

**移植要点**：

| RISC-V | ARM Cortex-M | 说明 |
|--------|-------------|------|
| `mcause` | `SCB->CFSR` / `SCB->HFSR` | 异常原因分类不同 |
| `mepc` | 硬件压栈帧 `[sp + 0x18]` | 无需 CSR 读取 |
| `mtval` | `SCB->MMFAR` / `SCB->BFAR` | 故障地址 |
| `osInterruptDisable()` | `__disable_irq()` | CMSIS 标准 API |

#### 8.3.2 异常现场保存结构体

```c
// ARM Cortex-M 硬件自动压栈的帧结构
typedef struct {
    uint32_t r0;
    uint32_t r1;
    uint32_t r2;
    uint32_t r3;
    uint32_t r12;
    uint32_t lr;
    uint32_t pc;     // 崩溃指令地址
    uint32_t xpsr;   // 程序状态寄存器
} arm_stack_frame_t;

// 异常现场记录（全局变量，供 DTools_Dump 和 Trace32 脚本引用）
typedef struct {
    arm_stack_frame_t *frame;  // 指向栈上的硬件压栈帧
    uint32_t cfsr;             // SCB->CFSR
    uint32_t hfsr;             // SCB->HFSR
    uint32_t mmfar;            // SCB->MMFAR (MemManage 故障地址)
    uint32_t bfar;             // SCB->BFAR (BusFault 故障地址)
} stm32_exception_t;

// 存放在不会溢出的全局区（如 .noinit 段，确保复位后保留）
static stm32_exception_t g_stm32_exception;
```

#### 8.3.3 异常入口实现（不依赖 RT-Thread 的版本）

直接覆盖启动文件中的弱函数：

```c
// 异常原因解码（等价于 mcause 解码）
static const char *decode_fault(void)
{
    if (SCB->HFSR & SCB_HFSR_FORCED_Msk) {
        if (SCB->CFSR & SCB_CFSR_MMFSR_Msk) return "MemManage";
        if (SCB->CFSR & SCB_CFSR_BFSR_Msk)  return "BusFault";
        if (SCB->CFSR & SCB_CFSR_UFSR_Msk)  return "UsageFault";
        return "HardFault";
    }
    return "Unknown";
}

void HardFault_Handler(void)
{
    // ① 保存 ARM 异常现场（等价于 g_osException 保存）
    g_stm32_exception.frame = (arm_stack_frame_t *)__get_MSP();
    g_stm32_exception.cfsr  = SCB->CFSR;
    g_stm32_exception.hfsr  = SCB->HFSR;
    g_stm32_exception.mmfar = SCB->MMFAR;
    g_stm32_exception.bfar  = SCB->BFAR;

    // ② 关中断（防止 PendSV 等打断 dump 流程）
    __disable_irq();

    // ③ 进入 ramdump
    DTools_Dump();

    // ④ DTools_Dump 返回后（reboot 命令），复位系统
    NVIC_SystemReset();
}

// 转发其他可配置故障到 HardFault
void MemManage_Handler(void)   __attribute__((alias("HardFault_Handler")));
void BusFault_Handler(void)    __attribute__((alias("HardFault_Handler")));
void UsageFault_Handler(void)  __attribute__((alias("HardFault_Handler")));
```

#### 8.3.4 与 RT-Thread 异常框架集成

RT-Thread 的 BSP 通常已经提供了 `HardFault_Handler` 或 `rt_hw_hard_fault_handler`。集成方式不是在 RT-Thread 的 handler 中替换，而是**在 RT-Thread 打印完异常信息之后、系统停止之前**插入 `DTools_Dump()`：

```
RT-Thread 异常处理流程 (已有):
  rt_hw_hard_fault_handler()          ← RT-Thread BSP 已实现
    ├─ 读取 SCB->CFSR/HFSR
    ├─ 打印异常类型、故障地址
    ├─ 打印寄存器快照 (r0-r12, lr, pc, xpsr)
    ├─ 打印当前线程名和调用栈
    │
    └─ ★ 此处插入 DTools_Dump()        ← 需要新增
         │
         └─ while(1) 或 RT-Thread 复位

方法: 在 rt_hw_hard_fault_handler() 末尾, while(1) 或 RT_ASSERT(0) 之前,
      添加:
        extern void DTools_Dump(void);
        DTools_Dump();
```

**注意**：SCB 寄存器值在进入 `HardFault_Handler` 时就已经固化，`DTools_Dump()` 中再读取也是有效的。但异常帧指针（`__get_MSP()` 在进入 handler 时的值）需要在 `DTools_Dump()` 调用前保存。

#### 8.3.5 此阶段需要适配的 Trace32 脚本

| 脚本 | 适配内容 | 工作量 |
|------|---------|--------|
| **restore.cmm** | `Data.LOAD.Binary` 地址改为 `0x20000000`（STM32 SRAM） | 小（改几个地址） |
| **frame.cmm** | RISC-V 32 寄存器偏移 → ARM 8 寄存器硬件压栈帧（`sp+0x00~sp+0x1C`） | 中（帧格式完全重写） |
| **errinfo.cmm** | `mcause` 查表 → `SCB->CFSR/HFSR` 位判断（见 [8.8.5-C3](#885-层次-c架构适配换-cpu-架构)） | 中（重写解码逻辑） |

不需要的：`show_thread.cmm`、`backtrace.cmm`、`show_mailbox.cmm`、`print_dlmalloc_heap.cmm` 等（Phase 3/4 才需要）。

#### 8.3.6 验证方式

1. 在应用代码中故意触发空指针访问：`*(volatile uint32_t *)0x00000000 = 0;`
2. 确认 CPU 进入 HardFault_Handler → `DTools_Dump()` → CLI 提示符出现在串口终端
3. 执行 `ramdump` 命令，PC 端接收镜像
4. Trace32 用 `restore.cmm` 加载 SRAM.bin + ELF → 查看崩溃 PC

**验收标准**：设备崩溃后自动进入 CLI，能在 Trace32 中定位崩溃地址和异常类型。

---

### 8.4 Phase 3: 线程感知与调用栈回溯

**目标**：Trace32 可以查看崩溃时刻所有线程的状态和调用栈。

**新增依赖**：RT-Thread 的线程管理（`rt_thread_t` 结构体、对象容器）。

#### 8.4.1 线程信息获取原理

Trace32 需要从 dump 镜像中获取每个线程的以下信息：

```
对每个线程获取: {名称, sp, 栈基址, 栈大小, 状态, 优先级}
```

其他 RTOS 通常通过全局链表头遍历线程。RT-Thread 的等价路径：

```
通用 RTOS                        RT-Thread
───────────────────────────     ───────────────────────────
g_osThreadList 全局链表头  →    rt_object_get_information(RT_Object_Class_Thread)
                                或直接遍历 rt_object_container 中的线程对象

osThread_t->name               → rt_thread_t->name
osThread_t->sp                 → rt_thread_t->sp
osThread_t->stackAddr          → rt_thread_t->stack_addr
osThread_t->stackSize          → rt_thread_t->stack_size
osThread_t->stat               → rt_thread_t->stat (值可能不同)
osThread_t->currentPriority    → rt_thread_t->current_priority
```

**适配方法**：Trace32 脚本逻辑不变，只改三样东西：
1. 全局变量名（`g_osThreadList` → RT-Thread 的线程容器符号）
2. 结构体字段偏移量（`show_thread.cmm` 中各字段的 `+N` 偏移）
3. 状态常量值（`OS_THREAD_READY=0x01` → `RT_THREAD_READY=...`）

如果 RT-Thread 使用对象容器而非纯链表，`show_thread.cmm` 的遍历方式需从"跟随 `next` 指针"改为"遍历容器数组"。但脚本其余部分（状态解码、栈使用率计算、输出格式）完全不变。

#### 8.4.2 上下文切换帧兼容性

**原理**：`backtrace.cmm` 从 `rt_thread_t->sp` 指向的栈帧中，通过识别指令编码（ARM: `BL`/`BLX`/`PUSH {..., lr}`）找到返回地址，逐帧向上回溯调用链。

RISC-V 和 ARM 的上下文切换帧布局不同，但核心信息相同：

```
RISC-V 帧 (osContextSwitch):       ARM 帧 (PendSV):
  sp+0x00: ra (返回地址)             sp+0x00: r4 (软件保存)
  sp+0x04: ra                       ...
  sp+0x08: mstatus.MIE              sp+0x14: lr (返回地址)
  ...                               sp+0x18: pc (硬件自动压栈)
  sp+0x7C: t6                       sp+0x1C: xpsr
```

`frame.cmm` 需要改为解析 ARM 帧格式。如果 RT-Thread 的 PendSV 帧布局与上述不同，只需修改脚本中的偏移量——原则不变。

#### 8.4.3 ARM Thumb-2 调用栈回溯适配

`backtrace.cmm` 的核心算法不变（在栈范围 `[sp, stack_end)` 内扫描返回地址），但指令识别逻辑需从 RISC-V `JAL`/`JALR` 改为 ARM Thumb-2 `BL`/`BLX`：

| 步骤 | RISC-V 方式 | ARM Cortex-M 方式 |
|------|-----------|-------------------|
| 获取当前 PC | `Register(PP)` → `&mepc` | `Register(PP)` → 硬件压栈的 PC |
| 获取返回地址 | 扫描栈上 `ra` → 反汇编 `JAL`/`JALR` 确认 | 扫描栈上 `lr` → 检查 `value[-2]` 处 `BL`/`BLX` 指令编码 |
| 识别函数入口 | `JAL` 的目标地址 | `BL` 的目标地址 |
| Thumb 标志 | 无 | bit[0] = 1 表示 Thumb 模式（ARM Cortex-M 固定为 1） |

详见 [8.8.5-C2](#885-层次-c架构适配换-cpu-架构)。

#### 8.4.4 此阶段需要适配的 Trace32 脚本

| 脚本 | 适配内容 | 工作量 |
|------|---------|--------|
| **show_thread.cmm** | 线程遍历 API + 字段偏移量 + 状态常量 + 栈哨兵值 | 中 |
| **backtrace.cmm** | RISC-V `JAL`/`JALR` → ARM `BL`/`BLX` 指令解析 | 大（最复杂的单脚本适配） |
| **show_all_backtrace.cmm** | 线程遍历入口（同 show_thread） | 小（遍历改完其余自动） |

#### 8.4.5 验证方式

1. 创建 3-5 个不同优先级的线程，运行中触发异常
2. dump 后 Trace32 加载，点 **AllThreadBT** 按钮
3. 确认每个线程都有正确的调用栈（函数名和源文件行号）

**验收标准**：全线程回溯输出正确，能识别崩溃线程和非崩溃线程各自的调用栈。

---

### 8.5 Phase 4: 内存与 IPC 分析（按需裁剪）

**目标**：Trace32 可查看堆使用率和内存泄漏，可查看邮箱/消息队列状态。

**新增依赖**：RT-Thread 的内存分配器（memheap / slab / mempool）和 IPC 模块。

> 此阶段可按需裁剪——如果不需要详细的内存泄漏诊断，可以跳过，仅保留 Phase 3 的分析能力就已经能满足 80% 的崩溃分析需求。

#### 8.5.1 内存分配器适配

RT-Thread 使用 memheap / slab / mempool 管理堆内存，与其他 RTOS 的 dlmalloc / smallheap 设计不同。适配策略：

| 内存分配器类型 | RT-Thread 对应 | 适配方式 |
|--------|---------------|---------|
| 通用堆分配器（dlmalloc 类） | memheap (`rt_memheap`) | 重写堆分析脚本，改为解析 `rt_memheap` 内部结构 |
| 固定大小池分配器（smallheap 类） | slab / mempool | slab 无空闲链表可遍历，裁剪掉对应分析脚本 |

**简化方案**：RT-Thread 通常使用 memheap 管理大块内存，可以通过读取 `rt_memheap` 的 `total_size` / `used_size` / `max_used_size` 获得基本统计信息。如果需要详细的按文件/行号的泄漏检测，需要 RT-Thread 开启 `RT_USING_MEMTRACE` 并在 Trace32 脚本中适配对应的追踪结构体。

#### 8.5.2 IPC 分析适配

如果 RT-Thread 使用了邮箱（`struct rt_mailbox`）或消息队列（`struct rt_messagequeue`），`show_mailbox.cmm` 需要调整：

- 字段偏移量（`entry`、`in_offset`、`out_offset` 的 offset）
- 对象类型枚举值（`RT_Object_Class_MailBox` 替换 `osObject_Class_MailBox`）

如果 RT-Thread 没有使用邮箱 IPC（仅使用信号量/事件/互斥量），此脚本可以跳过。

#### 8.5.3 裁剪策略

并不是所有 Trace32 脚本都必须移植。按分析需求分三级：

| 级别 | 保留的脚本 | 适用场景 |
|------|----------|---------|
| **最小可用** | restore.cmm, frame.cmm, errinfo.cmm | Phase 2 完成即可用 — 加载镜像、定位崩溃 PC |
| **标准分析** | + backtrace.cmm, show_thread.cmm | Phase 3 完成 — 回溯调用栈、查看线程状态 |
| **完整诊断** | + 内存堆分析 + IPC 分析 | Phase 4 完成 — 内存泄漏、IPC 死锁 |

**建议**：新平台移植时先做到"标准分析"级别（Phase 3），验证整个端到端链路正确后，再根据实际需要决定是否投入 Phase 4。

#### 8.5.4 基础 OS 接口映射

以下工具函数在 RT-Thread 中有直接等价，实现时直接使用 RT-Thread API：

| 通用 RTOS 风格接口 | RT-Thread 等价 | 用途 |
|-----------|---------------|------|
| `osMemcpy()` | `rt_memcpy()` | 内存拷贝 |
| `osMemset()` | `rt_memset()` | 内存清零 |
| `osPrintf()` | `rt_kprintf()` | 调试输出 |
| `osInterruptDisable()` | `rt_hw_interrupt_disable()` | 关中断 |
| `osStrncpy/osSnprintf` | RT-Thread 或标准 C 库 | 字符串操作 |
| `osThreadSleep()` | `rt_thread_mdelay()` | 延时 |

---

### 8.6 实现模块清单

移植时所有代码从零实现。以下清单列出需要实现的全部模块（★ 标记为平台相关）：

```
板侧 C 代码:
├── ymodem.c / ymodem.h         # YMODEM 协议栈（标准协议，CRC16 校验）
├── console.c / console.h       # 控制台格式化输出
├── cli.c / clitype.h           # 命令行解析循环
├── command.c / command.h       # 命令表（按 STM32 内存布局定义转储区域）
├── mux.c / mux.h               # MUX 代理（单核 STM32 可裁掉）
├── dtools_dump.c / dtools_dump.h # DIAG 协议处理循环（UART 路径）
├── ★ uart.c / uart.h           # UART 驱动（HAL 实现）
├── ★ chip_reg_base.h           # 内存区域基地址宏
└── ★ HardFault_Handler         # ARM Cortex-M 异常入口

PC 侧 Trace32 脚本（全部重写）:
├── restore.cmm                  # 加载 dump 镜像
├── frame.cmm                    # 解析 ARM 硬件压栈帧
├── errinfo.cmm                  # 解码 SCB 异常寄存器
├── backtrace.cmm                # ARM Thumb-2 调用栈回溯
├── show_thread.cmm              # RT-Thread 线程信息展示
├── show_all_backtrace.cmm       # 全线程回溯调度
├── show_mailbox.cmm             # IPC 邮箱分析（可选）
├── print_dlmalloc_heap.cmm      # 堆分析（可选，适配 rt_memheap）
└── offsets.cmm                  # 结构体偏移量集中管理

Python 辅助工具（需适配 DWARF 格式差异）:
├── dwarf_enum_to_cmm.py
└── dwarf_trace_to_cmm.py
```

### 8.7 开关和配置

#### 8.7.1 编译时开关

**功能总开关**：通过 Kconfig 或 `rtconfig.h` 中的宏控制 ramdump 是否编译进固件。关闭后 `DTools_Dump()` 实现为空函数。

```kconfig
config RAMDUMP
    bool "Enable ramdump"
    default y
```

**异常复位控制**：生产固件应在崩溃后直接复位（不进入 dump），调试固件才进入 dump：

```c
// 通过编译宏或 Kconfig 区分
#if defined(DEBUG_BUILD)
    #define RAMDUMP_ON_FAULT  1    // 调试版: 崩溃后进入 dump
#else
    #define RAMDUMP_ON_FAULT  0    // 量产版: 崩溃后直接复位
#endif
```

推荐的设计模式：通过编译宏决定上电默认值（调试版进入 dump、量产版直接复位），同时提供一个 NV 项允许运行时覆盖默认值。在 RT-Thread 上可以通过 Kconfig（编译默认值）+ FAL（Flash Abstraction Layer，运行时覆盖）实现等价效果。

#### 8.7.2 传输路径选择

通过构建系统选择 UART/其他传输方式：

```cmake
if(BUILD_TARGET STREQUAL "STM32F4")
    target_sources(ramdump PRIVATE
        uart/uart_stm32.c
        dtools_dump/dtools_dump.c        # UART 路径
    )
endif()
```

STM32 平台使用 UART 路径。DIAG 协议通过 HDLC 成帧在 UART 字节流中界定消息边界，YMODEM 协议通过自身控制字符实现帧同步。

#### 8.7.3 运行时配置

如果需要在运行时（而非编译时）控制 ramdump 的开启/关闭，可以通过 RT-Thread 的 FAL 框架或文件系统存储配置，在 `HardFault_Handler` 中读取判断。

---

### 8.8 Trace32 脚本移植适配详解

板子侧完成 YMODEM 传输后，PC 端通过 Trace32 脚本加载镜像并分析。移植到 ARM + RT-Thread 时，脚本需要三级适配：

| 层次 | 涉及脚本 | 触发条件 | 复杂度 |
|------|---------|---------|--------|
| **A. 地址适配** | restore.cmm | 换了芯片（内存布局变了） | 低（改几个 Data.LOAD 地址） |
| **B. 结构体适配** | show_thread.cmm, show_mailbox.cmm 等 | OS 换了（结构体字段布局不同） | 中（修改偏移量常量） |
| **C. 架构适配** | backtrace.cmm, errinfo.cmm, frame.cmm | 换了 CPU 架构（RISC-V → ARM） | 高（重写指令解析和异常解码） |

#### 8.8.1 层次 A：地址适配

仅修改 `restore.cmm` 中的加载地址：

```cmm
; === RISC-V 双核平台 ===
Data.LOAD.Binary &ramdumpDir\iram.bin    0xC0200000
Data.LOAD.Binary &ramdumpDir\psram.bin   0x80000000

; === STM32 平台 ===
Data.LOAD.Binary &ramdumpDir\SRAM.bin    0x20000000
Data.LOAD.Binary &ramdumpDir\CCM.bin     0x10000000
```

> 加载地址必须与板子侧 `do_ramdump()` 中 `T_YModemFile[].buf` 地址严格一致。

#### 8.8.2 层次 B：结构体适配

OS 从自定义 RTOS 换为 RT-Thread 后，`osThread_t` 变为 `rt_thread_t`，字段偏移量不同：

**适配流程**：
1. 从 RT-Thread 的 ELF 获取结构体布局：`readelf --debug-dump=info firmware.elf | grep rt_thread`
2. 提取关键字段偏移量（name、sp、stack_addr、stack_size、stat、current_priority）
3. 更新 Trace32 脚本中的偏移量常量

**推荐做法**：在脚本头部用 `Var.NEWGLOBAL` 定义偏移量常量，而非在脚本各处硬编码数字：

```cmm
; offsets.cmm — 集中管理所有偏移量
&thread_sp_offset        = 0x04    ; rt_thread_t->sp
&thread_stackAddr_offset = 0x38    ; rt_thread_t->stack_addr
&thread_stackSize_offset = 0x3C    ; rt_thread_t->stack_size
; ... 其他字段
```

换 OS 版本时只需修改这一个文件。

#### 8.8.3 层次 C：架构适配（RISC-V → ARM）

**C1. 栈帧格式适配（frame.cmm）**

RISC-V 和 ARM Cortex-M 的异常栈帧完全不同：

```
RISC-V 栈帧 (软件保存)              ARM Cortex-M 栈帧 (硬件自动压栈)
==============================     ================================
高地址  mstatus                              xPSR  (sp+0x1C)
       mepc                                  PC    (sp+0x18) ← 崩溃地址
       ra                                    LR    (sp+0x14)
       sp                                    r12   (sp+0x10)
       gp                                    r3    (sp+0x0C)
       tp                                    r2    (sp+0x08)
       a0                                    r1    (sp+0x04)
       a1                                    r0    (sp+0x00)
       ...
       t5                          低地址
       t6
低地址  SP 指向
```

ARM 版 `frame.cmm` 核心逻辑：
```cmm
; ARM Cortex-M 异常帧恢复
; 栈帧由硬件自动压栈，无需软件保存的 mcause/mepc
; 异常原因从 SCB 寄存器获取

&pc = Data.LONG(Register(SP) + 0x18)     ; 硬件压栈的 PC
&lr = Data.LONG(Register(SP) + 0x14)     ; 硬件压栈的 LR
Register(PP) = &pc                        ; 设置 Trace32 程序指针
```

**C2. 调用栈回溯适配（backtrace.cmm）**

RISC-V 回溯通过扫描栈内存 + 解析 `JAL`/`JALR` 指令编码。ARM 需要改为解析 `BL`/`BLX`/`PUSH {..., lr}` 指令：

| 步骤 | RISC-V | ARM Cortex-M |
|------|--------|-------------|
| 获取当前 PC | `Register(PP)` → `&mepc` | `Register(PP)` → 硬件压栈的 PC |
| 获取返回地址 | 扫描栈上 `ra` → 反汇编 `JAL`/`JALR` 确认 | 扫描栈上 `lr` → 检查 bit[0]（Thumb 标志）→ 反汇编 `BL` 确认 |
| 识别函数入口 | `JAL` 的目标地址 | `BL` 的目标地址 |
| 下一帧 SP | 当前 SP + 帧大小（指令分析计算） | 当前 SP + 硬件压栈帧大小（32B）+ 局部变量 |

**C3. 异常类型解码适配（errinfo.cmm）**

RISC-V 通过 `mcause` 查表。ARM 通过 SCB 寄存器组合判断：

```cmm
; ARM Cortex-M
; SCB->CFSR @ 0xE000ED28 (UFSR[31:16] + BFSR[15:8] + MMFSR[7:0])
; SCB->HFSR @ 0xE000ED2C
&cfsr = Data.LONG(0xE000ED28)
&hfsr = Data.LONG(0xE000ED2C)

if (&hfsr & 0x40000000)  ; FORCED: 硬故障由其他故障升级而来
    if (&cfsr & 0x000000FF)       ; MMFSR 非零
        &exc_type = "MemManage Fault"
    else if (&cfsr & 0x0000FF00)  ; BFSR 非零
        &exc_type = "BusFault"
    else if (&cfsr & 0xFFFF0000)  ; UFSR 非零
        &exc_type = "UsageFault (UNDEFINED/NOCP/INVPC/...)"
```

#### 8.8.4 不需要修改的脚本

以下脚本与 CPU 架构无关（只依赖内存中的数据结构，不涉及指令解码）：

- **restore.cmm**（加载部分）— 仅改地址
- **LM620_Restore.cmm** — 纯调度脚本，无架构依赖
- **dwarf_enum_to_cmm.py / dwarf_trace_to_cmm.py** — 通用 DWARF 解析工具

#### 8.8.5 适配优先级建议

```
Phase 2 期间:
  ├─ restore.cmm    — 修改加载地址（30 分钟）
  ├─ frame.cmm      — 适配 ARM 硬件压栈帧（2-4 小时）
  ├─ errinfo.cmm    — 适配 SCB->CFSR/HFSR 解码（1-2 小时）
  └─ 验证: 能定位崩溃 PC 和异常类型

Phase 3 期间:
  ├─ backtrace.cmm           — 适配 ARM Thumb-2 指令解析（4-8 小时，最复杂）
  ├─ show_thread.cmm         — 适配 RT-Thread 线程结构体偏移（1-2 小时）
  └─ 验证: 全线程回溯正确

Phase 4 期间:
  ├─ print_dlmalloc_heap.cmm — 适配或裁剪（1-2 小时）
  ├─ show_mailbox.cmm        — 适配或跳过（1 小时）
  └─ dwarf_enum_to_cmm.py    — 重新生成偏移量文件（10 分钟）
```

> **经验法则**：同架构换芯片（Phase 2 的 A 层次）≈ 半天；换 OS（Phase 3 的 B 层次）≈ 2-3 天；换 CPU 架构（Phase 2+3 的 C 层次）≈ 1-2 周。

---

### 8.9 移植检查清单

| 类别 | 检查项 | 对应阶段 |
|------|--------|:---:|
| **内存区域** | `BASE_SRAM` / `LEN_SRAM` 与 STM32 内存映射一致 | Phase 1 |
| | `do_ramdump()` 中 YMODEM 文件 `buf` 地址与 `restore.cmm` 一致 | Phase 1 |
| **IO 驱动** | `Uart_Init/Getc/Putc` 使用 STM32 HAL 实现 | Phase 1 |
| | 三个全局函数指针 `g_Getc/g_Putc/g_PutBytes` 正确注册 | Phase 1 |
| **异常入口** | `HardFault_Handler` 中保存 SCB 寄存器 + 硬件压栈帧指针 | Phase 2 |
| | 异常现场保存在不会被 dump 覆盖的区域（全局 .noinit 或 IRAM） | Phase 2 |
| | `MemManage_Handler/BusFault_Handler/UsageFault_Handler` 转发到 HardFault | Phase 2 |
| | 与 RT-Thread 的异常 handler 集成点正确（在 RT-Thread 打印信息之后、while(1) 之前） | Phase 2 |
| **OS 接口** | `osMemcpy/osMemset` 映射到 `rt_memcpy/rt_memset` | Phase 2 |
| | `osInterruptDisable` 在 `DTools_Dump()` 之前调用 | Phase 2 |
| **线程** | `rt_thread_t` 字段偏移量通过 DWARF 确认并更新到 Trace32 脚本 | Phase 3 |
| | ARM PendSV 上下文切换帧格式与 `frame.cmm` 偏移量一致 | Phase 3 |
| **构建** | CMakeLists.txt / SConscript 添加 STM32 目标 | Phase 1 |
| | 传输路径选 UART（`dtools_dump.c`） | Phase 1 |
| **Trace32 脚本** | `restore.cmm` 加载地址与板子侧 dump 地址一致 | Phase 2 |
| | `frame.cmm` 解析 ARM 硬件压栈帧（PC 在 `sp+0x18`） | Phase 2 |
| | `errinfo.cmm` 解码 SCB->CFSR/HFSR 而非 mcause | Phase 2 |
| | `backtrace.cmm` 解析 ARM Thumb-2 BL/BLX 指令而非 RISC-V JAL/JALR | Phase 3 |
| | `show_thread.cmm` 遍历 RT-Thread 线程容器（非 `g_osThreadList`） | Phase 3 |
| | 编译时开启 `-g` 确保 ELF 包含完整符号表 | Phase 2 |
| **验证** | Phase 1: `main()` 中手动调用 `ramdump()` → PC 收到 SRAM.bin | Phase 1 |
| | Phase 2: 人为触发空指针访问 → 自动进入 CLI → Trace32 定位崩溃 PC | Phase 2 |
| | Phase 3: 多线程崩溃 → 全线程回溯正确 | Phase 3 |
| | Phase 4（可选）: 堆分析脚本输出有效 | Phase 4 |

## 附录 A：核心参考代码

本附录摘取跨平台实现 ramdump 所需的最小代码片段。所有代码提取自 实际实现，已剥离业务逻辑，仅保留核心结构和模板。

### A.1 数据结构

#### A.1.1 栈帧结构（rt_hw_stack_frame）

对应 [5.2.2 节](#522-通用寄存器栈帧格式) 中的异常帧布局。移植到新架构时必须保持字段顺序和偏移量一致，因为 Trace32 脚本依赖此布局。

```c
// 来源: cpuport.c (异常入口)
// 大小: 32 × 4 = 128 字节，必须与 IRQ_SAVE_CONTEXT 汇编宏一致

struct rt_hw_stack_frame
{
    ubase_t epc;        /* [+0x00] epc - 异常 PC / 上下文切换返回地址      */
    ubase_t ra;         /* [+0x04] x1  - 返回地址                          */
    ubase_t mstatus;    /* [+0x08]      - 机器状态寄存器 (异常:完整值)      */
    ubase_t gp;         /* [+0x0C] x3  - 全局指针 (上下文切换帧无此字段)    */
    ubase_t tp;         /* [+0x10] x4  - 线程指针                          */
    ubase_t t0;         /* [+0x14] x5  - 临时寄存器 0                      */
    ubase_t t1;         /* [+0x18] x6  - 临时寄存器 1                      */
    ubase_t t2;         /* [+0x1C] x7  - 临时寄存器 2                      */
    ubase_t s0_fp;      /* [+0x20] x8  - 保存寄存器 0 / 帧指针             */
    ubase_t s1;         /* [+0x24] x9  - 保存寄存器 1                      */
    ubase_t a0;         /* [+0x28] x10 - 函数参数 0 / 返回值               */
    ubase_t a1;         /* [+0x2C] x11 - 函数参数 1                        */
    ubase_t a2;         /* [+0x30] x12 - 函数参数 2                        */
    ubase_t a3;         /* [+0x34] x13 - 函数参数 3                        */
    ubase_t a4;         /* [+0x38] x14 - 函数参数 4                        */
    ubase_t a5;         /* [+0x3C] x15 - 函数参数 5                        */
    ubase_t a6;         /* [+0x40] x16 - 函数参数 6                        */
    ubase_t a7;         /* [+0x44] x17 - 函数参数 7                        */
    ubase_t s2;         /* [+0x48] x18 - 保存寄存器 2                      */
    ubase_t s3;         /* [+0x4C] x19 - 保存寄存器 3                      */
    ubase_t s4;         /* [+0x50] x20 - 保存寄存器 4                      */
    ubase_t s5;         /* [+0x54] x21 - 保存寄存器 5                      */
    ubase_t s6;         /* [+0x58] x22 - 保存寄存器 6                      */
    ubase_t s7;         /* [+0x5C] x23 - 保存寄存器 7                      */
    ubase_t s8;         /* [+0x60] x24 - 保存寄存器 8                      */
    ubase_t s9;         /* [+0x64] x25 - 保存寄存器 9                      */
    ubase_t s10;        /* [+0x68] x26 - 保存寄存器 10                     */
    ubase_t s11;        /* [+0x6C] x27 - 保存寄存器 11                     */
    ubase_t t3;         /* [+0x70] x28 - 临时寄存器 3                      */
    ubase_t t4;         /* [+0x74] x29 - 临时寄存器 4                      */
    ubase_t t5;         /* [+0x78] x30 - 临时寄存器 5                      */
    ubase_t t6;         /* [+0x7C] x31 - 临时寄存器 6                      */
};
// 总大小: 0x80 (128 字节)
```

> **移植要点**：ARM Cortex-M 使用硬件自动压栈的帧结构（r0-r3, r12, lr, pc, xpsr），与此不同。见 [8.5.2 节](#852-需要修改的文件清单) 的 C 部分。

#### A.1.2 异常信息结构（osException_t）

```c
// 来源: cpuport.c (DTools_Dump 入口)
// 存放于 IRAM 固定地址，双核均可读取，dump 后通过 errinfo.cmm 解析

typedef struct
{
    ubase_t core;                        // 核心 ID: 1=AP, 2=CP
    struct rt_hw_stack_frame *trace;     // 指向异常栈帧
    ubase_t mcause;                      // 异常原因码 (低 5 位)
    ubase_t mdcause;                     // 详细原因码 (低 2 位)
    ubase_t mepc;                        // 异常指令地址
    ubase_t mtval;                       // 故障地址
} osException_t;

// 实例化 — 必须在链接脚本中预留 IRAM 空间
osException_t *g_osException =
    (osException_t *)IRAM_BASE_ADDR_EXCEPTION_SHARE_NC;
```

#### A.1.3 YMODEM 文件描述结构

```c
// 来源: ymodem.h (文件节点类型)

typedef struct
{
    const char *name;    // 文件名 (如 "IRAM.bin")
    uint32_t    size;    // 数据长度 (字节)
    uint8_t    *buf;     // 数据指针 (物理地址直接强转)
} T_YModemFile;
```

#### A.1.4 线程控制块（osThread_t）

Trace32 的 `show_thread.cmm`、`select_thread.cmm`、`show_all_backtrace.cmm`、`show_mailbox.cmm` 均依赖此结构体。通过 `offsetof(osThread_t, resource_node)` 将链表节点地址反推回结构体地址。

```c
// 来源: os_def.h (线程结构体)
// 注意: 仅列出 Trace32 脚本实际访问的字段（非完整结构体）

struct osThread
{
    struct osObject parent;                  // 对象基类（含 type 字段）
    const char      *name;                   // 线程名称 → Var.String()

    osList_t        resource_node;           // 链表节点 → offsetof() 反推结构体地址
                                             //   resource_node.next → 下一线程

    // ... 中间字段省略 ...

    void       *sp;                          // 栈指针 → frame.cmm / backtrace.cmm 入口
    void       *stackAddr;                  // 栈基地址 → backtrace 的 start 参数
    uint32_t    stackSize;                  // 栈大小 → backtrace 的 end 参数

    uint8_t     stat;                        // 线程状态 → & OS_THREAD_STAT_MASK(0x0F)
    uint8_t     currentPriority;             // 当前优先级 → Var.Value()
    ubase_t     initTick;                    // 初始化 tick
    ubase_t     remainingTick;              // 剩余 tick → Var.Value()

    ubase_t     userData;                   // 用户数据 → 指向 osMb_t 邮箱 / 其他对象
};
typedef struct osThread *osThread_t;
```

**线程状态常量**（`os_def.h`）：

```c
#define OS_THREAD_INIT       0x00   // 初始化
#define OS_THREAD_READY      0x01   // 就绪
#define OS_THREAD_SUSPEND    0x02   // 挂起/阻塞
#define OS_THREAD_RUNNING    0x03   // 运行中
#define OS_THREAD_CLOSE      0x04   // 关闭
#define OS_THREAD_STAT_MASK  0x0f   // show_thread.cmm 解码用掩码
```

> 非运行态线程的 `sp` 指向 `osContextSwitch` 保存的上下文切换帧，其格式与异常帧兼容（详见 [5.2.2 节](#522-通用寄存器栈帧格式) 的帧差异表）。

#### A.1.5 邮箱控制块（osMb_t）

```c
// 来源: os_def.h (线程状态常量)

struct osMailbox
{
    struct osIpcObject parent;               // IPC 对象基类
    ubase_t          *msg_pool;              // 消息缓冲区起始地址
    uint16_t          size;                  // 邮箱容量 → show_mailbox.cmm
    uint16_t          entry;                 // 当前消息数 → show_mailbox.cmm
    uint16_t          max_entry;             // 最大消息数（仅 show_thread.cmm 使用）
    uint16_t          urgent_entry;          // 紧急消息数
    uint16_t          in_offset;             // 写指针偏移 → show_mailbox.cmm
    uint16_t          out_offset;            // 读指针偏移 → show_mailbox.cmm
    osList_t          suspend_sender_thread; // 挂起的发送线程
};
typedef struct osMailbox *osMb_t;
```

**对象类型识别**（`os_def.h`）：

Trace32 脚本通过检查 `userData` 指向对象的 `type` 字段来区分线程绑定的资源类型：

```c
enum osObjectClassType {
    osObject_Class_Thread   = 0x01,
    osObject_Class_MailBox  = 0x05,   // show_mailbox.cmm 匹配此值
    // ...
    osObject_Class_Static   = 0x80,   // 静态分配标记，与类型值做 OR
};
// 类型提取: object->type & ~osObject_Class_Static
```

#### A.1.6 内存分配器结构体

Trace32 脚本通过直接读取以下结构体来离线分析堆状态。

**dlmalloc 分配器**（`os_ext.h`）：

```c
typedef struct osDlmalloc {
  uint8_t  num;              // av_ 数组索引（arena 编号）
  uint8_t  reserved[3];
  char    *base;             // 堆起始地址
  int      total;            // 堆总大小
  int      free_chunks;      // 空闲块数量
  int      used;             // 当前使用量
  int      max_used;         // 历史最大使用量
  int      user_used;        // 用户实际使用量
  int      free;             // 空闲总量
  int      top_size;         // top chunk 大小
  int      max_chunk;        // 最大空闲块
  uint64_t failed_num;       // 分配失败次数
} osDlmalloc_t;
```

**smallheap 分配器**（`os_smallheap.h`）：

```c
// 内存池
typedef struct {
    void     *start;                // 池起始地址
    void     *end;                  // 池结束地址
    uint32_t  min_shift;            // 最小分配 size 的 shift 值
    uint32_t  min_size;             // 最小分配 size
    uint32_t  min_mask;             // 最小分配 mask
    uint32_t  max_size;             // 最大分配 size (big pool 为 0)
    uint32_t  free_bitmap;          // 空闲块位图
    mem_list_t free_list[32];       // 32 级空闲链表
    uint32_t  max_used;             // 历史最大使用量
    uint32_t  used;                 // 当前使用量
    uint32_t  user_used;            // 用户实际使用量
    uint16_t  alloc_cnt[32];        // 各 size 桶当前分配数
    uint16_t  max_alloc_cnt[32];    // 各 size 桶历史最大分配数
} memPool_t;

// 双池分配器
typedef struct {
    memPool_t mem_pool[2];          // [0]=big pool, [1]=small pool
    uint32_t  max_alloc;
    uint32_t  min_alloc;
} memHeap_t;

// 分配单元 (定义在 smallheap.c，未在头文件暴露)
typedef struct {
    uint16_t   prev_size;
    uint16_t   cur_size;           // bit15=MEM_UNIT_USED_FLAG(0x8000) 标记使用中
    uint32_t   user;               // 调用者 (irq 时存 irq 号)
    const char *file;              // 分配源文件名
    uint32_t   line;               // 分配行号
    uint16_t   size;               // 用户请求大小
    uint16_t   real_size;
    uint16_t   magic;
    uint16_t   align_size;
    osList_t   node;               // 链表节点
} memUnit_t;

#define MEM_UNIT_USED_FLAG  (0x1 << 15)    // cur_size bit15 = 使用中
#define MEM_UNIT_MAX_SIZE   (0x7FFF)        // 去除 flag 后的有效 size
#define MEM_UNIT_MIN_SIZE   (clp2(sizeof(memUnit_t)))
```

#### A.1.7 内存追踪记录（osMemTrace_t）

当编译启用 `OS_USING_MEM_TRACE` 时，每次分配会在数据区末尾附加一条追踪记录。Trace32 通过 `sYmbol.EXIST(osMallocTrace)` 检测此功能是否开启。

```c
// 来源: os_ext.h (dlmalloc 结构体)

typedef struct {
    uint32_t    user;           // 调用者标识 (< 0xFF 表示 IRQ 号)
    size_t      size;           // 分配大小
    const char *file;           // 源文件名 (Var.STRing() 读取)
    uint16_t    line;           // 行号
    uint16_t    magic;          // 魔数 0x1212
} osMemTrace_t;
```

---

### A.2 汇编模板

#### A.2.1 异常入口保存上下文（RISC-V）

```asm
/* 来源: interrupt_gcc.S (异常入口汇编)
 *
 * 关键约束:
 *   - 帧大小 = 32 * REGBYTES (128 字节)
 *   - 必须与 struct rt_hw_stack_frame 字段偏移一致
 *   - 必须切换到专用异常栈 __excp_stack_end
 *   - 必须 64 字节对齐 (.align 6)
 */

#define REGBYTES  4

.macro IRQ_SAVE_CONTEXT
    addi sp, sp, -32 * REGBYTES       /* 栈上开 128 字节帧 */
    STORE x1,   1 * REGBYTES(sp)      /* ra               */
    csrr  x1, mstatus
    STORE x1,   2 * REGBYTES(sp)      /* mstatus          */
    csrr  x1, mepc
    STORE x1,   0 * REGBYTES(sp)      /* epc              */
    STORE x4,   4 * REGBYTES(sp)      /* tp               */
    STORE x5,   5 * REGBYTES(sp)      /* t0               */
    /* ... 依次保存 x6-x31，每个寄存器占一个 slot ... */
    STORE x31, 31 * REGBYTES(sp)      /* t6               */
.endm

.align 6                              /* CLIC 要求 64B 对齐 */
exc_entry:
    IRQ_SAVE_CONTEXT
    STORE x3,   3 * REGBYTES(sp)      /* gp (补存)        */

    /* 切换到异常栈 */
    la   sp, __excp_stack_end

    /* 传参给 C 处理函数 */
    mv   a0, mcause                   /* 异常原因         */
    mv   a1, sp                       /* 栈帧指针         */
    mv   a2, mdcause                  /* 详细原因         */
    mv   a3, mtval                    /* 故障地址         */
    call core_exception_handler
    /* 不应返回; 如果返回则恢复上下文 */
    j    osContextSwitch_exit
```

#### A.2.2 上下文切换保存/恢复（RISC-V）

```asm
/* 来源: context_gcc.S (上下文切换汇编)
 *
 * 与异常帧的区别:
 *   - epc 槽位存 ra (返回地址)，而非 mepc
 *   - mstatus 槽位仅存 MIE 位，非完整值
 *   - 不保存 gp (x3)
 *   - 保存 sp 到 osThread_t->sp (a0 参数)
 */

osContextSwitch:
    addi  sp,  sp, -32 * REGBYTES     /* 栈上开 128 字节帧 */
    STORE sp,  (a0)                   /* old_thread->sp = sp */

    STORE x1,   0 * REGBYTES(sp)      /* ra → epc 槽位     */
    STORE x1,   1 * REGBYTES(sp)      /* ra                 */
    /* mstatus.MIE 位 */
    csrr a0, mstatus
    andi a0, a0, 8
    beqz a0, save_mpie
    li   a0, 0x80
save_mpie:
    STORE a0,   2 * REGBYTES(sp)      /* mstatus            */
    /* 保存 x4-x31 (不保存 gp x3) */
    STORE x4,   4 * REGBYTES(sp)
    /* ... x5-x31 ... */
    STORE x31, 31 * REGBYTES(sp)

    LOAD sp,  (a1)                    /* sp = new_thread->sp */

osContextSwitch_exit:
    LOAD a0,   0 * REGBYTES(sp)       /* 恢复 epc → mepc   */
    csrw mepc, a0
    LOAD x1,   1 * REGBYTES(sp)       /* ra                 */
    LOAD x4,   4 * REGBYTES(sp)       /* tp                 */
    /* ... x5-x31 ... */
    LOAD x31, 31 * REGBYTES(sp)       /* t6                 */
    addi sp,  sp, 32 * REGBYTES       /* 释放栈帧           */
    mret
```

#### A.2.3 异常入口（ARM Cortex-M）

ARM Cortex-M 与 RISC-V 异常入口的核心区别：**硬件自动压栈**。

```
RISC-V:                           ARM Cortex-M:
  软件逐条保存 32 个 GPR             硬件自动压栈 8 个寄存器
  sw ra, 124(sp)                    {r0, r1, r2, r3, r12, lr, pc, xpsr}
  sw sp, 120(sp)                    SP 自动偏移 -32 字节
  ...                               软件只需保存剩余寄存器 (r4-r11)
  sw x1, 0(sp)                      
                                    SP →  [r0]       ← 硬件压入
  软件保存 mcause/mepc/mstatus            [r1]
  到栈帧中                                [r2]
                                          [r3]
  所有寄存器由软件控制                    [r12]
  灵活性高，但代码多                      [lr]
                                          [pc]       ← 崩溃地址
                                          [xpsr]     ← 程序状态
                                          [r4]       ← 软件压入(first)
                                          ...
                                          [r11]      ← 软件压入(last)
```

移植要点：
- **崩溃 PC**：从硬件压栈帧的 `pc` 字段读取（`*(sp + 0x18)`），无需 `mepc`
- **异常类型**：从 `SCB->CFSR` / `SCB->HFSR` 读取，无需 `mcause`
- **异常地址**：从 `SCB->MMFAR` / `SCB->BFAR` 读取，无需 `mtval`
- **栈帧结构**：改用 `arm_stack_frame_t`（见 [8.5.2-C](Ramdump方案设计文档.md#L2193)），替代 `rt_hw_stack_frame`
- **中断嵌套**：ARM 自动屏蔽同优先级中断，无需手动 `MSTATUS_MIE` 管理

```c
// ARM Cortex-M HardFault_Handler 入口伪代码（概念）
void HardFault_Handler(void) {
    // 1. 硬件已自动压栈：r0-r3, r12, lr, pc, xpsr
    arm_stack_frame_t *frame = (arm_stack_frame_t *)__get_MSP();

    // 2. 软件保存 RISC-V 的 g_osException 等价信息
    stm32_exception_t exc = {
        .frame    = frame,
        .cfsr     = SCB->CFSR,   // 替代 mcause
        .hfsr     = SCB->HFSR,   // 替代 mdcause
        .mmfar    = SCB->MMFAR,  // 替代 mtval
        .bfar     = SCB->BFAR,
        .core_id  = 0,           // 单核
    };

    // 3. 关中断 → 调用 DTools_Dump()
    __disable_irq();
    DTools_Dump();  // 与 RISC-V 版完全相同的接口
}
```

> **关键结论**：ARM 和 RISC-V 的异常入口汇编不同，但 C 层的接口（`DTools_Dump()`）完全一致。移植工作集中在 50 行左右的异常入口代码和 Trace32 脚本的指令解析部分。

#### A.2.4 上下文切换（ARM Cortex-M）

ARM 的 PendSV 上下文切换与 RISC-V 的 `osContextSwitch` 概念相同——都是保存当前线程寄存器、恢复下一个线程寄存器。

```
RISC-V (软件保存全部):              ARM (利用硬件压栈):
  sw ra, 124(sp)                     PendSV 异常触发
  sw sp, 120(sp)                     → 硬件自动压栈 r0-r3, r12, lr, pc, xpsr
  ... 32 条 store 指令 ...           → 软件压栈 r4-r11
  lw ra, 124(sp)                     → 保存 PSP 到线程栈
  ... 32 条 load 指令 ...            → 加载新线程的 PSP
  mret                              → 软件恢复 r4-r11
                                     → 硬件自动恢复 r0-r3, r12, lr, pc, xpsr
```

> 两种架构的上下文切换帧格式不同，但 Trace32 的回溯脚本通过识别帧中的返回地址（RISC-V: `ra` / ARM: `lr`）来重建调用链，原理相通。详见 [8.7.5-C2](Ramdump方案设计文档.md#L2596)。

### A.3 YMODEM 协议常量与包格式

```c
/* 来源: ymodem.h (YMODEM 协议常量) */

#define PACKET_SEQNO_INDEX         (1)
#define PACKET_SEQNO_COMP_INDEX    (2)
#define PACKET_HEADER              (3)   /* SOH/STX + block_no + ~block_no */
#define PACKET_TRAILER             (2)   /* CRC16 高字节 + 低字节 */
#define PACKET_OVERHEAD            (PACKET_HEADER + PACKET_TRAILER)
#define PACKET_SIZE                (128)
#define PACKET_1K_SIZE             (1024)
#define PACKET_TIMEOUT             (3000)

#define FILE_NAME_LENGTH           (64)
#define FILE_SIZE_LENGTH           (16)

/* 控制字符 */
#define SOH  (0x01)   /* 128 字节数据包头                 */
#define STX  (0x02)   /* 1024 字节数据包头                */
#define EOT  (0x04)   /* 传输结束                         */
#define ACK  (0x06)   /* 确认                             */
#define NAK  (0x15)   /* 接收错误，请求重传               */
#define CAN  (0x18)   /* 连续两个 CAN 中止传输            */
#define CRC  (0x43)   /* 'C' — CRC16 模式握手请求        */

/* 包格式:
 * +0:      SOH (128B) 或 STX (1024B)
 * +1:      block_no (从 0 开始，block0 为文件信息包)
 * +2:      ~block_no
 * +3..+N:  payload (128 或 1024 字节，不足补 0x00)
 * +N+1:    CRC16 高字节
 * +N+2:    CRC16 低字节
 *
 * Block0 (文件信息包):
 * +3..     "filename\0" + "filesize" + 剩余字节补 0x00
 * 例:      "IRAM.bin\0" + "524288" + [0x00 x N]
 */
```

### A.4 DIAG 协议命令码与消息头

DIAG 协议的命令 ID 枚举定义在 [slog_diag.h](slog_diag.h)，是 PC 工具与设备端交互的核心协议常量。移植到新平台时，如需兼容现有 PC 工具，这些命令码必须保持一致。

#### A.4.1 命令 ID 枚举

```c
/* 来源: slog_diag.h (DIAG 命令枚举) */

typedef enum
{
    DIAG_EMPTY_MSG = 0,            // 空消息
    DIAG_FILTER_CONFIG,            // 1  - 日志过滤配置
    DIAG_DOWNLINK_MSG,             // 2  - 下行消息
    DIAG_RAMDUMP_MSG,              // 3  - Ramdump 模式通知（终端→PC）
    DIAG_DROP_COUNT,               // 4  - 丢包计数
    DIAG_POWER_ON_MSG,             // 5  - 上电通知
    DIAG_PSM_RESUME_MSG,           // 6  - PSM 唤醒通知
    DIAG_UPLINK_MSG,               // 7  - 上行消息
    DIAG_REQ_RULE_MSG,             // 8  - 请求规则
    DIAG_REG,                      // 9  - 寄存器读写
    DIAG_DUMP,                     // 10 - 内存读写（ramdump 核心命令）
    DIAG_SHUTDOWN,                 // 11 - 关机
    DIAG_REBOOT,                   // 12 - 正常重启
    DIAG_VERSION,                  // 13 - 版本查询
    DIAG_FILE_MANAGER,             // 14 - 文件管理（VFS 操作）
    DIAG_EXTEND_POWER_ON_MSG,      // 15 - 扩展上电通知（含上电时长）
    DIAG_PANIC_MSG,                // 16 - Panic 通知（含异常日志）
    DIAG_REBOOT_TO_DOWNLOAD,       // 17 - 重启到下载模式
    DIAG_SET_DUMP_MODE,            // 18 - 设置 dump 模式（DIAG↔YMODEM 切换）
    DIAG_GET_DUMP_MODE,            // 19 - 查询当前 dump 模式
    DIAG_CONSOLE_MSG,              // 20 - 控制台消息
    DIAG_STATISTICS_MSG,           // 21 - 统计消息
    DIAG_AT_MSG,                   // 22 - AT 命令透传
    DIAG_NV_MSG,                   // 23 - NV 读写
    DIAG_SYNC_MSG,                 // 24 - 同步请求
    DIAG_SYNC_OK_MSG,              // 25 - 同步确认
    DIAG_REASON_MSG,               // 26 - 重启原因
    DIAG_LOG_MSG,                  // 27 - 残留日志获取
    DIAG_PARTITION_MSG,            // 28 - Flash 分区信息

    DIAG_DBG_MSG = 0xFF,           // 255 - 调试消息
} SLOG_DiagType;
```

#### A.4.2 消息头结构

DIAG 消息的三层封装：

```c
/* 来源: slog_diag.h (COMM_Header) */
/*       slog_def.h        */

/* === 第1层: COMM_Header — 模块路由层 (12 字节) === */
typedef struct
{
    uint8_t  msgType;       // 消息类型: 1=COMM_MSG_TYPE, 6=COMM_MSG_UE_QUERY
    uint8_t  pad;           // 固定 0xAA
    uint16_t reserved;      // 固定 0xAAAA
    uint8_t  tgtMdlNo;      // 目标模块号 (如 MDL_PHONE=0x01)
    uint8_t  tgtSubMdlNo;   // 目标子模块号 (SUBMDL_SLOG_AGENT=0x55)
    uint8_t  srcMdlNo;      // 源模块号 (MDL_SLOG=0x73)
    uint8_t  srcSubMdlNo;   // 源子模块号
    uint32_t bufLen;        // 后续载荷总长度 (SLOG_Header + Payload)
} COMM_Header;

/* === 第2层: SLOG_Header — 日志子系统层 (4 字节) === */
typedef struct
{
    uint8_t  version;       // SLOG 协议版本 (当前为 1)
    uint8_t  msgType;       // SLOG_DIAG_MSG = 8
    uint16_t length;        // 后续载荷长度 (SLOG_DiagHeader + Payload)
} SLOG_Header;

/* === 第3层: SLOG_DiagHeader — DIAG 命令层 (4 字节) === */
typedef struct
{
    uint16_t diagId;        // SLOG_DiagType 枚举值
    uint16_t len;           // payload 长度
} SLOG_DiagHeader;
```

**三层封装示例**（DIAG_DUMP 内存读取请求，PC→设备）：

```
Byte Offset  Field               Example         Layer
──────────────────────────────────────────────────────────
[0]          msgType             0x01            COMM_Header
[1]          pad                 0xAA
[2-3]        reserved            0xAAAA
[4]          tgtMdlNo            0x01            (MDL_PHONE)
[5]          tgtSubMdlNo         0x55            (SUBMDL_SLOG_AGENT)
[6]          srcMdlNo            0x73            (MDL_SLOG)
[7]          srcSubMdlNo         0x55
[8-11]       bufLen              20              (SLOG_Header 4B + SLOG_DiagHeader 4B + Payload 12B)
─────── COMM_Header 12B ──────────────────────────────────
[12]         version             0x01            SLOG_Header
[13]         msgType             0x08            (SLOG_DIAG_MSG)
[14-15]      length              16              (SLOG_DiagHeader 4B + Payload 12B)
─────── SLOG_Header 4B ───────────────────────────────────
[16-17]      diagId              0x000A          SLOG_DiagHeader  (DIAG_DUMP)
[18-19]      len                 12              (Payload 12B)
─────── SLOG_DiagHeader 4B ───────────────────────────────
[20-23]      sequence            1               SLOG_DiagDumpReq
[24]         target              0               (DIAG_TARGET_TYPE_AP)
[25]         operation           0               (DIAG_DUMP_OP_TYPE_READ)
[26-27]      crc                 0
[28-31]      address             0xC0200000      (读取地址)
[32-35]      len                 256             (读取长度)
─────── Payload 12B ─────────────────────────────────────
Total: 36 bytes (不含 HDLC 成帧)
```

#### A.4.3 HDLC 成帧常量（UART 路径）

UART 路径在 COMM_Header 之外额外增加 HDLC 成帧层，用于在字节流中界定消息边界：

```c
/* 来源: slog_hdlc.h (HDLC 常量) */

#define HDLC_FLAG       0x7E   // 帧定界符（帧头/帧尾）
#define HDLC_ESCAPE     0x7D   // 转义字符
#define HDLC_ESCAPE_MASK 0x20  // 转义异或掩码

/* 转义规则:
 *   - 数据中的 0x7E → 发送 0x7D 0x5E
 *   - 数据中的 0x7D → 发送 0x7D 0x5D
 *   - 数据中的 0x11/0x13 → 发送 0x7D 0x31/0x33 (XON/XOFF 软件流控转义，可选)
 */

/* HDLC 帧格式:
 * ┌──────┬──────────┬──────┬──────┐
 * │ 0x7E │ Payload   │ CRC16│ 0x7E │
 * │ 1B   │ N bytes   │ 2B   │ 1B   │
 * └──────┴──────────┴──────┴──────┘
 * Payload = COMM_Header + SLOG_Header + SLOG_DiagHeader + DiagPayload
 * 帧内 0x7E/0x7D 经过转义
 */
```

> HDLC 成帧用于在 UART 字节流中界定 COMM_Header 消息边界，COMM_Header 从帧起始位置解析。

#### A.4.4 关键负载结构

**DIAG_DUMP 内存读写**（ramdump 核心命令，diagId=10）：

```c
/* 来源: slog_diag.h (DIAG Dump 消息) */

#define SLOG_DIAG_DUMP_MAX_LEN  512   // 单次读取最大 512 字节

// 请求 (PC→设备)
typedef struct {
    uint32_t sequence;       // 请求序列号（响应中原样返回）
    uint8_t  target;         // DIAG_TARGET_TYPE_AP(0) / CP(1)
    uint8_t  operation;      // DIAG_DUMP_OP_TYPE_READ(0) / WRITE(1)
    uint16_t crc;            // 请求中为 0
    uint32_t address;        // 读写地址
    uint32_t len;            // 读写长度
    uint8_t  data[0];        // 写入时携带数据
} SLOG_DiagDumpReq;

// 响应 (设备→PC)
typedef struct {
    uint32_t sequence;       // 原样返回
    uint8_t  target;
    uint8_t  operation;
    int8_t   result;         // 0=成功
    uint8_t  reserved1;
    uint16_t crc;            // data[] 的 CRC16
    uint16_t reserved2;
    uint32_t address;
    uint32_t len;
    uint8_t  data[0];        // 读取时携带实际内存数据
} SLOG_DiagDumpRsp;
```

**DIAG_SET_DUMP_MODE 模式切换**（diagId=18）：

```c
/* 来源: slog_diag.h (DIAG DumpMode 消息) */

typedef enum {
    DIAG_RAMDUMP_MODE,         // 0 — 切换到 YMODEM CLI 模式
    DIAG_DTOOLS_DUMP_MODE,     // 1 — 切换到 DIAG 逐块读取模式
} SLOG_DiagDumpMode;

typedef struct {
    int32_t dumpMode;          // SLOG_DiagDumpMode
} SLOG_DiagSetDumpModeRequest;

typedef struct {
    int32_t result;            // 0=成功
} SLOG_DiagSetDumpModeResponse;
```

**DIAG_PANIC_MSG 异常通知**（diagId=16）：

```c
/* 来源: slog_diag.h (DIAG Panic 消息) */

typedef struct {
    uint64_t apDurationTimeMs; // AP 上电时长 (ms)
    uint32_t reserved;
    uint32_t length;           // data 长度（含 \0）
    uint8_t  data[0];          // 异常日志文本 (g_osErrorLog 内容)
} SLOG_DiagPanic;
```

> **PC 工具兼容性约束**：以上结构体的字段顺序、大小和枚举值定义了 DIAG 协议的二进制接口。如果移植到新平台时需要兼容现有 PC 工具（DIAG Dump 工具），这些定义必须原样保留。如果仅使用 YMODEM 模式（不需要 PC 工具交互），则 DIAG 协议可以裁剪掉。


### A.5 IO 函数指针接口

```c
/* 来源: ymodem.h (YMODEM IO 接口)
 *
 * 平台只需实现这三个函数，注册到全局指针，
 * 上层 YMODEM / DIAG 协议即可直接工作。
 */

typedef int32_t (*F_ConGetc)(uint32_t timeout);
typedef void    (*F_ConPutc)(uint8_t ch);
typedef void    (*F_ConPutBytes)(uint8_t *bytes,
                                  uint32_t bytesLen,
                                  uint32_t timeout);

/* 全局函数指针 — 在 ramdump() 入口处赋值 */
extern F_ConGetc     g_Getc;
extern F_ConPutc     g_Putc;
extern F_ConPutBytes g_PutBytes;
```

### A.6 内存区域地址定义模板
/* 来源: chip_reg_base.h (内存区域定义)
 *
 * 移植时必须同步修改的三处:
 *   1. 本文件 (芯片基地址宏)
 *   2. 链接脚本 (MEMORY 段 ORIGIN)
 *   3. do_ramdump() (T_YModemFile 数组)
 */

/* === 本地内存 (TCM) === */
#define BASE_ILM       0x00008000UL    /* 指令本地内存         */
#define BASE_DLM       0x00010000UL    /* 数据本地内存         */

/* === 共享 RAM (IRAM) — 双核可见 === */
#define BASE_SH_RAM0   0xC0200000UL    /* Cache 别名           */
#define BASE_SH_RAM0_NC 0x10200000UL   /* 非 Cache 别名        */

/* === 片外 PSRAM === */
#define BASE_PSRAM     0x80000000UL    /* Cache 别名           */
#define BASE_PSRAM_NC  0x40000000UL    /* 非 Cache 别名        */

/* === XIP Flash === */
#define BASE_XIP_FLASH 0xC8000000UL

/* === 区域长度 === */
#define LEN_ILM_AP      (16 * 1024)
#define LEN_ILM_CP      (32 * 1024)
#define LEN_DLM_AP      (16 * 1024)
#define LEN_DLM_CP      (32 * 1024)
#define LEN_SH_RAM      (512 * 1024)
```

### A.7 IRAM 内异常共享区布局

```c
/* 来源: iram_layout.h (IRAM 布局)
 *
 * IRAM 起始 0xC0200000，前若干 KB 为固定用途区域。
 * g_osException 和 g_osAssert 位于此区域的预留槽位，双核均可访问。
 * 链接脚本中对应区域不分配用户代码/数据。
 */

/* IRAM 基址 */
#define IRAM0_BASE_ADDR                     (0xC0200000UL)

/* Trace RAM 快照 (exc_entry 中拷贝) */
#define IRAM_BASE_ADDR_AP_TRACE_RAM         (... + 0x5B00)
#define IRAM_BASE_LEN_AP_TRACE_RAM          (256UL)

/* 异常信息文本区 */
#define IRAM_BASE_ADDR_EXCEPTION_INFO       (... + 0x5C00)
#define IRAM_BASE_LEN_EXCEPTION_INFO        (512UL)

/* 断言共享区 (16B) */
#define IRAM_BASE_ADDR_ASSERT_SHARE         (... + 0x6000)
#define IRAM_BASE_LEN_ASSERT_SHARE          (16UL)

/* 异常共享区 (32B) — g_osException 存放处 */
#define IRAM_BASE_ADDR_EXCEPTION_SHARE      (... + 0x6010)
#define IRAM_BASE_LEN_EXCEPTION_SHARE       (32UL)

/* g_osException 必须小于 IRAM 预留空间 */
OS_ASSERT(sizeof(osException_t) <= IRAM_BASE_LEN_EXCEPTION_SHARE);
```

### A.8 链接脚本异常栈片段

```ld
/* 来源: cpu-ap.lds (链接脚本)
 *
 * 异常栈位于 BSS 段末尾（DRAM 中），大小默认为 2KB。
 * exc_entry 汇编中 la sp, __excp_stack_end 切换到此栈。
 * 启动时 start.S 将其全部填入 0x24242424 哨兵值。
 */

__stack_size = DEFINED(__stack_size) ? __stack_size : 2K;

SECTIONS {
    .bss : {
        /* ... 所有 BSS 数据 ... */
        . = ALIGN(32);
        PROVIDE( __excp_stack_start = . );
        . = . + __stack_size;
        PROVIDE( __excp_stack_end = . );
    } >DRAM AT>DRAM
}
```

### A.9 Trace32 frame.cmm 寄存器偏移量参考

```cmm
/* 来源: frame.cmm (异常帧恢复脚本)
 *
 * 此脚本依赖 struct rt_hw_stack_frame 的字段偏移量。
 * 如果帧结构字段顺序改变，必须同步修改以下偏移。
 * 偏移计算公式: &cpu_frame + (slot_index * 4)
 *
 * slot  0: epc        → Register.Set PC
 * slot  2: mstatus    → (仅参考，不恢复)
 * slot  3: gp (x3)    → Register.Set X3
 * slot  4: tp (x4)    → Register.Set X4
 * slot  5: t0 (x5)    → Register.Set X5
 * ...
 * slot 31: t6 (x31)   → Register.Set X31
 *
 * SP 计算: &sp = &cpu_frame + sizeof(struct rt_hw_stack_frame)
 *         = &cpu_frame + 0x80
 */

ENTRY &cpu_frame

&sp = &cpu_frame + 0x80    /* SP = 帧尾，不取自帧内字段 */

Register.Set PC  Var.Value(((struct rt_hw_stack_frame*)&cpu_frame)->epc)
Register.Set X1  Var.Value(ra)          /* slot 1 */
Register.Set X2  &sp
Register.Set X3  Var.Value(gp)          /* slot 3 */
Register.Set X4  Var.Value(tp)          /* slot 4 */
Register.Set X5  Var.Value(t0)
Register.Set X6  Var.Value(t1)
Register.Set X7  Var.Value(t2)
Register.Set X8  Var.Value(s0_fp)
Register.Set X9  Var.Value(s1)
Register.Set X10 Var.Value(a0)
Register.Set X11 Var.Value(a1)
Register.Set X12 Var.Value(a2)
Register.Set X13 Var.Value(a3)
Register.Set X14 Var.Value(a4)
Register.Set X15 Var.Value(a5)
Register.Set X16 Var.Value(a6)
Register.Set X17 Var.Value(a7)
Register.Set X18 Var.Value(s2)
Register.Set X19 Var.Value(s3)
Register.Set X20 Var.Value(s4)
Register.Set X21 Var.Value(s5)
Register.Set X22 Var.Value(s6)
Register.Set X23 Var.Value(s7)
Register.Set X24 Var.Value(s8)
Register.Set X25 Var.Value(s9)
Register.Set X26 Var.Value(s10)
Register.Set X27 Var.Value(s11)
Register.Set X28 Var.Value(t3)
Register.Set X29 Var.Value(t4)
Register.Set X30 Var.Value(t5)
Register.Set X31 Var.Value(t6)
```

---

### A.10 移植检查清单

基于本文档从零实现 ramdump 时，按以下顺序逐项确认：

| 序号  | 检查项                                                               | 参考章节         |
| --- | ----------------------------------------------------------------- | ------------ |
| 1   | `struct rt_hw_stack_frame` 字段顺序与汇编 `IRQ_SAVE_CONTEXT` 一致          | A.1.1, A.2.1 |
| 2   | `osException_t` 大小 ≤ `IRAM_BASE_LEN_EXCEPTION_SHARE`              | A.1.2, A.7   |
| 3   | `BASE_ILM`/`BASE_DLM`/`BASE_SH_RAM0`/`BASE_PSRAM` 与链接脚本 ORIGIN 一致 | A.6, 5.1.6   |
| 4   | `__excp_stack_end` 在异常栈顶（高地址端）                                    | A.8          |
| 5   | `exc_entry` 中 `la sp, __excp_stack_end` 切换到异常栈                    | A.2.1        |
| 6   | `core_exception_handler` 接收 4 个参数 (mcause, sp, mdcause, mtval)    | A.2.1        |
| 7   | `g_osException->core` 防重入检查 `== 0`                                | 5.2.3        |
| 8   | `do_ramdump()` 中 `T_YModemFile[].buf` 直接指向物理地址                    | A.1.3, A.6   |
| 9   | 实现 `g_Getc` / `g_Putc` / `g_PutBytes` 三个 IO 函数                    | A.5          |
| 10  | `frame.cmm` 偏移量与 `rt_hw_stack_frame` 字段对齐                         | A.9          |
| 11  | `restore.cmm` 加载地址与 dump 地址一致                                     | 7.2.1        |
| 12  | 双别名地址（IRAM/PSRAM）两个地址都加载                                          | 7.2.1        |
