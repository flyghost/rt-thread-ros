# flash_guard —— 烧录守卫

把「受限沙箱里跑不了」的硬件动作（烧录 / 探针 / 编译）交给一个**由人手动启动、不在沙箱里**的进程。
AI 在仓内写请求文件，守卫执行，再把退出码与日志写回仓内。**没有提权，没有远程 shell。**

## 为什么需要它

`tools/pyocd/0.1.3/pyocd.exe` 是 PyInstaller 单文件包，启动时要把 `VCRUNTIME140.dll` 解压到临时目录。
DSH 的受限文件沙箱（`workspace-write`）只允许写工作区，于是它必然报：

```
pyocd.exe : VCRUNTIME140.dll could not be extracted!
fopen: Permission denied
[sandbox: file access denied under workspace-write mode]
```

放宽到 `danger-full-access` 也不解决——实测两次都让 job runner 以 `3221225478`（`0xC0000142`）挂死，
之后连 `Write-Output "ok"` 都跑不了，只能重启电脑。

结论：**这不是「权限不够」，是「进程位置不对」**。所以换成「人开一个不受限的窗口 + 文件信箱」，
这与 `omnibus` 仓的 `build_guard.py` 是同一套办法。

## 两条命令

沙箱**之外**（人来做，窗口开着别关，Ctrl+C 退出）——双击仓库根的 `ai_services.bat` 即可。
它是**「AI 需要你开的服务台」**：目前能起两个常驻服务，以后新服务往同一个文件里加。

| 服务 | 为什么 AI 自己起不了 |
|---|---|
| `guard` 烧录守卫 | `pyocd.exe` 是 PyInstaller 单文件包，必须解包 DLL 到临时目录，沙箱写不了工作区外 |
| `hub` 串口 hub | 一个 COM 口只能被一个进程独占，AI 和人要同时看串口 |

```powershell
ai_services.bat                     :: 菜单：1 守卫 / 2 hub / 3 两个都起 / 4 状态 / 0 退出
ai_services.bat guard               :: 只起守卫（本窗口，常驻）
ai_services.bat hub                 :: 只起串口 hub（本窗口，COM46 @ 115200 -> TCP 5555）
ai_services.bat hub COM7 921600     :: 换串口 / 波特率
ai_services.bat both                :: 守卫本窗口 + hub 另开一个窗口
ai_services.bat status              :: 守卫活没活 / 5555·5556 有没有人听 / 串口候选 / 固件

:: 等价的手工方式（不想用 bat 时）
python scripts\flash_guard\flash_guard.py
python scripts\serial_hub\serial_hub.py --com COM46 --baud 115200 --ui tui
```

`ai_services.bat` 里可调的项：`HUB_COM` / `HUB_BAUD`（板级默认值）、`HUB_UI`（`tui` 默认，
无界面跑用 `set HUB_UI=none` 再启动）、`PY313`（装 pyserial 的解释器）。

**加一个新服务**（比如日志采集、探针复位、CAN 桥）：工具本身放 `scripts/<name>/`，
然后在 `ai_services.bat` 里加一个 `:<name>` 标签（照抄 `:guard` 的形状）+ 菜单一行 + 头部 usage 一行。
不要在这个 bat 里塞业务逻辑——它只是启动器。

> **这个 bat 刻意做成纯 ASCII + CRLF 换行。** 两个坑都是实测踩出来的：
> ① 中文必须与控制台代码页（本机 GBK）一致，否则 cmd 会把中文字节当命令执行；
> ② 只有 LF 换行会让 cmd 的 `goto`/标签解析错乱，直接变成**死循环**（实测几十秒写掉 322 KB 日志）。
> 想加中文注释，请另写 `.md`，不要塞进这个 `.bat`。

沙箱**之内**（AI 或你都能跑，只读写仓内文件）：

```powershell
python scripts\flash_guard\flash_guard.py --status                      # 守卫生不活着 + 积压
python scripts\flash_guard\flash_guard.py --request flash --wait        # 烧录现在的 rtthread.bin
python scripts\flash_guard\flash_guard.py --request build_flash --wait --wait-timeout 600
python scripts\flash_guard\flash_guard.py --list                        # 历史请求一览
```

## 动作白名单

守卫**只认这几个动作**，argv 由它自己现拼（不经 shell），参数值带 shell 元字符一律 `rejected`。

| action | 单次上限 | 实际执行的命令 | 用途 |
|---|---|---|---|
| `flash` | 180 s | `pyocd flash --target STM32F407VE --erase=auto --frequency=1000000 <bin>`（`package` 时多一个 `--pack`） | 烧录 |
| `build_flash` | 1100 s | `scons -j20` 然后上面那条 | 一条龙 |
| `build` | 900 s | `scons -j20`（沙箱内其实也能编，留着备用） | 编译 |
| `list` | 60 s | `pyocd list` | 看调试器认不认得到 |
| `erase` | 180 s | `pyocd erase --target <tgt> --chip` | 整片擦除 |
| `reset` | 60 s | `pyocd reset --target <tgt>` | 复位 |
| `probe` | 90 s | 打印 `TEMP/TMP/TMPDIR`、试建临时目录、再跑 `pyocd.exe --version` | 环境自检（烧不动时先跑它） |
| `selftest` | 30 s | `python -c "print('flash_guard selftest ok')"` | 验证信箱协议本身 |

参数（写进 `args`）：`target`（默认 `STM32F407VE`）、`bin`（仓内相对路径，默认 `bsp/stm32/stm32f407-atk-explorer/rtthread.bin`）、`pyocd`（`bundled` / `package`，默认 `bundled`）、`note`。

### 两套 pyocd：`--pyocd bundled|package`

| 值 | 是什么 | 什么时候用 |
|---|---|---|
| `bundled`（默认） | 仓里自带的 `tools/pyocd/0.1.3/pyocd.exe`（PyInstaller 单文件，**版本 0.27**） | 老探针（CMSIS-DAP v1/HID、ST-Link） |
| `package` | `pip install --target out/pyocd_pkg pyocd` 装的 **0.45.1**，用 `python -m pyocd` 跑（`libusb-package` 自带 libusb DLL） | 新探针（CMSIS-DAP **v2**，WinUSB/bulk 接口，在 Windows 上显示为 `WinUsb Device` / `Horco CMSIS-DAP v2` 之类） |

`package` 方式下守卫会额外设 `PYTHONPATH=<repo>/out/pyocd_pkg` 与 `PYOCD_HOME=<repo>/out/pyocd_home`（否则 pyocd 要去写 `C:\Users\<me>\.pyocd`，那是工作区外）。
实测：同一块板，0.27 报 `No available debug probes are connected`，0.45.1 能列出探针——**版本差异**，不是驱动或权限问题。

### 新版 pyocd 的 pack 从仓库里拿：`--pack`

新版 pyocd 删掉了内置芯片定义（`out/pyocd_pkg/pyocd/target/` 只剩 `__init__.py`），
只带几十个 `builtin` 目标，**STM32F407VE 不在里面**，不加 pack 就报
`Target type stm32f407ve not recognized`。

守卫给 `package` 方式的每条 pyocd 命令都加 `--pack <repo>/tools/pyocd/0.1.3/packs/Keil.STM32F4xx_DFP.2.14.0-small.pack`
（仓里原本就有这份，是给 0.27 的 `pyocd.yaml` 用的）。于是：

| 不做的事 | 原因 |
|---|---|
| 不用 `pyocd pack install stm32f407ve` | 那会先下**全球厂商 pack 索引**（实测 1704 个 `.pdsc` / 134.5 MB）再下 2 MB 的 pack，全塞在 `C:\Users\<me>\AppData\Local\cmsis-pack-manager`，仓库外、不可复现 |
| 不依赖用户目录缓存 | `--pack` 直接把路径喂给 pyocd，缓存目录里有什么都不影响 |

验证过的两条等价证据：

```
python -m pyocd list --targets --pack scripts\pyocd\0.1.3\packs\Keil.STM32F4xx_DFP.2.14.0-small.pack
  → stm32f407ve   STMicroelectronics   STM32F407VE   ...   pack
```
```
--request flash --pyocd package --wait   → exitCode=0，identical 261120 bytes (255 pages)
```

`pack` 这个 action 仍留在白名单里，但**平时不用**——只有换芯片（仓库里没有对应 pack）时才需要。
要换芯片：把新的 `.pack` 放进 `tools/pyocd/0.1.3/packs/`，把 `REPO_PACK` 指过去即可（比 `pack install` 更可复现）。

### 改了守卫脚本不用再关窗口：自动重启

守卫每轮轮询会看自己这个 `.py` 的 mtime；一变就 `os.execv` 原地换一份新代码（最多自动换 3 次，防崩溃循环）。
横幅会打印「检测到 flash_guard.py 被改动 —— 自动重启以载入新代码」。
（换进程的瞬间 pid 会变，`guard.lock` 靠 pid 判活，会自动接管。）

### 子进程的 TEMP 被钉在 `out/tmp/`

`pyocd.exe` 是 PyInstaller 单文件包，**启动时先把自己解包到临时目录**才谈得上干活。
守卫给所有子进程把 `TEMP`/`TMP`/`TMPDIR` 强制指向仓库内的 `out/tmp/`，不继承窗口的环境变量——
实测有窗口带着已失效的 per-session 临时路径，pyocd 直接报
`[18336] INTERNAL ERROR: cannot create temporary directory!` 并退 `-1`（退出码 `4294967295`）。
守卫横幅里会打印「子进程TEMP」这一行，烧不动时先 `--request probe --wait` 看它。

同一件事在 `ai_services.bat` 里也做了一遍（`set "TEMP=%REPO%out\tmp"` 等三行，在建任何子进程之前）：
两层都有必要——bat 那层管住「这个窗口及其所有后代」，守卫那层管住「即使窗口的 TEMP 是坏的，我派出去的子进程也不受影响」。

## 信箱协议

默认目录 `out/guard/`（`/out/` 已被 gitignore；`--mailbox` 可改）。

| 文件 | 谁写 | 内容 |
|---|---|---|
| `req_NNNN.json` | 会话侧 | `{protocol, action, args, createdAt, expiresIn, note}` |
| `rep_NNNN.json` | 守卫 | `{status, exitCode, message, startedAt, finishedAt, queuedSeconds, log, tail[]}` |
| `rep_NNNN.log` | 守卫 | 完整 stdout+stderr（UTF-8） |
| `heartbeat.json` | 守卫，每 2 s | `pid/beatAt/pending/running` —— 判断「守卫在不在」 |
| `running.json` | 守卫，执行中每 1 s | 谁在跑、已跑多久、日志多长、最后增长时刻 |
| `guard.lock` | 守卫 | 防重入；旧 pid 已死则新守卫自动接管 |

`status` 取值：`ok` / `failed` / `timeout` / `expired` / `rejected`。

两处时间判据（防「永远挂住」）：

- **停滞**：日志连续 180 s 没有新字节 ⇒ 判 `timeout` 并 `taskkill /F /T` 连进程树杀（`--stall`，0 = 关闭）。
- **总时长**：超过该动作上限同样杀掉（`--timeout` 覆盖）。

会话侧 `--wait` 只是**放弃等待**（默认 300 s，退 2），**不会杀掉守卫里的任务**：烧录可能还在跑，事后 `--list` 或读日志。

## 边界（刻意不做的事）

- 不接受任意命令、不代你决定跑哪个动作、不替你 commit。
- 不联网、不读凭据、不写仓库以外的路径。
- 不判断固件是否该烧——HEAD/工作区是否一致由调用者自己负责。

## 排查

| 现象 | 原因 / 处理 |
|---|---|
| `--request` 报 `守卫不在跑` | 沙箱外那个窗口没开（或已退出）。双击 `ai_services.bat` |
| `--status` 显示「不在跑」但窗口还开着 | 看窗口里是否已退出；残留 `guard.lock` 会按 pid 自动接管，不用手工删 |
| 请求一直「排队中」 | 守卫在跑长任务（`--status` 会显示 `正在执行` + 已跑多久 + 日志字节数） |
| 改了 `flash_guard.py` 后行为没变 | 守卫会自动重启（看 mtime，最多 3 次）；若仍异常，关掉窗口重开最稳 |
| 想要干净的信箱 | 删 `out/guard/` 即可，守卫每 2 s 重建目录 |
