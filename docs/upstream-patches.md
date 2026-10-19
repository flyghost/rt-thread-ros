# 本仓对 RT-Thread 上游的偏离与构建约束

> 目的：把"我们改过上游什么"和"上游有哪些限制我们必须绕开"写成一份可执行的清单。
> 升级 `os/rt-thread`、新增一块板、新增一个项目之前，先看这里。
> 相关：`AGENTS.md`（分层与关键路径）、`scripts/README.md`（脚本命令）、`bsp/stm32/tools/bsp_paths.py`（路径契约实现）。

## 0. 一句话

`os/rt-thread` 与 `bsp/stm32/libraries` 视为**冻结的上游**；本仓只在下述少数位置有偏离，其余"现代化"全部加在薄入口（`SConstruct`）、共享模块（`bsp/stm32/tools/`）与脚本层（`scripts/`）。

## 1. 偏离清单（改过上游的地方）

| # | 文件 | 位置 | 内容 | 为什么 | 升级上游后怎么办 |
|---|---|---|---|---|---|
| 1 | `os/rt-thread/tools/building.py` | `:373` 注释 + `:376` | `bsp_vdir = os.environ.get('RT_BUILD_DIR') or 'build'`（上游写死 `'build'`） | 让中间文件统一出树到 `out/build/<board>`，不在 BSP 目录留 `build/` | 重新贴这 2 行（对比 `:376` 是否是 `bsp_vdir = 'build'`） |
| 2 | `bsp/stm32/libraries/STM32F4xx_HAL/SConscript` | `:137-142` | 平台三分支追加 `CMSIS/Device/ST/STM32F4xx/Source/Templates/{gcc,arm,iar}/startup_stm32f407xx.s` | 上游把 startup 放 `board/SConscript` 并用 `SDK_LIB` 绝对路径引用；**绝对路径会绕过 `variant_dir`**，把 `startup_*.o` 直接生成到 `libraries/.../Templates/gcc/`（源码树里混 `.o`） | 保留；若上游库 `SConscript` 被整份替换，重新追加这 6 行 |
| 3 | `bsp/stm32/libraries/STM32F1xx_HAL/SConscript` | `:89-94` | 同上，`startup_stm32f103xb.s` | 同上 | 同上 |
| 4 | `os/rt-thread/libcpu/arm/cortex-m3/` | 整目录（5 文件） | `SConscript`、`cpuport.c`、`context_{gcc,rvds,iar}.S` | 本仓历史从未入库，两块 F103 链接报 `undefined reference to rt_hw_stack_init`；从本机 RT-Thread Studio 的 v5.1.0 树补齐 | 升级上游时用上游版本覆盖（注意 v5.1/v5.2 的 `cpuport.c` 差异） |
| 5 | `bsp/stm32/libraries/STM32F1xx_HAL/` | 整目录（236 文件 / 15.9 MB） | 完整 F1 HAL 库 | 曾在 `32a96c7 瘦身` 中被删除，两块 F103 无法编译；从 `32a96c7^` 恢复 | 跟随上游/ST 版本更新 |

本仓新增（**不属于**上游偏离，随仓更新）：`bsp/stm32/tools/bsp_paths.py`、`bsp/stm32/tools/bsp_build.py`、`bsp/stm32/tools/sdk_dist.py`（上游也有）、三块板的 `SConstruct` 薄壳。

## 2. 上游的 cwd 约定（6 处）——这是"必须从板目录构建"的根因

`os/rt-thread/tools/building.py` 与板级 `rtconfig.py` 里有多处**按当前工作目录**解析的路径：

| # | 位置 | 内容 | 影响 |
|---|---|---|---|
| 1 | `os/rt-thread/tools/building.py:280` | `f = open('rtconfig.h', 'r')` | 组件依赖解析读 cwd 的 `rtconfig.h` |
| 2 | `os/rt-thread/tools/building.py:376-379` | `bsp_vdir = ... or 'build'`；`objs = SConscript('SConscript', variant_dir=bsp_vdir, duplicate=0)` | 顶层 `SConscript` 按 cwd 解析；变体目录相对顶层目录 |
| 3 | `os/rt-thread/tools/building.py:417` | `f = open(bsp_directory + '/rtconfig.h', 'r')` | 板目录推导依赖同一套假设 |
| 4 | `os/rt-thread/tools/building.py:862` | `if os.path.isfile('template.uvprojx')` | `scons --target=mdk5` 在 cwd 找 IDE 模板 |
| 5 | `bsp/stm32/<board>/rtconfig.py:49` | `-Map=rt-thread.map`、`-T board/linker_scripts/link.lds` | 链接脚本与 map 文件都按 cwd 解析 |
| 6 | `bsp/stm32/<board>/rtconfig.py:62` | `POST_ACTION = ... -O binary $TARGET rtthread.bin` | 产物 `rtthread.bin` 生成在 cwd |

**因此**：

```bash
cd bsp/stm32/stm32f407-atk-explorer && scons -j20        # 正确
scons -j20 -C bsp/stm32/stm32f407-atk-explorer           # 正确（等价）
python scripts/firmware/build.py build                   # 正确（内部 cd 到板目录）
scons -f bsp/stm32/.../SConstruct                         # ✗ 不支持（顶层目录变了，building.py:379 找错 SConscript）
```

`bsp/stm32/<board>/SConstruct` 里有前置守卫：跨目录 `-f` 会立刻打印「构建入口必须从板目录运行」并退出码 1，而不是抛 traceback。
板目录内 `scons -f SConstruct` 仍可用。

## 3. 路径契约（本项目自定，非上游）

| 变量 | 谁算 | 值 | 校验 |
|---|---|---|---|
| `PROJECT_ROOT` | 各入口 `SConstruct` | 环境变量覆盖 → 从入口目录向上找 `.git`/`AGENTS.md` → 报错 | 必须是存在的目录 |
| `RTT_ROOT` | `bsp_build.resolve_paths()` | `os.getenv('RTT_ROOT')` 或 `<PROJECT_ROOT>/os/rt-thread` | `include/rtthread.h`、`tools/building.py` |
| `LIBRARIES_DIR` | 同上 | `<board_dir>/../libraries` | `<STM32_LIBRARY>/SConscript`、`HAL_Drivers/SConscript` |
| `APP_ROOT` | 同上 | `os.getenv('APP_ROOT')` 或 `<PROJECT_ROOT>/app` | `SConscript` |
| `BUILD_DIR` | 同上 | `os.getenv('RT_BUILD_DIR')` 或 `<PROJECT_ROOT>/out/build/<入口目录名>` | 以相对入口目录的形式注入 `RT_BUILD_DIR` 给 `building.py` |
| `STM32_LIBRARY` | 板级 `rtconfig.py` | `'STM32F4xx_HAL'` / `'STM32F1xx_HAL'` | 缺失即报错 |

任一项不满足 → 打印「找不到X / 缺少标记文件 / 调用位置」并退出码 1（实现见 `bsp/stm32/tools/bsp_paths.py`）。

## 4. 升级上游的检查清单

1. `git diff <old> <new> -- os/rt-thread`，重点看 `tools/building.py`、`libcpu/`、`components/SConscript`；
2. 重贴偏离 #1 的 2 行：确认 `bsp_vdir = os.environ.get('RT_BUILD_DIR') or 'build'`；
3. 若 `bsp/stm32/libraries/*/SConscript` 被替换，重贴偏离 #2/#3 的 startup 六行；
4. 三块板各跑一次：`python scripts/firmware/build.py --board <name> clean` + `build`（或 `cd` 后 `scons`），要求 warning 0 / error 0；
5. 确认源码树里 `.o` 数量为 0：`Get-ChildItem -Recurse -Filter *.o | Where-Object { $_.FullName -notmatch '\\out\\build\\' }` 只应命中 `third-party/`；
6. 更新本文件与 `AGENTS.md` 的偏离条目。

## 5. 新增一块板的检查清单

1. 复制现有板目录结构（`board/`、`rtconfig.py`、`Kconfig`、`SConscript`、`applications/`）；
2. `rtconfig.py` 填 `ARCH/CPU/CROSS_TOOL/STM32_LIBRARY`（以及 `LFLAGS` 里的链接脚本名）；
3. `SConstruct` **不要手抄**：从任一现有板复制（三份应字节一致），或用生成器产出；
4. `Kconfig` 顶部确认 `RTT_DIR := ../../../os/rt-thread` 与注释一致；
5. 验证：`scons -C <新板> clean` + `scons -C <新板>`，检查 `out/build/<新板>/` 与 warning 0。

## 6. 新增一个项目的检查清单（P2 落地后适用）

1. `projects/<name>/project.toml`：声明 `board`、`variant`、`components`、`flash`；
2. `projects/<name>/rtconfig.py`：继承板级 `rtconfig.py`，覆盖 `LFLAGS`（链接脚本绝对化）与 `BUILD`；
3. `projects/<name>/Kconfig`：`mainmenu` + `source` 板级与 `app/` 的 Kconfig；
4. `projects/<name>/SConstruct`：与板级同一份薄壳（`BOARD_DIR` 由 `project.toml` 的 board 决定）；
5. `python scripts/firmware/build.py --project <name> build`，产物进 `out/build/<name>/`。
