# scripts/flash_guard —— 长任务执行器 / 烧录信箱

## 为什么需要它（以及它现在不是必需的）

早期仓里的 pyocd 是 RT-Thread 打包的 **PyInstaller 单文件 `pyocd.exe`**：它启动第一步要把自带的 DLL
解包到临时目录，在 DSH 文件沙箱里必然报 `VCRUNTIME140.dll could not be extracted!` +
`fopen: Permission denied`（进程退 `-1`）。那时的唯一出路就是「把动作交给沙箱外的进程」。

现在 pyocd 换成 `python -m pyocd`（pip 装在 `tools/pyocd/pkg`），**不再解包自己，沙箱里也能直接烧**
（实测 `python scripts/firmware/build.py flash` 在会话内即可完成）。所以：

| 场景 | 用什么 |
|---|---|
| 日常编译 / 烧录 | 直接 `python scripts/firmware/build.py build-flash` |
| 不想一直被 `--wait` 阻塞、要完整日志、要人开着的窗口执行、要改脚本自动重载 | 用本守卫 |

守卫的价值从「唯一通路」变成「可选的长任务执行器」：**AI 在仓内写请求文件 → 沙箱外的人类窗口执行 →
退出码与完整日志写回仓内**，守护进程还能在脚本被改动时 `os.execv` 自重启。

守卫是「白名单执行器」，不是远程 shell：它不接受任意命令、参数值由它自己拼 argv、不经 shell。

## 两半

| 半边 | 在哪跑 | 干什么 |
|---|---|---|
| 会话侧 | 沙箱内（AI 或你） | `--status` / `--list` / `--request`，往信箱写 `req_NNNN.json`，等 `rep_NNNN.json` |
| 守卫 | 沙箱**外**（人启动，窗口别关） | 每 2 s 扫信箱，按白名单执行，写 `running.json` / `heartbeat.json` / `rep_*.json` / `rep_*.log` |

信箱默认 `out/guard/`（`out/` 已被 gitignore）。协议版本 `PROTOCOL = 1`，请求带有效期（默认 900 s）与 HEAD，
过期/HEAD 不符一律不跑。

## 启动

**人手动**（推荐）：双击仓库根的 `ai_services.bat`，菜单选 `4 flash guard`。
命令行等价：

```bat
ai_services.bat guard              :: 本窗口起守卫（常驻）
ai_services.bat hub                :: 起串口 hub（COM46 @ 115200 → TCP 5555）
ai_services.bat both               :: hub 另开窗口 + 守卫本窗口
ai_services.bat status             :: 守卫 / 端口 / 串口 / 固件
ai_services.bat build              :: 编译
ai_services.bat flash              :: 经守卫烧录
ai_services.bat build-flash        :: 编译 + 烧录
ai_services.bat help               :: 用法
```

`ai_services.bat` 只是**人的启动壳**，里面每一行都转调 Python；AI 不要走 bat。

## 会话侧命令（沙箱内）

```powershell
python scripts\flash_guard\flash_guard.py --status                      # 守卫活没活 + 积压
python scripts\flash_guard\flash_guard.py --request list --wait         # 看调试器认不认得到
python scripts\flash_guard\flash_guard.py --request flash --wait        # 烧现在的 rtthread.bin
python scripts\flash_guard\flash_guard.py --request build_flash --wait --wait-timeout 900
python scripts\flash_guard\flash_guard.py --list                        # 历史请求一览
```

退出码：`0` 成功 / `1` 跑了但失败 / `2` 用法错、被拒或等待超时 / `3` 守卫不在跑。
`--wait` 超时**不会**杀守卫里的任务，只是不再等。

## 动作白名单

argv 由守卫现拼（不经 shell）；参数值含 shell 元字符一律 `rejected`。

| action | 上限 | 实际执行的命令 | 用途 |
|---|---|---|---|
| `flash` | 180 s | `python -m pyocd flash --target STM32F407VE --erase=auto --frequency=1000000 --pack <pack> <bin>` | 烧录 |
| `build_flash` | 1100 s | 先 `python scripts/firmware/build.py build`，再上面那条 | 一条龙 |
| `build` | 900 s | `python scripts/firmware/build.py build`（沙箱内其实也能编，留着备用） | 编译 |
| `list` | 60 s | `python -m pyocd list -v --pack <pack>` | 看调试器认不认得到 |
| `erase` | 180 s | `python -m pyocd erase --target <tgt> --chip` | 整片擦除 |
| `reset` | 60 s | `python -m pyocd reset --target <tgt>` | 复位 |
| `probe` | 90 s | 打印 `TEMP/TMP/TMPDIR`、试建临时目录、跑 `python -m pyocd --version` | 环境自检（烧不动先跑它） |
| `usb` | 60 s | 用 pyusb/libusb 枚举 USB 设备（`LIBUSB_DEBUG=4`） | 定位「设备到底在不在」 |
| `selftest` | 30 s | `python -c "print('flash_guard selftest ok')"` | 验证信箱协议本身 |

参数（写进 `args`）：`target`（默认 `STM32F407VE`）、`bin`（仓内相对路径，默认 `bsp/stm32/stm32f407-atk-explorer/rtthread.bin`）、`note`（≤200 字符）。

## pyocd 只有一份

守卫与 `scripts/firmware/` 用的是同一份：**`tools/pyocd/pkg` 里 pip 装的 pyocd 0.45.x**，用
`python -m pyocd` 跑，守卫给它设 `PYTHONPATH=tools/pyocd/pkg`。

- 仓里那个 `pyocd.exe`（RT-Thread 打包的 0.27）已删除：它认不到 CMSIS-DAP **v2**（WinUSB/bulk）探针，
  `list` 恒为空。
- 芯片定义一律 `--pack tools/pyocd/packs/Keil.STM32F4xx_DFP.2.14.0-small.pack`，
  **不跑 `pyocd pack install`**（那会往 `C:\Users\<me>\AppData\Local\cmsis-pack-manager` 下 130+ MB 全局索引）。
- 安装/复现：`python tools/pyocd/install.py`（详见 `tools/pyocd/README.md`）。

## 子进程的 TEMP 被钉在 `out/tmp/`

PyInstaller 式的单文件程序启动时要解包到 `%TEMP%`；窗口里继承来的 per-session TEMP 可能已失效
（实测报 `INTERNAL ERROR: cannot create temporary directory!`，退出码 `4294967295` = `-1`）。

所以守卫给每个子进程设 `TEMP = TMP = TMPDIR = <repo>/out/tmp`（并 `mkdir` 兜底），
`ai_services.bat` 里也设了一遍（`set "TEMP=%REPO%out\tmp"`）——两层都有必要。

## 改了守卫脚本不用关窗口

守卫每轮轮询看自己这个 `.py` 的 mtime，一变就 `os.execv` 原地换新代码（最多 3 次防崩溃循环），
横幅会打印「检测到 flash_guard.py 被改动 —— 自动重启以载入新代码」。pid 会变，`guard.lock` 靠 pid 判活自动接管。

## ai_services.bat 的两条硬约束（实测踩出来的）

1. **纯 ASCII**：`.bat` 由 cmd.exe 按当前代码页逐字节解析，UTF-8 中文会被拆成乱码命令
   （`'菜单' is not recognized ...`）；
2. **CRLF 换行**：只有 LF 时 `goto`/标签解析会错乱，实测会进入死循环刷屏。

中文说明一律写在 `.md` 里（就是本文件）。改完 bat 自查：
`(Get-Content ai_services.bat -Raw).Length` 与「非 ASCII 字节数 = 0、纯 LF 行数 = 0」。

## 排错

| 现象 | 原因 / 处置 |
|---|---|
| `--request` 报「守卫不在跑」 | 沙箱外那个窗口没开或已退出。双击 `ai_services.bat` 选 4 |
| `pyocd` 报 `No available debug probes are connected` | 探针不在线（USB 口/线/hub），先 `--request list --wait`，再 `--request usb --wait` 看 libusb 视角 |
| `cannot create temporary directory` | TEMP 坏了；`--request probe --wait` 看守卫钉的 TEMP 是否可写 |
| `Target type stm32f407ve not recognized` | 缺 `--pack`；确认 `tools/pyocd/packs/*.pack` 在 |
| 修改后行为没变 | 守卫还在跑旧代码；等它自动重启，或关掉窗口重开 |
