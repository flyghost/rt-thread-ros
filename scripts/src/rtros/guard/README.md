# scripts/guard —— 沙箱外执行器（任务表驱动）

守卫是**由人手动启动、常驻在沙箱之外**的执行器：AI 往仓内信箱写一个请求文件，守卫按**白名单**执行，
把退出码和完整日志写回仓内。它不烧录专用——具体能跑什么由 `tasks.toml` 决定。

什么时候用它：

| 场景 | 为什么 |
|---|---|
| 一次构建 8 分钟 | 会话侧 `--wait` 有超时，守卫能继续跑，日志逐行落盘 |
| 无人值守跑长任务 | 关掉会话也不影响守卫执行 |
| 想看「谁在跑、跑了多久、日志还在涨吗」 | 守卫 1 s 刷 `running.json`、2 s 刷 `heartbeat.json` |
| 需要沙箱外环境 | 某些程序在 DSH 沙箱内起不来（历史问题：PyInstaller 解包） |

> 现在**烧录不必走守卫**：pyocd 是 `python -m pyocd`，会话里直接
> `python scripts/run_rtros.py build flash` 即可（沙箱内实测通过）。守卫是**可选**的长任务执行器。

## 两半

| 半边 | 谁用 | 入口 |
|---|---|---|
| 会话侧 | AI / 脚本 | `python scripts/run_rtros.py guard --status / --list / --tasks / --request <id> --wait` |
| 守卫侧（常驻） | 人 | 双击仓根 `ai_services.bat`，菜单 **7 guard**；或 `python scripts/run_rtros.py guard` |

守卫窗口**开着就行**，Ctrl+C 退出。

## 任务表：`scripts/src/rtros/guard/tasks.toml`

「哪些命令允许被请求执行」只有这一处定义。加一条任务 = 加一段 `[[tasks]]`，**不用改 `guard.py`**。

```toml
[[tasks]]
id      = "flash"                       # 请求里写的名字
title   = "烧录固件（pyocd flash）"       # 横幅 / --tasks 里显示
timeout = 180                           # 单次总时长上限（秒）
allow   = ["bin", "target"]              # 允许请求携带的参数（note 永远允许）
run = [[                                # argv 列表的列表：按顺序执行，任一失败即整条失败
  "{pyocd_python}", "-m", "pyocd", "flash",
  "--pack", "{pyocd_pack}", "--target", "{target}",
  "--erase=auto", "--frequency=1000000", "{bin}",
]]
```

| 键 | 说明 |
|---|---|
| `id` | 全表唯一，请求里用它（`--request flash`） |
| `title` | 一行说明，横幅与 `--tasks` 显示 |
| `timeout` | 单次总时长上限；另受停滞判据约束（默认 180 s 日志无增长即判卡住） |
| `allow` | 允许请求携带的参数名；只有 `bin` / `target` 有意义，`note` 永远允许 |
| `run` | 每行一条 argv，**不经 shell**；占位符在守卫里展开 |
| `cwd` | 工作目录，默认仓库根 |
| `builtin` | 需要内嵌 Python 源码的任务指到 `guard.py` 的实现（`probe` / `usb` / `selftest`） |

占位符：`{repo}`、`{python}`，加上 `[paths]` 里每个键（`{venv_python}`、`{pyocd_python}`、`{pyocd_pack}`、
`{build_entry}` …），以及请求参数 `{bin}`、`{target}`。`[paths]` 里的相对路径会补成仓内绝对路径；
其余占位符调用方**无法注入**。

当前内置任务：

| id | 干什么 |
|---|---|
| `probe` | 自证环境：TEMP/TMP/TMPDIR 可写、`mkdtemp` 能否写入、pyocd 版本、pkg 在不在 |
| `usb` | pyusb/libusb 枚举，看 libusb 到底能看见哪些设备 |
| `selftest` | 只跑 `python -c "print('guard selftest ok')"`，验证信箱协议本身 |

## 会话侧命令

```powershell
python scripts/run_rtros.py guard --status                                  # 守卫活没活 + 积压 + 心跳
python scripts/run_rtros.py guard --tasks                                   # 列出 tasks.toml 允许的任务
python scripts/run_rtros.py guard --request list --wait                     # 看调试器认不认得到
python scripts/run_rtros.py guard --request flash --wait                    # 烧 tasks.toml 的 default_bin
python scripts/run_rtros.py guard --request flash --bin out\bin\base\rtthread.bin --wait
python scripts/run_rtros.py guard --request build_flash --wait --wait-timeout 900
python scripts/run_rtros.py guard --list                                    # 历史请求一览
```

| 参数 | 说明 |
|---|---|
| `--request <id>` | 下请求；`id` 必须在 `tasks.toml` 里 |
| `--bin <相对路径>` | 仅当任务 `allow` 含 `bin`；必须是仓内相对路径，扩展名 `.bin/.hex/.elf` |
| `--target <型号>` | 仅当 `allow` 含 `target`；只许 `[A-Za-z0-9_.+-]` |
| `--note <文字>` | 备注（≤200 字符），写进请求便于追溯 |
| `--expires <秒>` | 请求有效期（默认 900）；过期守卫不执行 |
| `--wait` / `--wait-timeout` | 等应答并回显日志尾（默认 300 s）；超时**不杀**守卫里的任务 |
| `--mailbox <目录>` | 换信箱（默认 `out/guard`），并行测试用 |
| `--once` / `--timeout` / `--stall` | 守卫侧：处理完积压就退 / 覆盖单次上限 / 停滞判据 |

退出码：`0` 成功；`1` 跑了但失败；`2` 用法错、被拒、或等待超时；`3` 守卫不在跑。

## 信箱与协议

| 文件 | 作用 |
|---|---|
| `req_NNNN.json` | 请求（`protocol`/`id`/`action`/`args`/`head`/`createdAt`+`expiresIn`/`note`） |
| `rep_NNNN.json` | 应答：`status`、`exitCode`、`startedAt`、`finishedAt`、`queuedSeconds`、`log`、`tail` |
| `rep_NNNN.log` | 完整输出（逐行落盘） |
| `heartbeat.json` | 心跳（2 s），带一份 `running` |
| `running.json` | 正在跑什么、何时开始、日志多长、最后增长时刻（1 s 刷） |
| `guard.lock` | 防重入（写 pid）；旧 pid 已死会自动接管 |

全部 UTF-8；先写 `.tmp` 再改名（原子）。

## 安全边界

**守卫是「白名单执行器」，不是远程 shell。** 它不接受任意命令、不代你判断该跑哪一层、
也不替你决定要不要提交。请求只能：命中 `tasks.toml` 的 `id`、携带该任务 `allow` 声明的参数、
参数值通过校验（无 shell 元字符 / `target` 限字符集 / `bin` 限仓内相对路径与扩展名），
其余一律 `rejected` 且不执行。

## 子进程的 TEMP 钉在 `out/tmp`

守卫给所有子进程设 `TEMP=TMP=TMPDIR=<仓库>/out/tmp`。原因：换机器/换窗口后继承来的 `TEMP`
可能指向已失效的 per-session 目录，解包型程序会直接
`INTERNAL ERROR: cannot create temporary directory!`（退出码 `4294967295` = `-1`）。
钉在仓库内既可控、又不需要额外权限。

## 改动自动生效

守卫每轮轮询比对 `guard.py` 与 `tasks.toml` 的 mtime：任一变化就自动重启（最多 3 次）。
改任务表不用关窗口；但若是守卫以老版本代码启动、且这次改的是**代码结构**，建议重开一次窗口确认。

## 排错

| 现象 | 原因 / 处理 |
|---|---|
| `--status` 退 3 | 守卫没跑：双击 `ai_services.bat`，菜单 7 |
| `--request` 退 2 | 任务名或参数被拒（错误信息会指出是 `id`、`bin`、`target` 哪一项） |
| `rep` 里 `status=failed` + `4294967295` | 子进程起不来，先 `--request probe` 看 TEMP/pyocd |
| 长时间没有日志增长 | 180 s 停滞判据会连进程树杀掉，`rep` 里 `status=timeout` |
| 改了 `tasks.toml` 没生效 | 看横幅是否打印「自动重启」；否则重开窗口 |
| 两条请求抢同一设备 | 单个守卫是串行的；要并行就换 `--mailbox` 起第二个守卫 |
