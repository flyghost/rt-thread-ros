# scripts/ramdump —— 采集与分析

从设备取回 ramdump，并离线解析它。**四个桶各管一件事**，依赖只朝 `lib/` 单向流动：

| 目录 | 角色 | 入口 |
|---|---|---|
| `lib/` | 库：串口 / 控制台 / YMODEM / 编译下载 / 工程配置 | 不直接跑，被下面几个桶 import |
| `build/` | 编译 · 下载 · 清理 · menuconfig | `python scripts/ramdump/build/build.py [--flash]` |
| `dump/` | 采集：触发 → YMODEM → 落盘 | `dump/dump.py`（全流程）、`dump/receive.py`（只收） |
| `test/` | 探针：列口 / 探控制台 / USB 回环 | `test/test_serial.py`、`test/test_usb_loopback.py` |
| `analyzer/` | 离线解析 dump（backtrace / 异常解码 / 符号表） | `python scripts/ramdump/analyzer/ramdump_analyzer.py` |

规则：**桶 → `lib/` 单向依赖**，桶之间不互相 import（`test/` 不 import `dump/`）。
想加"下载"这类动作就加进 `build/build.py` 的子命令，不要另开一个桶。

## 常用命令

```bash
# 编译 / 下载
python scripts/ramdump/build/build.py                 # 只编译
python scripts/ramdump/build/build.py --flash         # 编译 + 下载
python scripts/ramdump/build/build.py --flash-only    # 只下载现有的 rtthread.bin
python scripts/ramdump/build/build.py --clean         # 清理 build/ 与 rt-thread.elf/rtthread.bin/rt-thread.map

# 采集（全流程：编译 → 下载 → 等 MSH → 触发 → YMODEM 收 → out/dump/<时间戳>/）
python scripts/ramdump/dump/dump.py                          # 自动找口
python scripts/ramdump/dump/dump.py --com COM46 --skip-build
python scripts/ramdump/dump/dump.py --com COM46 --region sram
python scripts/ramdump/dump/dump.py --com COM46 --transport usb   # UART 触发 + USB CDC 收
python scripts/ramdump/dump/receive.py --com COM46                # 只收（设备已在跑）
python scripts/ramdump/dump/receive.py --com COM8 --no-trigger    # 设备已经在发 YMODEM

# 探针
python scripts/ramdump/test/test_serial.py --list                 # 列口 + 标出自动选哪个
python scripts/ramdump/test/test_serial.py --probe --com COM46    # 在 MSH 还是 @ramdump>
python scripts/ramdump/test/test_usb_loopback.py --com COM8       # USB CDC 回环（设备在 vcom 模式）

# 分析
python scripts/ramdump/analyzer/ramdump_analyzer.py out/dump/20260722_015005
```

`ramdump.bat` 只是薄包装，省得敲路径：`ramdump.bat dump --com COM46`、`ramdump.bat build --flash`、`ramdump.bat recv --com COM46`。

## 依赖与环境

- **Python + pyserial**：本机 `E:\software\InstallerEdition\DevTools\Python\Python313\python.exe`（3.13.2 + pyserial 3.5）有；rt-thread-env 里的 3.11.9/venv **没有** pyserial。
- **编译/下载**：编译下载已统一到 `scripts/firmware/`（`build.py` CLI + `config.py` 常量 + `tools.py` 实现），
  本目录的 `lib/config.py` 只是转发常量；pyocd 只有一份，装在 `tools/pyocd/pkg`（见 `tools/pyocd/README.md`），
  芯片定义用仓内 `tools/pyocd/packs/Keil.STM32F4xx_DFP.2.14.0-small.pack`（target `STM32F407VE`，
  `--erase=auto --frequency=1000000`）。烧录在会话里可直接跑；`scripts/guard/` 的守卫是可选的
  长任务执行器（信箱 + 日志 + 自动重启）。
- **analyzer** 额外依赖见 `analyzer/requirements.txt`。
- 产物：固件落 `out/bin/`，dump 落 `out/dump/<YYYYmmdd_HHMMSS>/`；两者都在 `.gitignore` 里。

## 走 USB 收 dump 时要注意

- 设备侧 `RT_USING_RAMDUMP_USB` 打开时，进异常后会把 dump 通道切到 USB CDC（OTG FS，板子上是 MicroUSB 口那个），**UART 上不会再出 dump 数据**。
- 进 dump 后才做 USB 枚举 → **线要先插好**；PC 侧会多出一个串口，VID:PID 是占位的 `FFFF:FFFF`，所以自动找口找不到它，用 `test/test_serial.py --list` 看一眼再 `--com COM8`。
- `dump/dump.py --transport usb` 会：串口发触发 → 在 UART 上等到 `@ramdump>` → 切到 USB CDC 口 → 下发 `ramdump*` → YMODEM 收。

## 端口被占用怎么办

**不要**用 `taskkill /F /IM python.exe`（会把别的脚本一起杀掉）——这也是原 `kill_com.bat` / `test_com3.py` 被去掉的原因。正确做法：

1. `python scripts/serial_hub/serial_hub.py --list` 看这个口是谁；
2. 或者让 `scripts/serial_hub/serial_hub.py` 独占该口，人用终端软件连它的 TCP 端口，脚本连它的数据口。

> 现状：`dump/` 与 `test/` 里的脚本目前是**直接打开 COM 口**的。让它们改连串口中枢的 TCP 口（`--host/--port`）是一步可选的增量改动，还没做。

## 与 Trace32 的关系

`tools/trace32/` 是本目录 `analyzer/` 之外的另一套离线分析手段，两者并列
（样本数据放 `out/trace32/`，已在 `.gitignore` 内）。
