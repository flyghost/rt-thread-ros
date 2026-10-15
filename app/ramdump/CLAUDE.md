# Ramdump 组件 — Claude 行为规范

## 架构概述

Ramdump 是运行在 HardFault 异常上下文中的裸机崩溃诊断系统，支持 UART 和
USB CDC ACM 双 I/O 通道、YMODEM 文件传输、交互式 CLI。

**核心约束**：dump 运行期间全局中断已由系统关闭。dump 框架本身不做任何
开关中断操作，所有代码以轮询方式运行——无中断依赖、无 RT-Thread 调度器。

**入口约束**：所有进入 dump 的路径（真异常、手动命令）都必须走系统断言
`RAMDUMP_ASSERT → UDF 指令 → HardFault`，不存在直接函数调用入口。

## 层级框架

```
应用层     CLI 命令解析、YMODEM dump 引擎、异常记录
          ↓
I/O 抽象   统一收发接口（put/get），编译期宏选择 UART 或 USB，二选一不镜像
          ↓
transport/  UART 轮询驱动（寄存器级）   │   USB CDC ACM 设备（轮询模式）
           uart/                        │   usb/
                                        │   ├─ core/   CherryUSB 设备核心
                                        │   ├─ class/  CDC ACM 类驱动
                                        │   └─ port/   DWC2 端口驱动（非 DMA）
          ↓
OSAL      裸机原语：DWT 忙等延时，零 RT-Thread 依赖
```

## 核心设计原则

1. **dump 框架不碰中断**——全局中断的关闭由系统保证（Cortex-M4 异常入口
   硬件自动设置 PRIMASK），dump 框架内不出现 `__disable_irq`、
   `NVIC_DisableIRQ`、`NVIC_EnableIRQ` 等操作。所有 I/O 代码以纯轮询
   方式编写，不假设中断可用。

2. **唯一入口是 HardFault**——无论真异常还是手动触发，都必须经过
   `RAMDUMP_ASSERT → UDF 指令 → UsageFault → HardFault_Handler →
   ramdump_enter()` 这条路径，不允许绕过异常系统直接调用 dump 函数。

3. **同步发送**——USB 发送接口启动传输后内部轮询等待完成（主机 ACK 或超时
   恢复），返回即表示数据已发出。调用者不需要自己 poll。

4. **非阻塞接收**——USB 接收接口只读环形缓冲区，无数据立即返回 -1。RX 数据
   的填充由 poll 路径统一处理，与收发逻辑解耦。

5. **超时自愈**——发送等待超时时（主机断线、挂起），硬件 abort 流程自动恢复
   IN 端点，下次发送无需额外处理。

6. **策略与机制分离**——端口层只做纯硬件初始化（GPIO、时钟），中断策略、
   初始化顺序等决策放在应用层。

## 入口路径

```
真异常：  CPU 异常 → HardFault_Handler → ramdump_enter()
手动命令：MSH 命令 → RAMDUMP_ASSERT(0) → UDF → UsageFault → HardFault → ramdump_enter()
```

两条路径最终汇入同一个 HardFault 入口，dump 框架本身不区分触发来源。

## DWC2 传输模型（非 DMA 从机）

每包 IN 传输分两个阶段，都由 poll 驱动：

- **TXFE（FIFO 空）**：软件把数据从内存搬进 DWC2 TxFIFO
- **XFRC（传输完成）**：主机发送 IN token → 取走数据 → 回 ACK → 硬件置位

USB 是主机驱动的总线，设备不能主动发送。软件只负责在 TXFE 时填 FIFO、
在 XFRC 时确认完成，IN token 的到达时机由主机决定，软件不感知。

## 移植要点

- USB 协议栈是 cherryusb 的独立分支，与主项目 `components/drivers/usb/cherryusb/` 无关
- DWC2 基址 `0x50000000`（STM32F407 OTG FS），非 DMA 从机模式
- 移植到其他 MCU：替换 `usb_dc_low_level_init()` 中的 GPIO/时钟配置

## 测试

### 编译烧录（必须用脚本）

```bash
cd tools/ramdump_auto
python ramdump_auto.py --build-only
```

### USB 回环测试（在 dump CLI 内）

USB 回环不再是独立线程，而是 `@ramdump>` 下的 `vcom` 命令，与真实 crash dump
运行在完全相同的 HardFault 轮询上下文中：

1. COM3（UART MSH）输入 `cmd_ramdump` → 触发断言进入 HardFault
2. 等待 ~3 秒让 USB 枚举完成
3. 切换到 COM8（USB CDC ACM 虚拟串口）
4. 输入 `vcom` → 进入 echo 回环，Ctrl+C 退出

```python
import serial, time
# 触发 dump
u = serial.Serial('COM3', 115200, timeout=1, write_timeout=1)
u.write(b'cmd_ramdump\r\n'); u.flush(); u.close()
time.sleep(4)

# 在 COM8 上测试 vcom
ser = serial.Serial('COM8', 115200, timeout=2, write_timeout=2)
ser.dtr = True; time.sleep(0.5)
ser.write(b'vcom\r\n'); time.sleep(0.3)
ser.read(1024)  # 消费提示
ser.write(b'Hello!\r\n'); time.sleep(0.5)
print(ser.read(256))  # 应回显
ser.write(b'\x03')    # Ctrl+C 退出
ser.close()
```

**COM8 是 USB CDC ACM，COM3 是 CH340 UART。**

### 完整 dump

```bash
cd tools/ramdump_auto
python ramdump_auto.py --com COM3 --crash
```

## 常见错误

1. **不要开 OTG_FS 的 NVIC 中断**——会导致 `USBD_IRQHandler` 重入
2. **crash 上下文不要用 `rt_thread_mdelay`**——调度器已停，用 DWT 忙等
3. **NVIC 控制不要放在 port 层**——`usb_dc_low_level_init` 只做硬件初始化
4. **COM3 是 UART，COM8 是 USB**——不要搞混
5. **`ramdump_usb_send` 现在是同步的**——返回 0 表示主机已 ACK
