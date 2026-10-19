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
projects/<name>/         # 项目层：一块板 + 一套配置 + 一套自有源（SConstruct/rtconfig.py/project.toml）
                         #   当前只有 base（出厂基线）；板级硬件仍只有 bsp/stm32/<board>/ 一份
scripts/                 # 自有 Python 脚本（firmware/ 编译烧录；guard/ 沙箱外守卫；
                         #   ramdump/ 采集与解析；serial_hub/ 串口服务器）
out/                     # out/build/<入口名>/（.o/.d/.sconsign）、out/bin/<入口名>/（elf/map/bin）、
                         #   out/pycache/（所有入口的 __pycache__ 都引到这里）、dump、trace32 样本（全部 gitignore）
docs/                    # 设计文档：reference/ 外来原始方案；archive/ 已落地设计稿；根下为实现方案（历史稿）
```
**`scripts/` 是独立工具仓 `toolbelt` 的子模块**（`https://github.com/flyghost/toolbelt.git`）：
改工具要在 `scripts/` 里提交并 push，再回本仓提交一次子模块指针；`git clone` 本仓需 `--recurse-submodules`。

**本仓事实（板子 / 工具链 / 芯片 / 串口）在工程根的 `toolbelt.toml`**，Python 工具侧由
`scripts/src/toolbelt/manifest.py` 读取校验；换板或换机器只改它，`scripts/` 不动。

构建接入：路径契约在 `bsp/stm32/tools/bsp_paths.py`，构建逻辑在 `bsp/stm32/tools/bsp_build.py`；各板 `SConstruct`
只是**薄壳**（三份字节一致）。`PROJECT_ROOT` = 环境变量覆盖 → 向上找 `.git`/`AGENTS.md` → 报错退出；
`RTT_ROOT = <PROJECT_ROOT>/os/rt-thread`，自有代码在 `<PROJECT_ROOT>/app`，HAL 库在板目录上一级 `libraries/`；
中间文件目录由 `RT_BUILD_DIR` 注入（默认 `out/build/<入口目录名>`，由 `os/rt-thread/tools/building.py:376` 读取）。
上游 6 处 cwd 约定、本仓对上游的偏离清单、升级与新增板/项目的检查清单，全在 `docs/upstream-patches.md`。
BSP 的 `Kconfig` 里 `RTT_DIR := ../../../os/rt-thread`（仅 menuconfig 使用）。

## Build & Flash
```bash
python scripts/tools/run.py build build-flash   # 编译 + 烧录（默认项目 projects/base）
python scripts/tools/run.py build --board build # 直接编译板级 BSP（对照用）
out\venv\Scripts\tb.cmd build status      # 装过仓内 venv 后的正式入口（见 scripts/README.md 第 2 节）
ai_services.bat                                # 人手动用：菜单（编译/烧录/守卫/串口 hub/状态）
```
**所有脚本命令（环境搭建 / 编译 / 烧录 / 守卫 / 串口 / 采集 / 解析，Python 与 bat 对照）见 `scripts/README.md`。**
**改 `scripts/` 下的 Python：`python scripts/tools/run.py quality all` 必须全绿（ruff + format + mypy + pytest）；提交钩子与 CI 跑的是同一套命令（见 `scripts/README.md` 第 4 节）。**
四条稳定事实（细节见 `scripts/tools/pyocd/README.md`、`scripts/src/toolbelt/firmware/` 与 `docs/upstream-patches.md`）：
- 工具链环境变量由脚本内置（`RTT_CC=gcc`、`RTT_EXEC_PATH=%ENV_ROOT%\tools\gnu_gcc\arm_gcc\mingw\bin`、
  `ENV_ROOT=E:\software\EnvEdition\rt-thread-env\env-windows`），SCons 跑在 `ENV_ROOT\.venv` 的解释器里；
- **构建入口必须站在入口目录里运行**（`cd projects/<name>` 或 `cd bsp/stm32/<board>`，或 `scons -C <...>`）：
  上游 `building.py` 有 6 处按 cwd 解析的路径，跨目录 `scons -f` 会在薄壳里被明确拒绝（退 1）；
  中间文件统一在 `out/build/<入口目录名>`（`RT_BUILD_DIR`），产物统一在 `out/bin/<入口目录名>`
  （elf/map/bin，由 `RT_ARTIFACT_DIR` + 显式 `Default(TARGET)` 实现）；两者都在 `out/` 下，入口目录只留源码；
- **pyocd 全仓只有一份**：pip 装进 `scripts/tools/pyocd/pkg`（已 gitignore，`python scripts/tools/pyocd/install.py` 复现），
  芯片定义用仓内 `scripts/tools/pyocd/packs/Keil.STM32F4xx_DFP.2.14.0-small.pack`，不写用户目录缓存；
- **烧录两条路都通**：`python scripts/tools/run.py build flash` 会话里直接跑即可（现代 pyocd 用 `python -m pyocd`，
  不再有 PyInstaller 解包那堵墙，沙箱内实测可烧）；`scripts/src/toolbelt/guard/` 的守卫是**可选**的长任务执行器
  （信箱 + 完整日志 + 改脚本自动重启 + 无人值守），由人双击 `ai_services.bat` 启动。

## 关键路径
| 用途 | 路径 |
|------|------|
| 板子 | `bsp/stm32/stm32f407-atk-explorer/`、`stm32f103c8t6-remoter`、`stm32f103-100ask-mini` |
| 项目层 | `projects/base/`（`project.toml` + `SConstruct` + `rtconfig.py` + `SConscript`） |
| 内核配置 | `bsp/stm32/stm32f407-atk-explorer/rtconfig.h` |
| 链接脚本 | `bsp/stm32/stm32f407-atk-explorer/board/linker_scripts/link.lds` |
| 异常入口 | `os/rt-thread/libcpu/arm/cortex-m4/context_gcc.S`, `cpuport.c` |
| 异常钩子 API | `os/rt-thread/include/rthw.h`（`rt_hw_exception_install`） |
| 启动文件 | `bsp/stm32/stm32f407-atk-explorer/board/CubeMX_Config/Src/stm32f4xx_it.c` |
| Ramdump 组件 | `app/ramdump/` |
| Ramdump OS 适配层 | `app/ramdump/port/rtthread/` |
| Ramdump 异常转发 | `bsp/stm32/stm32f407-atk-explorer/board/ramdump_handlers.c` |
| Trace32 脚本 | `tools/trace32/`（样本数据在 `out/trace32/`，gitignore） |
| 采集/解析工具 | `scripts/src/toolbelt/ramdump/`（`lib/` + `build/` `dump/` `test/` + `analyzer/`） |
| 串口服务器 | `scripts/src/toolbelt/serial_hub/`（一个进程独占串口，人 + 脚本同时连） |

## Ramdump 采集 / 解析（`scripts/src/toolbelt/ramdump/`）
分层：`lib/`（配置、串口、控制台、YMODEM、编译下载的实现）、`build/` `dump/` `test/` 三个动作桶
（**只依赖 lib，桶之间不互相 import**）、`analyzer/`（离线解析 dump）。
命令、端口号、依赖环境、USB 收包注意事项、串口被占用怎么办——全在 `scripts/src/toolbelt/ramdump/README.md`。

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
| 采集与解析用法 | `scripts/src/toolbelt/ramdump/README.md` |
| 串口服务器 | `scripts/src/toolbelt/serial_hub/README.md` |
| 守卫（信箱协议 / 白名单 / 排错） | `scripts/src/toolbelt/guard/README.md` |
| pyocd 安装与版本（唯一实现） | `scripts/tools/pyocd/README.md` |
| USB 双栈（CherryUSB / ST） | `app/usb/README.md` |
| **上游偏离与构建约束（6 处 cwd 约定 / 升级清单 / 新增板与项目清单）** | `docs/upstream-patches.md` |
| 项目层（一块板多个项目 / 目录结构 / 已知限制） | `projects/README.md` |
| 设计文档 | `docs/`：`reference/Ramdump方案设计文档.md`（外来原始方案，RISC-V 双核）、`archive/ramdump-decouple-plan.md`（已落地）、`Ramdump实现设计方案.md`（历史计划稿，路径与协议已过时） |
