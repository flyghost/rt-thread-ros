# scripts/ — 本工程的胶水层

只放三类东西：两份 bat（`ai_services.bat` 服务面板、`ramdump.bat` 采集）、独立工具仓子模块
`toolbelt/`，以及本文件（说明）。

禁止放进本目录：
- **工具业务代码** → 进 `scripts/toolbelt/`（改完在子模块里提交并 push，再回本仓提交指针）；
- **工程事实**（板级路径、串口号、工具链、芯片型号）→ 进工程根 `toolbelt.toml`。

调用工具的规范入口：`python scripts/toolbelt/tools/run.py <命令>`。
双仓判据与提交顺序见根 `AGENTS.md` 的「双仓边界」——本文件不复述规则，避免两处漂移。
