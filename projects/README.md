# projects/ —— 项目层（同一块板，多个产品配置）

一个 **project** = 「一块板 + 一套配置 + 一套自有源」，编译产物落在自己目录，互不干扰。
板级硬件描述仍然只有一份，放在 `bsp/stm32/<board>/`；项目只引用它，不复制它。

## 目录结构（当前只有 base）

```
projects/
└── base/                 # 出厂基线：不加任何自有代码，行为与板级编译完全一致
    ├── project.toml      # 单一事实来源：板子是谁、变体、目标名、烧录参数
    ├── SConstruct        # 薄入口（~90 行）：找根 → 读 toml → 交给 bsp/stm32/tools
    ├── rtconfig.py       # 继承板级 rtconfig，仅覆盖项目特有项（链接脚本绝对化）
    ├── SConscript        # 编译组建：板级 board/ + applications/，以及本项目子目录
    ├── Kconfig           # 占位（menuconfig 仍在板目录跑，见「已知限制」）
    └── rtconfig.h        # 从板级复制（P3 计划改成 defconfig + fragment 生成）
```

## 怎么用

```powershell
# 默认构建 projects/base（等价于 python scripts\firmware\build.py build）
cd projects\base
scons -j20

# 推荐：用统一 CLI（会自动设工具链环境变量、产物收进 out/）
python scripts\firmware\build.py status        # 看入口/中间目录/固件/pyocd
python scripts\firmware\build.py build         # 编译（默认 projects/base）
python scripts\firmware\build.py build-flash   # 编译 + 烧录
python scripts\firmware\build.py --project base build
python scripts\firmware\build.py --board build # 直接编译板级 BSP（对照用）
```

中间文件统一在 `out/build/base/`（板级模式是 `out/build/stm32f407-atk-explorer/`），
**源码树里不会出现 `.o`**；产物是本目录的 `rt-thread.elf` / `rt-thread.map` / `rtthread.bin`。

## 构建入口必须"站对目录"

SCons 把**执行命令时所在的目录**当顶层目录（`#`），RT-Thread 上游有 6 处依赖它
（详见 `docs/upstream-patches.md` 第 2 节）。所以：

| 可以 | 不行 |
|---|---|
| `cd projects\base` 后 `scons` | `scons -f projects\base\SConstruct`（从仓库根） |
| 任意目录 `scons -C projects\base` | 同上 |
| `python scripts\firmware\build.py ...`（内部会切 cwd） | — |

薄入口会检查 `os.getcwd()`，不匹配直接报错退 1，不会编译到一半才崩。

## 新增一个项目（P2 之后）

1. `cp -r projects/base projects/<name>`，改 `project.toml` 的 `name`；
2. 在项目里放 `applications/`、`src/` 等自有源（每个目录一个 `SConscript`，会被自动收进来）；
3. 需要不同配置就改本项目 `rtconfig.h`；
4. `python scripts\firmware\build.py --project <name> build`。

## 已知限制（都在后续批次里）

| 限制 | 现状 | 计划 |
|---|---|---|
| `rtconfig.h` 是复制来的 | 两处改动要手动同步 | P3：defconfig + fragment 生成 |
| `menuconfig` 只能在板目录跑 | 板级 `Kconfig` 的 `RTT_DIR` 是相对板目录的常量 | P3：项目级 Kconfig |
| 多项目并行构建 | 未验证（目前只跑了 base） | 后续批次 |
| 烧录参数 | 目前取 `scripts/firmware/config.py`（STM32F407VE + 仓内 pack） | 后续读 `project.toml [flash]` |
