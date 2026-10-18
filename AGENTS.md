# rt-thread-ros — 工程基线

> 给 AI 的会话基线：只放**稳定事实**（分层 / 构建前提 / 关键路径）。
> 命令与用法在各归属文件，见文末索引——此处不重述，避免出现第二份会过期的副本。

## 目录分层（2026-10 重排后）
```
os/rt-thread/            # 上游 RT-Thread（自有改动应尽量收敛，便于整树替换 / 升级）
  ├── src/ include/ libcpu/ tools/ Kconfig
  └── components/{dfs,drivers,fal,finsh,libc,utilities}
bsp/stm32/<board>/       # 板级：SConstruct / board/ / applications/ / Keil/iar 工程
app/                     # 自有代码（与上游物理分离）
  ├── ramdump/           # 崩溃诊断：UART轮询+YMODEM+CLI+断言（port/ 层隔离 OS）
  └── ros/               # ANO_DT 等业务
scripts/                 # 自有 Python 脚本（firmware/ 编译烧录；flash_guard/ 沙箱外守卫；
                         #   ramdump/ 采集与解析；serial_hub/ 串口服务器）
out/                     # 中间文件 out/build/<board>/、最终 bin、dump、trace32 样本（全部 gitignore）
docs/                    # 设计文档：reference/ 外来原始方案；archive/ 已落地设计稿；根下为实现方案（历史稿）
```
构建接入：`bsp/stm32/<board>/SConstruct:8` 默认 `RTT_ROOT = <bsp>/../../../os/rt-thread`（可用 `RTT_ROOT` 环境变量覆盖）；
`SConstruct:59-63` 额外加载 `app/`。中间文件目录由环境变量 `RT_BUILD_DIR` 控制（相对 BSP 目录，
`scripts/firmware/` 设成 `../../../out/build/<board>`；不设则退回上游默认的 `build/`），
认这个变量的是 `os/rt-thread/tools/building.py` 与各 BSP 的 `SConstruct`。BSP 的 `Kconfig` 里 `RTT_DIR := ../../../os/rt-thread`。

## Build & Flash
```bash
python scripts/firmware/build.py build-flash   # 编译 + 烧录
ai_services.bat                                # 人手动用：菜单（编译/烧录/守卫/串口 hub/状态）
```
**所有脚本命令（环境搭建 / 编译 / 烧录 / 守卫 / 串口 / 采集 / 解析，Python 与 bat 对照）见 `scripts/README.md`。**
三条稳定事实（细节见 `tools/pyocd/README.md` 与 `scripts/firmware/`）：
- 工具链环境变量由脚本内置（`RTT_CC=gcc`、`RTT_EXEC_PATH=%ENV_ROOT%\tools\gnu_gcc\arm_gcc\mingw\bin`、
  `ENV_ROOT=E:\software\EnvEdition\rt-thread-env\env-windows`），SCons 跑在 `ENV_ROOT\.venv` 的解释器里；
- **pyocd 全仓只有一份**：pip 装进 `tools/pyocd/pkg`（已 gitignore，`python tools/pyocd/install.py` 复现），
  芯片定义用仓内 `tools/pyocd/packs/Keil.STM32F4xx_DFP.2.14.0-small.pack`，不写用户目录缓存；
- **烧录两条路都通**：`python scripts/firmware/build.py flash` 会话里直接跑即可（现代 pyocd 用 `python -m pyocd`，
  不再有 PyInstaller 解包那堵墙，沙箱内实测可烧）；`scripts/flash_guard/` 的守卫是**可选**的长任务执行器
  （信箱 + 完整日志 + 改脚本自动重启 + 无人值守），由人双击 `ai_services.bat` 启动。

## 关键路径
| 用途 | 路径 |
|------|------|
| 板子 | `bsp/stm32/stm32f407-atk-explorer/`、`stm32f103c8t6-remoter`、`stm32f103-100ask-mini` |
| 内核配置 | `bsp/stm32/stm32f407-atk-explorer/rtconfig.h` |
| 链接脚本 | `bsp/stm32/stm32f407-atk-explorer/board/linker_scripts/link.lds` |
| 异常入口 | `os/rt-thread/libcpu/arm/cortex-m4/context_gcc.S`, `cpuport.c` |
| 异常钩子 API | `os/rt-thread/include/rthw.h`（`rt_hw_exception_install`） |
| 启动文件 | `bsp/stm32/stm32f407-atk-explorer/board/CubeMX_Config/Src/stm32f4xx_it.c` |
| Ramdump 组件 | `app/ramdump/` |
| Ramdump OS 适配层 | `app/ramdump/port/rtthread/` |
| Ramdump 异常转发 | `bsp/stm32/stm32f407-atk-explorer/board/ramdump_handlers.c` |
| Trace32 脚本 | `tools/trace32/`（样本数据在 `out/trace32/`，gitignore） |
| 采集/解析工具 | `scripts/ramdump/`（`lib/` + `build/` `dump/` `test/` + `analyzer/`） |
| 串口服务器 | `scripts/serial_hub/`（一个进程独占串口，人 + 脚本同时连） |

## Ramdump 采集 / 解析（`scripts/ramdump/`）
分层：`lib/`（配置、串口、控制台、YMODEM、编译下载的实现）、`build/` `dump/` `test/` 三个动作桶
（**只依赖 lib，桶之间不互相 import**）、`analyzer/`（离线解析 dump）。
命令、端口号、依赖环境、USB 收包注意事项、串口被占用怎么办——全在 `scripts/ramdump/README.md`。

## Trace32
```bash
cd tools/trace32
do STM32F407_Restore.cmm                                    # GUI界面
```
需要 `t32marm.exe`（ARM版），不能用 `t32mriscv.exe`（RISC-V版）。
样本数据（`SRAM.bin` / `CCM.bin` / `exception_record.bin` / `rt-thread.elf`）放 `out/trace32/`；
`.cmm` 里用变量 `&ramdump_path` 指向它，换目录后运行时重新指定即可。

## 详细文档
| 范围 | 文档 |
|------|------|
| **所有脚本命令（环境/编译/烧录/串口/采集/解析，Python 与 bat 对照）** | `scripts/README.md` |
| 组件级：异常链路 / 传输层 / 协议 / 脚本 | `app/ramdump/AGENTS.md` |
| 采集与解析用法 | `scripts/ramdump/README.md` |
| 串口服务器 | `scripts/serial_hub/README.md` |
| 烧录守卫（信箱协议 / 白名单 / 排错） | `scripts/flash_guard/README.md` |
| pyocd 安装与版本（唯一实现） | `tools/pyocd/README.md` |
| USB 双栈（CherryUSB / ST） | `app/usb/README.md` |
| 设计文档 | `docs/`：`reference/Ramdump方案设计文档.md`（外来原始方案，RISC-V 双核）、`archive/ramdump-decouple-plan.md`（已落地）、`Ramdump实现设计方案.md`（历史计划稿，路径与协议已过时） |
