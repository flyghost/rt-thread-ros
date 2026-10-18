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
scripts/                   # 自有脚本（ramdump/ 采集与解析；serial_hub/ 串口服务器）
out/                     # 编译产物 + dump 输出
docs/                    # 设计文档：reference/ 外来原始方案；archive/ 已落地设计稿；根下为实现方案（历史稿）
```
构建接入：`bsp/stm32/<board>/SConstruct:8` 默认 `RTT_ROOT = <bsp>/../../../os/rt-thread`（可用 `RTT_ROOT` 环境变量覆盖）；
`SConstruct:59-61` 额外加载 `app/`（`variant_dir=build/app`）。BSP 的 `Kconfig` 里 `RTT_DIR := ../../../os/rt-thread`。

## Build & Flash
```bash
cd bsp/stm32/stm32f407-atk-explorer
scons -j20                                              # 编译
pyocd flash --target=STM32F407VE rtthread.bin           # 下载
# 或一键: build_and_flash.bat   （build / flash / clean / menuconfig / verbose）
```
构建需先备好工具链环境变量：`RTT_CC=gcc`、`RTT_EXEC_PATH=%ENV_ROOT%\tools\gnu_gcc\arm_gcc\mingw\bin`
（`ENV_ROOT=E:\software\EnvEdition\rt-thread-env\env-windows`），`build_and_flash.bat` 已内置这套默认值。

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
| Trace32 脚本 | `bsp/stm32/tools/trace32/` |
| 采集/解析工具 | `scripts/ramdump/`（`lib/` + `build/` `dump/` `test/` + `analyzer/`） |
| 串口服务器 | `scripts/serial_hub/`（一个进程独占串口，人 + 脚本同时连） |

## Ramdump 采集 / 解析（`scripts/ramdump/`）
分层：`lib/`（配置、串口、控制台、YMODEM、编译下载的实现）、`build/` `dump/` `test/` 三个动作桶
（**只依赖 lib，桶之间不互相 import**）、`analyzer/`（离线解析 dump）。
命令、端口号、依赖环境、USB 收包注意事项、串口被占用怎么办——全在 `scripts/ramdump/README.md`。

## Trace32
```bash
cd bsp/stm32/tools/trace32
do STM32F407_Restore.cmm                                    # GUI界面
```
需要 `t32marm.exe`（ARM版），不能用 `t32mriscv.exe`（RISC-V版）。

## 详细文档
| 范围 | 文档 |
|------|------|
| 组件级：异常链路 / 传输层 / 协议 / 脚本 | `app/ramdump/AGENTS.md` |
| 采集与解析用法 | `scripts/ramdump/README.md` |
| 串口服务器 | `scripts/serial_hub/README.md` |
| 设计文档 | `docs/`：`reference/Ramdump方案设计文档.md`（外来原始方案，RISC-V 双核）、`archive/ramdump-decouple-plan.md`（已落地）、`Ramdump实现设计方案.md`（历史计划稿，路径与协议已过时） |
