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
| [4. 守卫（可选）](#4-守卫可选) | `scripts/guard/guard.py` | `ai_services.bat` |
| [5. 串口服务](#5-串口服务) | `scripts/serial_hub/serial_hub.py`、`scripts/ramdump/test/test_serial.py` | `ai_services.bat`、`ramdump.bat` |
| [6. 采集 dump](#6-采集-dump) | `scripts/ramdump/dump/{dump,receive}.py`、`test_usb_loopback.py` | `ramdump.bat` |
| [7. 解析 dump](#7-解析-dump) | `scripts/ramdump/analyzer/ramdump_analyzer.py` | `ramdump.bat` |
| [8. 环境变量与依赖](#8-环境变量与依赖) | — | — |
| [9. 常见菜谱](#9-常见菜谱) | — | — |
| [10. 已废弃 / 兼容入口](#10-已废弃--兼容入口) | — | — |
| [11. Python 质量门](#11-python-质量门) | `tools/pyquality/install.py`、`scripts/quality.py`、`scripts/check_bat.py` | — |
| [12. 统一入口](#12-统一入口) | `scripts/cli.py` | — |

## 0. 速查

```powershell
# 编译 + 烧录（日常）
python scripts\firmware\build.py build-flash

# 人手动：双击仓根 ai_services.bat（菜单 1~9，0 退出）
ai_services.bat

# 打印服务清单（命令表，带等价完整命令）
python scripts\ai_services.py --list

# 起串口 hub（起完别的进程/脚本用 TCP 127.0.0.1:5555 连它）
python scripts\serial_hub\serial_hub.py --com COM46 --baud 115200 --ui tui
```

### 服务面板：`scripts/ai_services.py`（命令表）+ `ai_services.bat`（外壳）

**命令表只在这一个文件里**（`SERVICES` 元组），bat 只有 68 行：探解释器 + 原样转发参数。
增删服务改 Python 里的一行即可，不需要动 bat。

| 菜单 | 名字 | 实际命令 | 说明 |
|---|---|---|---|
| 1 | `build` | `build.py build` | 默认项目 `projects/base`，产物 `out/bin/base/` |
| 2 | `flash` | `build.py flash` | **直连烧录**（不再绕守卫） |
| 3 | `build-flash` | `build.py build-flash` | 编译成功才烧 |
| 4 | `board-build` | `build.py --board build` | 板级 BSP 对照编译 |
| 5 | `clean` | `build.py clean` | 清 `out/build/*`、`out/bin/*`、旧 `build/` |
| 6 | `status` | `build.py status` + `guard --status` + `serial_hub --list` | 末行附 5555/5556 端口状态 |
| 7 | `guard` | `guard.py` | 前台常驻，Ctrl+C 结束 |
| 8 | `hub` | `serial_hub.py --com COM46 --baud 115200 --ui tui` | 前台常驻；`ai_services.bat hub COM5 9600` 可覆盖 |
| 9 | `both` | 新窗口起 hub，本窗口起守卫 | — |

只给命令行用的名字：`guard-status`、`hub-list`、`help`。
`python scripts\ai_services.py --run <名字或编号>` 等价于菜单选择；AI/CI 直接调各脚本，不走 bat。

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
| 编译（默认 `projects/base`） | `python scripts\firmware\build.py build` | `ai_services.bat build`（菜单 1） |
| 编译指定项目 | `python scripts\firmware\build.py --project base build` | — |
| 直接编译板级 BSP（对照用） | `python scripts\firmware\build.py --board build` | `ai_services.bat board-build`（菜单 4） |
| 指定并行数 | `python scripts\firmware\build.py build -j8` | — |
| 清理产物 | `python scripts\firmware\build.py clean` | `ai_services.bat clean`（菜单 5）/ `ramdump.bat clean` |
| menuconfig（始终在板目录） | `python scripts\firmware\build.py menuconfig` | `ramdump.bat menuconfig` |
| 看状态 | `python scripts\firmware\build.py status` | `ai_services.bat status`（菜单 6，汇总三段） |

**构建入口**由 `PROJECT` 环境变量 / `--project` / `--board` 决定：默认 `projects/base`（项目层），
`--board` 直接编译板级 BSP。`status` 第一行会打印当前入口（`(project)` 或 `(board)`）。
`status` 打印：入口、BSP 路径、`rtthread.bin` 大小与时间、pyocd 版本、芯片 pack 是否存在、目标芯片。

### 中间文件（`.o`/`.d`）在哪

统一收在**仓库根的 `out/build/<入口目录名>/`**（已被 `/out/` 忽略），不再散落在源码树：

```
out/build/base/                      # 项目 projects/base
out/build/stm32f407-atk-explorer/    # 板级 BSP
├── kernel/        ← os/rt-thread 内核与组件
├── libraries/     ← STM32F4xx_HAL（含 startup_stm32f407xx.o）+ HAL_Drivers
├── app/           ← app/ramdump、app/usb
├── board/         ← 板级 board/、applications/（项目模式下多一层 board/）
└── applications/
```

最终产物 `rt-thread.elf` / `rt-thread.map` / `rtthread.bin` 也**不在入口目录**，统一在
`out/bin/<入口目录名>/`（项目 = `out/bin/base/`，板级 = `out/bin/stm32f407-atk-explorer/`）；
`.sconsign.dblite`（SCons 构建签名库）收在 `out/build/<入口目录名>/`。入口目录因此只剩源码与配置。

实现方式（P1 之后）：

- 各板 `SConstruct` 与 `projects/<name>/SConstruct` 都是薄壳，逻辑在 `bsp/stm32/tools/bsp_build.py`：
  默认把中间目录算成 `<PROJECT_ROOT>/out/build/<入口目录名>`，并把 `RT_BUILD_DIR` 注入给
  `os/rt-thread/tools/building.py:376`；
- `scripts/firmware/` 仍可显式传 `RT_BUILD_DIR` 覆盖（**相对入口目录**）；
- **直接敲 `scons`（在板目录或项目目录里）也落到 `out/build/<入口目录名>`**；
  但需要先备好工具链环境变量（`RTT_CC=gcc`、`RTT_EXEC_PATH=%ENV_ROOT%\tools\gnu_gcc\arm_gcc\mingw\bin`，
  否则 rtconfig.py 会报 `the toolchain path ... is not exist`）。用 `scripts/firmware/` 或 `ai_services.bat`
  时这些变量已内置，不必手工设置。

**入口位置约束**：SCons 必须在入口目录里跑（`cd <板目录/项目目录>` 或 `scons -C <...>`）。
跨目录 `scons -f .../SConstruct` 会被薄壳拒绝（退 1）——上游 `building.py` 有 6 处按 cwd
解析的路径，详见 `docs/upstream-patches.md`。

`clean` 会把 `out/build/<入口目录名>` 和遗留的 `build/` 一起删掉。

## 3. 烧录

| 目的 | Python 命令 | bat 等价 |
|---|---|---|
| 只烧现有 bin | `python scripts\firmware\build.py flash` | `ai_services.bat flash`（菜单 2） |
| 编译 + 烧录 | `python scripts\firmware\build.py build-flash` | `ai_services.bat build-flash`（菜单 3） |
| 烧指定文件 | `python scripts\firmware\build.py flash --bin out\bin\base\rtthread.bin` | — |
| 老命令（兼容） | `python scripts\ramdump\build\build.py --flash` | `ramdump.bat build --flash` / `ramdump.bat flash` |

`flash` 默认烧**当前构建入口**的 `rtthread.bin`（项目 = `out/bin/base/rtthread.bin`，
板级 = `out/bin/stm32f407-atk-explorer/rtthread.bin`），所以先 `build` 再 `flash` 不会烧错目标。

固定参数（写死在 `scripts/firmware/tools.py`）：

```
python -m pyocd flash --target STM32F407VE --erase=auto --frequency=1000000 \
    --pack tools\pyocd\packs\Keil.STM32F4xx_DFP.2.14.0-small.pack <bin>
```

pyocd 日志走 stderr，PowerShell 里看到 `NativeCommandError` 字样是正常的（不代表失败，看退出码）。

## 4. 守卫（可选）

守卫是「信箱 + 完整日志 + 改脚本自动重启 + 无人值守」的长任务执行器：AI 写请求文件，人在沙箱外开的窗口执行，结果写回 `out/guard/`。
**日常烧录不需要它**（`build.py flash` 直接就能跑）。
**能跑哪些命令不写在代码里**，全在 `scripts/guard/tasks.toml`（加任务 = 加一段 `[[tasks]]`）。

| 目的 | Python 命令 | bat 等价 |
|---|---|---|
| 起守卫（常驻） | `python scripts\guard\guard.py` | `ai_services.bat guard`（菜单 7，人手动） |
| 活没活 / 积压 | `python scripts\guard\guard.py --status` | `ai_services.bat status` |
| **列出允许的任务** | `python scripts\guard\guard.py --tasks` | `ai_services.bat guard-tasks` |
| 历史请求 | `python scripts\guard\guard.py --list` | — |
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
细节与排错：`scripts/guard/README.md`。

## 5. 串口服务

### 5.1 serial_hub（一个进程独占串口，多个客户端同时连）

| 目的 | Python 命令 | bat 等价 |
|---|---|---|
| 起中继（默认 COM 自动选、115200） | `python scripts\serial_hub\serial_hub.py` | `ai_services.bat hub`（菜单 8） |
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
| `RT_BUILD_DIR` | `../../out/build/<入口目录名>`（由脚本设） | SCons 中间文件目录，**相对入口目录**（项目目录或板目录）；不设则回到上游默认的 `build/` |
| `PROJECT` | `base`（默认） | 构建哪个项目（`projects/<名字>`）；设为空 / `none` 等价于板级编译 |
| `HUB_COM` / `HUB_BAUD` / `HUB_UI` | `COM46` / `115200` / `tui` | `scripts\ai_services.py` 的 `hub`/`both` 条目读取（可覆盖默认值） |
| `AI_SERVICES_NOPAUSE` | 未设 | 设了则 bat 结尾不 `pause`（自动化用） |
| `PYTHONPYCACHEPREFIX` | `out\pycache`（bat 内设） | 别把 `__pycache__` 撒进源码树 |
| `PRE_COMMIT_HOME` | `out\precommit`（`quality.py` 自动设） | pre-commit 的缓存目录，避免写用户目录 |

依赖一览：Python 3.13（PATH 上的 `python`）、pyserial（hub/采集）、pyocd 0.45.1 + 18 个依赖（`tools/pyocd/install.py` 装）、
analyzer 额外要 pyelftools + numpy、编译要 `rt-thread-env` 里的 arm-none-eabi-gcc 与 SCons（4.8.x）。

## 9. 常见菜谱

```powershell
# 日常：改完代码编译 + 烧录
python scripts\firmware\build.py build-flash

# 换机器重建环境
python tools\pyocd\install.py
python scripts\firmware\build.py status

# 人手动：双击 ai_services.bat（菜单 1 编译 / 2 烧录 / 3 编译+烧录 / 4 板级 / 5 清理 / 6 状态 / 7 守卫 / 8 hub / 9 两个都起）

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
python scripts\guard\guard.py --request build_flash --wait --wait-timeout 900
```

## 10. 已废弃 / 兼容入口

| 入口 | 状态 | 替代 |
|---|---|---|
| `bsp/stm32/stm32f407-atk-explorer/build_and_flash.bat` | **已删除**（305 行 cmd） | `python scripts\firmware\build.py ...` + `ai_services.bat` |
| `python scripts\ramdump\build\build.py` | 兼容壳（转发到 `scripts/firmware/`） | `python scripts\firmware\build.py` |
| `--new-console` | 失效（无独立窗口逻辑） | 直接看当前终端输出 |
| `tools/pyocd/0.1.3/pyocd.exe`（0.27） | **已删除** | `tools/pyocd/pkg` 里的 0.45.1 |
| `tools/pyocd/0.1.3/pyocd.yaml` | 已删除 | 命令行显式 `--pack`（脚本里已内置） |

## 11. Python 质量门

工具链**不在 site-packages 里**，而是按仓内约定装到 `tools/pyquality/pkg/`（已 gitignore），版本固定在 `tools/pyquality/install.py`：
换机器只需一条命令重建，不会因为 `pip install` 到全局而出现"我这能过、你那不能过"。

### 11.1 安装（每台机器一次）

```powershell
python tools\pyquality\install.py           # ruff 0.14.3 / mypy 1.18.2 / pytest 8.4.2 / pre-commit 4.3.0
python tools\pyquality\install.py --check   # 只检查版本，不动文件
python scripts\quality.py doctor            # 打印解释器 + 工具目录 + 三个工具版本
python scripts\quality.py hooks-install     # 装 git 提交钩子（并把缓存钉到 out\precommit）
```

| 步骤 | 为什么这样 |
|---|---|
| 装进 `tools/pyquality/pkg` | 版本唯一来源、可随时整体删除重建、CI 与本地同版本；`pip install` 到全局会与别的项目抢版本 |
| `install.py` 内部替换 `tempfile.mkdtemp` | 受限环境里 `mkdtemp` 建出的目录不可写，pip 必失败（详见 `tools/pyocd/install.py` 同样手法） |
| `hooks-install` 把 `PRE_COMMIT_HOME` 写进钩子 | 生成的钩子由 git 直接调用，拿不到当前进程环境变量；否则缓存会写 `~/.cache/pre-commit` |

### 11.2 命令（`scripts/quality.py`）

| 命令 | 作用 | 改文件？ |
|---|---|---|
| `python scripts\quality.py check` | `ruff check .` | 否 |
| `python scripts\quality.py check --fix` | 自动修可修的（**只用这一种粒度**，不要跑全量 `--unsafe-fixes`） | 是 |
| `python scripts\quality.py format` | `ruff format .` | 是 |
| `python scripts\quality.py format-check` | 只检查排版 | 否 |
| `python scripts\quality.py types` | `mypy`（配置在 `scripts/pyproject.toml`） | 否 |
| `python scripts\quality.py tests` | `pytest`（透传参数：`tests -k ymodem -x`） | 否 |
| `python scripts\quality.py all` | 全套并打汇总表（**提交前/CI 用这条**） | 否 |
| `python scripts\quality.py hooks` | 跑 `pre-commit run --all-files` | 可能（钩子里带 `--fix`） |
| `python scripts\quality.py hooks --staged` | 只跑暂存文件（= 提交时自动跑的那次） | 可能 |
| `python scripts\quality.py hooks-install` | 安装 git 提交钩子 | 否 |
| `python -X utf8 scripts\check_bat.py` | `.bat/.cmd` 必须纯 ASCII + CRLF | 否 |

### 11.3 配置在哪（改规则只改一处）

| 文件 | 管什么 |
|---|---|
| `scripts/pyproject.toml` | ruff 规则集/行长 110/LF/双引号；mypy 覆盖范围；pytest 测试目录与 marker |
| `.pre-commit-config.yaml` | 4 个钩子：`ruff check --fix`、`ruff format`、TOML 可解析、`.bat` ASCII+CRLF |
| `.github/workflows/ci.yml` | CI：质量门 + 固件编译 |
| `.editorconfig` | 编辑器层面：Python LF/4 空格；`.bat` CRLF |

### 11.4 CI（`.github/workflows/ci.yml`）

| job | 内容 | 阻塞？ |
|---|---|---|
| `python-quality` | 装同版本工具 → `quality.py doctor` → `quality.py all` → `check_bat.py` | 是 |
| `firmware-build` | `apt install gcc-arm-none-eabi` + `scons==4.8.1` → `python scripts/firmware/build.py build`（`RTT_EXEC_PATH=/usr/bin`、`VENV=$pythonLocation`） | **否**（软失败：本机是 Windows 工具链，Linux 构建尚未本地验证） |

### 11.5 排错

| 症状 | 原因 / 处理 |
|---|---|
| `PermissionError: C:\Users\<你>\.cache\pre-commit` | 钩子没被 `hooks-install` 改写 → 重跑 `python scripts\quality.py hooks-install` |
| `ruff` 报一堆中文标点 "歧义 Unicode" | `RUF001-003` 已在 `ignore` 里；若手工跑请确认 cwd 是 `scripts/`（配置在那里） |
| `pytest` 收集到 `tools/pyocd/pkg/**/tests` | 在仓根跑 pytest 了；必须在 `scripts/` 下（`quality.py` 会自动 `cwd=scripts`） |
| 自动修复后行为变了 | **禁用全量 `--unsafe-fixes`**：它曾把 `print(...)` 整条删掉。删代码类修复必须人工过 diff |
| 提交时报 `fatal error - NtCreateDirectoryObject(...msys-2.0S5-...): 0xC0000022` | Git 用 msys `sh` 跑钩子，受限环境里它建不了共享内存对象。此时**先 `python scripts\quality.py hooks` 手动跑一遍**（等价检查），再用 `git commit --no-verify` 提交；普通终端里不受影响 |

## 12. 统一入口

`python scripts/cli.py <命令> [参数...]` 是**路由**，不是新实现：它把命令名映射到既有脚本的 `main()`，行为与直接调老入口完全一致。

```powershell
python scripts\cli.py list                  # 有哪些命令（加 --json 输出机器可读清单）
python scripts\cli.py doctor                # 环境自检：解释器/四个工具/pyocd/串口
python scripts\cli.py status --json         # 构建状态（入口/中间目录/产物/大小/pyocd）
python scripts\cli.py build-flash -j 8      # = python scripts\firmware\build.py build-flash -j 8
python scripts\cli.py hub --com COM46       # = python scripts\serial_hub\serial_hub.py --com COM46
```

| 命令 | 分组 | 等价于 |
|---|---|---|
| `list` | 基础 | 本表 |
| `doctor` | 基础 | 解释器 + `ruff/mypy/pytest/pre-commit` 版本 + `pyocd.check()` + 串口列表 |
| `status` | 构建 | `scripts/firmware/build.py status`，另给 `--json` |
| `build` / `build-flash` / `flash` / `clean` / `menuconfig` | 构建 | `scripts/firmware/build.py <同名命令>` |
| `quality` | 质量 | `scripts/quality.py`（参数透传，如 `quality check --fix`） |
| `guard` | 服务 | `scripts/guard/guard.py`（`--status`/`--request`/`--tasks` 透传） |
| `hub` | 服务 | `scripts/serial_hub/serial_hub.py` |
| `dump` / `recv` | 采集 | `scripts/ramdump/dump/{dump,receive}.py` |
| `analyze` | 采集 | `scripts/ramdump/analyzer/ramdump_analyzer.py`（含 `--sram/--ccm/--exception/--elf` 等） |

公共开关：`-v/--verbose`（叠加，诊断走 stderr）、`-q/--quiet`（只出结果/错误）、`--json`（**只对 `list`/`doctor`/`status` 生效**，其它命令原样透传）。
退出码：`0` 成功、`1` 运行时失败、`2` 用法错误（未知命令、参数不对）。

三条边界（避免误解）：
1. **不复制业务**：子命令逻辑仍在原脚本里；`cli.py` 只做 import + 参数转发。
2. **老入口继续可用**：本文档其余章节、`ai_services.py` 命令表都仍指向原脚本路径。
3. **`--json` 不猜格式**：只有本文件自己产出的三个命令支持；要别的命令机器可读，由那个脚本自己加。

### 12.1 `__pycache__` 落在 `out/pycache`

入口脚本第一段都有一份**内联**的 4 行引导：

```python
_sys.pycache_prefix = str(
    next(p for p in Path(__file__).resolve().parents if any((p / m).exists() for m in (".git", "AGENTS.md")))
    / "out" / "pycache"
)
```

为什么内联、不抽成 `runtime/pycache.py`：**import 本身就会先在源码旁生成 `.pyc`**，等模块被导入时已经晚了。
所以每个入口在 import 任何本地模块之前都要自己算一次；写法统一成上面这 4 行，靠「向上找 `.git`/`AGENTS.md`」避免写死父级层数（过去正是层数写错导致 `__pycache__` 漏进源码树）。


## 附：两个 bat 的定位

| bat | 定位 | 约束 |
|---|---|---|
| `ai_services.bat` | **薄外壳**（68 行）：探 `python` → 转发所有参数给 `scripts\ai_services.py`；菜单/命令表全在那个 Python 文件里 | **纯 ASCII + CRLF**（cmd 逐字节解析，中文/纯 LF 会炸）；不含业务逻辑 |
| `scripts/ramdump/ramdump.bat` | 采集流程的薄包装：`build`/`flash`/`clean`/`menuconfig`/`dump`/`recv`/`list`/`probe`/`loopback`/`analyzer`/`hub` | 同上 |
