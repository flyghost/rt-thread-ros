# rt-thread-ros

基于 RT-Thread 的遥控/机器人（ROS）固件工程：上游内核与自有代码物理分离，
并提供一套从设备崩溃到 PC 侧离线分析的 ramdump 诊断链路。

## 目录分层

| 目录 | 是什么 | 例外/约束 |
|---|---|---|
| `os/rt-thread/` | 上游 RT-Thread 内核与组件 | 自有改动应尽量收敛，便于整树替换/升级 |
| `bsp/stm32/<board>/` | 板级工程：`SConstruct` / `board/` / `applications/` / Keil 工程 | 现有 `stm32f407-atk-explorer`、`stm32f103c8t6-remoter`、`stm32f103-100ask-mini` |
| `app/` | 自有代码，与上游物理分离 | `ramdump/`（崩溃诊断）、`ros/`（`ANO_DT` 数据透传） |
| `scripts/` | 自有 PC 端脚本 | `ramdump/`（采集 + 解析）、`serial_hub/`（串口服务器） |
| `docs/` | 设计文档（含外来原始方案与已归档设计稿） | 见 `docs/` 索引说明 |
| `out/` | 中间文件 `build/<board>/`、最终 bin、dump、trace32 样本 | 不进版本库 |

构建接入：`bsp/stm32/<board>/SConstruct` 默认 `RTT_ROOT` 指向 `os/rt-thread`（可用环境变量覆盖），
并额外加载 `app/`；中间文件目录由 `RT_BUILD_DIR` 控制，脚本里默认指到 `out/build/<board>`。

## 索引（先看哪一份）

| 想了解 | 看这里 |
|---|---|
| **所有脚本命令（环境/编译/烧录/串口/采集/解析，Python 与 bat 对照）** | `scripts/README.md` |
| 仓库分层 / 构建烧录 / 关键路径 | `AGENTS.md` |
| ramdump 组件内部（异常链路 / 传输层 / 协议 / 脚本） | `app/ramdump/AGENTS.md` |
| ramdump 采集与解析的完整用法 | `scripts/ramdump/README.md` |
| 串口服务器（一个进程独占串口，人 + 脚本同连） | `scripts/serial_hub/README.md` |
| 守卫（信箱协议 / 白名单 / 排错） | `scripts/guard/README.md` |
| pyocd 安装与版本（唯一实现） | `tools/pyocd/README.md` |
| 设计文档（外来原始方案 / 已超越的实现方案 / 已落地的协议抽象稿） | `docs/` |

> **脚本怎么用一律看 `scripts/README.md`**（命令总表）；本 README 与 `AGENTS.md` 只留方向性结论，
> 避免出现第二份会过期的副本。

## 快速开始

```bash
# 构建 + 烧录（STM32F407 板，工具链与 pyocd 路径都在脚本里）
python scripts/firmware/build.py build-flash
python scripts/firmware/build.py status        # 固件 / pyocd / pack 状态

# 人手动用：双击 ai_services.bat（菜单：编译 / 烧录 / 守卫 / 串口 hub / 状态）

# 走统一脚本（编译 / 烧录 / 采集 / 解析四个桶）
python scripts/ramdump/build/build.py --flash
```

> `ai_services.bat` 只是人的启动壳，AI 一律直接调 Python 入口；`scripts/guard/`
> 是**可选**的长任务执行器（信箱 + 完整日志 + 改脚本自动重启 + 无人值守）。
