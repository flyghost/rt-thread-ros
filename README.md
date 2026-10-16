# rt-thread-ros

基于 RT-Thread 的遥控/机器人（ROS）固件工程：上游内核与自有代码物理分离，
并提供一套从设备崩溃到 PC 侧离线分析的 ramdump 诊断链路。

## 目录分层

| 目录 | 是什么 | 例外/约束 |
|---|---|---|
| `os/rt-thread/` | 上游 RT-Thread 内核与组件 | 自有改动应尽量收敛，便于整树替换/升级 |
| `bsp/stm32/<board>/` | 板级工程：`SConstruct` / `board/` / `applications/` / Keil 工程 | 现有 `stm32f407-atk-explorer`、`stm32f103c8t6-remoter`、`stm32f103-100ask-mini` |
| `app/` | 自有代码，与上游物理分离 | `ramdump/`（崩溃诊断）、`ros/`（`ANO_DT` 数据透传） |
| `tools/` | 自有 PC 端脚本 | `ramdump/`（采集 + 解析）、`serial_hub/`（串口服务器） |
| `docs/` | 设计文档（含外来原始方案与已归档设计稿） | 见 `docs/` 索引说明 |
| `out/` | 编译产物 + dump 输出 | 不进版本库 |

构建接入：`bsp/stm32/<board>/SConstruct` 默认 `RTT_ROOT` 指向 `os/rt-thread`（可用环境变量覆盖），
并额外加载 `app/`。

## 索引（先看哪一份）

| 想了解 | 看这里 |
|---|---|
| 仓库分层 / 构建烧录 / 关键路径 | `AGENTS.md` |
| ramdump 组件内部（异常链路 / 传输层 / 协议 / 脚本） | `app/ramdump/AGENTS.md` |
| ramdump 采集与解析的完整用法 | `tools/ramdump/README.md` |
| 串口服务器（一个进程独占串口，人 + 脚本同连） | `tools/serial_hub/README.md` |
| 设计文档（外来原始方案 / 已超越的实现方案 / 已落地的协议抽象稿） | `docs/` |

> 命令与端口号以 `AGENTS.md` 为准，本 README 不重述——历史版本曾在此处抄一份用法，
> 结果是脚本改名后 README 指的目录已不存在（见 `docs/` 归档说明）。

## 快速开始

```bash
# 构建 + 烧录（STM32F407 板，内置工具链默认值）
cd bsp/stm32/stm32f407-atk-explorer
build_and_flash.bat

# 或走统一脚本（编译 / 烧录 / 采集 / 解析四个桶）
python tools/ramdump/build/build.py --flash
```
