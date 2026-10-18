# 脚本命令手册（`scripts/` + `tools/` + 仓根 bat）

> 所有入口都是 **Python**；bat 只是**给人手动用的薄壳**，里面没有业务逻辑，每一行都转调下面某条 Python 命令。
> 板端 msh 命令（`usb_st` / `usb_reinit` / `reboot` 等）不在此文，见 `app/usb/README.md`。

## 目录

| 分类 | Python 入口 | bat 壳 |
|---|---|---|
| [0. 速查](#0-速查) | — | — |
| [1. 环境搭建](#1-环境搭建) | `tools/pyocd/install.py`、`pip` | — |
| [2. 编译 / 配置 / 状态](#2-编译--配置--状态) | `scripts/firmware/build.py` | `ai_services.bat`、`ramdump.bat` |
| [3. 烧录](#3-烧录) | `scripts/firmware/build.py` | `ai_services.bat`、`ramdump.bat` |
| [4. 烧录守卫（可选）](#4-烧录守卫可选) | `scripts/flash_guard/flash_guard.py` | `ai_services.bat` |
| [5. 串口服务](#5-串口服务) | `scripts/serial_hub/serial_hub.py`、`scripts/ramdump/test/test_serial.py` | `ai_services.bat`、`ramdump.bat` |
| [6. 采集 dump](#6-采集-dump) | `scripts/ramdump/dump/{dump,receive}.py`、`test_usb_loopback.py` | `ramdump.bat` |
| [7. 解析 dump](#7-解析-dump) | `scripts/ramdump/analyzer/ramdump_analyzer.py` | `ramdump.bat` |
| [8. 环境变量与依赖](#8-环境变量与依赖) | — | — |
| [9. 常见菜谱](#9-常见菜谱) | — | — |
| [10. 已废弃 / 兼容入口](#10-已废弃--兼容入口) | — | — |

## 0. 速查

```powershell
# 编译 + 烧录（日常）
python scripts\firmware\build.py build-flash

# 人手动：双击仓根 ai_services.bat（菜单 1~7）
ai_services.bat

# 起串口 hub（起完别的进程/脚本用 TCP 127.0.0.1:5555 连它）
python scripts\serial_hub\serial_hub.py --com COM46 --baud 115200 --ui tui
```

## 1. 环境搭建

| 目的 | Python 命令 | 备注 |
|---|---|---|
| 装/复现 pyocd（全仓唯一来源） | `python tools\pyocd\install.py` | pip 装 0.45.1 到 `tools/pyocd/pkg`（已 gitignore） |
| 只检查是否装好 | `python tools\pyocd\install.py --check` | 打印版本 + pack 是否存在，exit 0/1 |
| 重装 | `python tools\pyocd\install.py --force` | 先删 `pkg/` 再装 |
| 指定版本 | `python tools\pyocd\install.py --version 0.45.1` | — |
| 静默 | `python tools\pyocd\install.py --quiet` | — |
| 串口依赖（hub / 采集要） | `python -m pip install pyserial` | 本机 Python313 已有 3.5；`rt-thread-env` 的 venv **没有** |
| 解析依赖（analyzer 要） | `python -m pip install -r scripts\ramdump\analyzer\requirements.txt` | `pyelftools>=0.30`、`numpy>=1.24.0` |
| 维护 pack 清单 | `python tools\pyocd\packs\update_yaml.py` | 扫 `packs/` 重生成清单，非日常 |

工具链（arm-none-eabi-gcc、SCons）**不用手工配**：`scripts/firmware/tools.py` 会内置
`ENV_ROOT`、`RTT_CC=gcc`、`RTT_EXEC_PATH`，并直接用 `ENV_ROOT\.venv` 里的解释器跑 SCons。

## 2. 编译 / 配置 / 状态

| 目的 | Python 命令 | bat 等价 |
|---|---|---|
| 编译 | `python scripts\firmware\build.py build` | `ai_services.bat build`（菜单 1） |
| 指定并行数 | `python scripts\firmware\build.py build -j8` | — |
| 清理产物 | `python scripts\firmware\build.py clean` | `ramdump.bat clean` |
| menuconfig | `python scripts\firmware\build.py menuconfig` | `ramdump.bat menuconfig` |
| 看状态 | `python scripts\firmware\build.py status` | `ai_services.bat status`（菜单 7） |

`status` 打印：BSP 路径、`rtthread.bin` 大小与时间、pyocd 版本、芯片 pack 是否存在、目标芯片。

## 3. 烧录

| 目的 | Python 命令 | bat 等价 |
|---|---|---|
| 只烧现有 bin | `python scripts\firmware\build.py flash` | `ai_services.bat flash`（菜单 2） |
| 编译 + 烧录 | `python scripts\firmware\build.py build-flash` | `ai_services.bat build-flash`（菜单 3） |
| 烧指定文件 | `python scripts\firmware\build.py flash --bin out\bin\rtthread.bin` | — |
| 老命令（兼容） | `python scripts\ramdump\build\build.py --flash` | `ramdump.bat build --flash` / `ramdump.bat flash` |

固定参数（写死在 `scripts/firmware/tools.py`）：

```
python -m pyocd flash --target STM32F407VE --erase=auto --frequency=1000000 \
    --pack tools\pyocd\packs\Keil.STM32F4xx_DFP.2.14.0-small.pack <bin>
```

pyocd 日志走 stderr，PowerShell 里看到 `NativeCommandError` 字样是正常的（不代表失败，看退出码）。

## 4. 烧录守卫（可选）

守卫是「信箱 + 完整日志 + 改脚本自动重启 + 无人值守」的长任务执行器：AI 写请求文件，人在沙箱外开的窗口执行，结果写回 `out/guard/`。
**日常烧录不需要它**（`build.py flash` 直接就能跑）。

| 目的 | Python 命令 | bat 等价 |
|---|---|---|
| 起守卫（常驻） | `python scripts\flash_guard\flash_guard.py` | `ai_services.bat guard`（菜单 4，人手动） |
| 活没活 / 积压 | `python scripts\flash_guard\flash_guard.py --status` | `ai_services.bat status` |
| 历史请求 | `python scripts\flash_guard\flash_guard.py --list` | — |
| 烧录 | `--request flash --wait` | `ai_services.bat flash` |
| 编译 + 烧录 | `--request build_flash --wait --wait-timeout 900` | `ai_services.bat build-flash` |
| 只编译 | `--request build --wait` | `ai_services.bat build` |
| 看探针 | `--request list --wait` | — |
| 环境自检（TEMP / pyocd） | `--request probe --wait` | — |
| libusb 视角枚举 | `--request usb --wait` | — |
| 擦片 / 复位 | `--request erase` / `--request reset`（加 `--wait`） | — |
| 协议自检 | `--request selftest --wait` | — |
| 指定固件 / 目标 | `--bin <仓内相对路径>`、`--target STM32F407VE` | — |
| 备注 / 有效期 | `--note "..."`、`--expires 900` | — |
| 换信箱（并行测试） | `--mailbox out\guard_test` | — |

退出码：`0` 成功 / `1` 跑了但失败 / `2` 用法错、被拒或等待超时 / `3` 守卫不在跑。
细节与排错：`scripts/flash_guard/README.md`。

## 5. 串口服务

### 5.1 serial_hub（一个进程独占串口，多个客户端同时连）

| 目的 | Python 命令 | bat 等价 |
|---|---|---|
| 起中继（默认 COM 自动选、115200） | `python scripts\serial_hub\serial_hub.py` | `ai_services.bat hub`（菜单 5） |
| 指定串口 / 波特率 | `... --com COM46 --baud 115200` | `ai_services.bat hub COM46 115200` |
| 列出候选并标出自动选哪个 | `... --list` | `ramdump.bat list` |
| 无界面（只落日志） | `... --ui none` | `set HUB_UI=none` 后 `ai_services.bat hub` |
| 全屏面板 / 逐行打印 | `--ui tui` / `--ui stream` | 默认 `tui` |
| 换监听端口 | `--port 5555`（数据，raw/telnet 嗅探）、`--control-port 5556`（0=关） | — |
| telnet 接入口 | `--telnet-port 5557`（0=关） | — |
| 本窗口打印什么 | `--stdout {rx,rxtx,hex,none}` | — |
| 日志目录 | `--log-dir out\log`（默认开） | — |
| 允许局域网连 | `--allow-lan`（默认只听 127.0.0.1） | — |
| 临时探测规则 | `--prefer 1A86:7523` / `--prefer name:COM7` / `--prefer desc:ch340` | — |
| DTR/RTS 复位控制 | `--reset-mode {dtr,rts,both}`、`--reset-active {low,high}`、`--reset-pulse 0.1`、`--dtr-open {keep,high,low}` | — |
| 热拔插自动重开 | `--reopen` / `--no-reopen`、`--reopen-delay 2.0` | — |
| 写锁 | `--lock-writes` / `--no-lock-writes`（默认开） | — |
| 控制口前缀 | `--control-prefix @@` | — |

### 5.2 不开 hub 时的串口自检

| 目的 | Python 命令 | bat 等价 |
|---|---|---|
| 列出串口（标出自动选择） | `python scripts\ramdump\test\test_serial.py --list` | `ramdump.bat list` |
| 探控制台（MSH 还是 `@ramdump>`） | `python scripts\ramdump\test\test_serial.py --probe --com COM46` | `ramdump.bat probe --com COM46` |
| 发一行看回显 | `... test_serial.py --echo --com COM46` | — |
| 探测时长 | `--seconds 3.0` | — |

## 6. 采集 dump

| 目的 | Python 命令 | bat 等价 |
|---|---|---|
| 全流程（编译→下载→触发→YMODEM 收） | `python scripts\ramdump\dump\dump.py --com COM46` | `ramdump.bat dump --com COM46` |
| 只收（设备已在跑） | `python scripts\ramdump\dump\receive.py --com COM46` | `ramdump.bat recv --com COM46` |
| 跳过编译下载 | `... dump.py --skip-build` | `ramdump.bat dump --skip-build` |
| 只编译下载不采集 | `... dump.py --build-only` | — |
| 选区域 | `--region {all,flash,sram,ccm}`，或 `--sram-only` / `--ccm-only` / `--flash-only` | 参数原样透传 |
| 走 USB 通道 | `... dump.py --transport usb --com COM21` | 参数原样透传 |
| 真异常路径 | `--crash --crash-cmd RAMDUMP_ASSERT` | — |
| 跳过 MSH 探测 | `--no-check` / `receive.py --no-trigger` | — |
| 落盘目录 | `--out-dir out\dump\mycase`（默认 `out/dump/<时间戳>`） | — |
| 弹独立窗口跑编译下载 | `--new-console`（**已失效，保留参数名**） | — |
| USB 回环测试 | `python scripts\ramdump\test\test_usb_loopback.py --com COM21 --sizes 1024,4096,8192` | `ramdump.bat loopback --com COM21` |

公共参数：`--com`（省略则按 VID:PID 自动找 CH340）、`--baud`（默认 115200）。

## 7. 解析 dump

| 目的 | Python 命令 | bat 等价 |
|---|---|---|
| 出 HTML 报告 | `python scripts\ramdump\analyzer\ramdump_analyzer.py --sram SRAM.bin --ccm CCM.bin --exception exception_record.bin --elf rt-thread.elf -o report.html` | `ramdump.bat analyzer --sram ...` |
| 出文本报告 | 同上加 `--text` / `-t` | 参数原样透传 |
| 带 flash dump | 加 `--flash Flash.bin` / `-f` | — |
| 只看某对象范围 | `--object-start 0x20000000 --object-end 0x20001000` | — |

短选项：`-s` sram、`-c` ccm、`-f` flash、`-e` exception、`-l` elf、`-o` output。
`exception_decoder.py`、`arm_backtrace.py`、`rtthread_parser.py` 是 analyzer 的被 import 模块，平时不直接敲。

## 8. 环境变量与依赖

| 变量 | 默认值 | 作用 |
|---|---|---|
| `ENV_ROOT` | `E:\software\EnvEdition\rt-thread-env\env-windows` | 工具链根（arm-gcc、SCons venv） |
| `RTT_CC` / `RTT_EXEC_PATH` | `gcc` / `%ENV_ROOT%\tools\gnu_gcc\arm_gcc\mingw\bin` | SCons 用的编译器 |
| `VENV` | `%ENV_ROOT%\.venv` | 跑 SCons 的解释器目录 |
| `PYOCD_PY` | 当前解释器 | 跑 `-m pyocd` 的解释器（要与 `pkg/` 里二进制 wheel 的 ABI 一致，即 CPython 3.13） |
| `PYOCD_TARGET` | `STM32F407VE` | pyocd 目标名 |
| `SCONS_JOBS` | `20` | 并行编译数 |
| `HUB_COM` / `HUB_BAUD` / `HUB_UI` | `COM46` / `115200` / `tui` | 仅 `ai_services.bat` 用 |
| `FLASH_GUARD_NOPAUSE` | 未设 | 设了则 bat 结尾不 `pause`（自动化用） |
| `PYTHONPYCACHEPREFIX` | `out\pycache`（bat 内设） | 别把 `__pycache__` 撒进源码树 |

依赖一览：Python 3.13（PATH 上的 `python`）、pyserial（hub/采集）、pyocd 0.45.1 + 18 个依赖（`tools/pyocd/install.py` 装）、
analyzer 额外要 pyelftools + numpy、编译要 `rt-thread-env` 里的 arm-none-eabi-gcc 与 SCons（4.8.x）。

## 9. 常见菜谱

```powershell
# 日常：改完代码编译 + 烧录
python scripts\firmware\build.py build-flash

# 换机器重建环境
python tools\pyocd\install.py
python scripts\firmware\build.py status

# 人手动：双击 ai_services.bat（菜单 1 编译 / 2 烧录 / 3 编译+烧录 / 4 守卫 / 5 hub / 6 两个都起 / 7 状态）

# 起串口 hub（起完别的进程用 TCP 127.0.0.1:5555 连它，控制口 5556，telnet 5557）
python scripts\serial_hub\serial_hub.py --com COM46 --baud 115200 --ui tui

# 看板子控制台是 MSH 还是 @ramdump>
python scripts\ramdump\test\test_serial.py --probe --com COM46

# 采一次 dump
python scripts\ramdump\dump\dump.py --com COM46

# 解析刚采到的 dump（出文本报告）
python scripts\ramdump\analyzer\ramdump_analyzer.py --sram out\dump\<时间>\SRAM.bin `
    --exception out\dump\<时间>\exception_record.bin `
    --elf bsp\stm32\stm32f407-atk-explorer\rt-thread.elf --text

# 无人值守长任务（先让守卫窗口开着）
python scripts\flash_guard\flash_guard.py --request build_flash --wait --wait-timeout 900
```

## 10. 已废弃 / 兼容入口

| 入口 | 状态 | 替代 |
|---|---|---|
| `bsp/stm32/stm32f407-atk-explorer/build_and_flash.bat` | **已删除**（305 行 cmd） | `python scripts\firmware\build.py ...` + `ai_services.bat` |
| `python scripts\ramdump\build\build.py` | 兼容壳（转发到 `scripts/firmware/`） | `python scripts\firmware\build.py` |
| `--new-console` | 失效（无独立窗口逻辑） | 直接看当前终端输出 |
| `tools/pyocd/0.1.3/pyocd.exe`（0.27） | **已删除** | `tools/pyocd/pkg` 里的 0.45.1 |
| `tools/pyocd/0.1.3/pyocd.yaml` | 已删除 | 命令行显式 `--pack`（脚本里已内置） |

## 附：两个 bat 的定位

| bat | 定位 | 约束 |
|---|---|---|
| `ai_services.bat` | 人的服务面板：菜单 1~7 + `guard`/`hub`/`both`/`status`/`build`/`flash`/`build-flash`/`help` | **纯 ASCII + CRLF**（cmd 逐字节解析，中文/纯 LF 会炸）；不含业务逻辑 |
| `scripts/ramdump/ramdump.bat` | 采集流程的薄包装：`build`/`flash`/`clean`/`menuconfig`/`dump`/`recv`/`list`/`probe`/`loopback`/`analyzer`/`hub` | 同上 |
