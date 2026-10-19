# serial_hub —— 串口中继（一个进程独占串口，多客户端同时收发）

Windows 的 COM 口默认**独占**：SecureCRT 打开后脚本再打开就是 `Access denied`；靠
`FILE_SHARE_*` 硬共享又会让两个读者**瓜分**读流（各自随机丢字节）。所以只有一个正确解：
**一个进程独占串口，其它人连它**。这个目录就是那个进程。

## 跑起来

```bash
python scripts/serial_hub/serial_hub.py                       # 按探测规则自动选串口（规则见 discovery/）
python scripts/serial_hub/serial_hub.py --com COM46 --baud 115200
python scripts/serial_hub/serial_hub.py --list                # 只列候选串口后退出
python scripts/serial_hub/serial_hub.py --stdout hex           # 本窗口按 hex+ASCII 实时显示
python scripts/serial_hub/serial_hub.py --stdout rxtx          # 本窗口也打 PC->串口 的内容
python scripts/serial_hub/serial_hub.py --ui tui               # 全屏界面（零依赖 ANSI TUI）
```

## 客户端怎么连

| 客户端 | 配置 |
|---|---|
| SecureCRT / PuTTY | Protocol = **Raw**，Host `127.0.0.1`，Port **5555** |
| MobaXterm | Session = **Telnet**，Host `127.0.0.1`，Port **5557** |
| 自动化脚本 | TCP 连 5555；内联命令 `@@lock` / `@@unlock` / `@@status` / `@@whoami` / `@@proto <raw\|telnet>` |
| 控制台 | `telnet 127.0.0.1 5556`：`help` / `status` / `sessions` / `lock <id>` / `proto <id> <raw\|telnet>` / `kill <id>` / `reset [dtr\|rts\|both]` / `shutdown` |

5555 = raw（首字节 0xFF 自动切 telnet，`--no-sniff` 可关）；5557 = 强制 telnet（`--telnet-port 0` 关掉）。

## 串口怎么被自动挑出来（探测规则）

`--com` 省略时，hub 枚举所有串口，按 `discovery/` 下的规则表挑一个。
**一个芯片家族 = 一个文件**，通用代码里不含任何型号知识：

| 规则文件 | 认什么 |
|---|---|
| `discovery/ch34x.py` | CH340/CH341/CH343/CH347：VID:PID 或描述关键字 |
| `discovery/cp210x.py` | CP2102/CP2104/CP2105/CP2108 |
| `discovery/ftdi.py` | FT232/FT231/FT2232/FT4232 |
| `discovery/usb_serial.py` | 兜底：任何带 USB 标记的串口（虚拟串口对、蓝牙 SPP 不会被它选中） |

判定强度：**VID:PID > 硬件ID关键字 > 描述关键字 > 串口名 glob**；同级再比 `priority`。

```bash
python scripts/serial_hub/serial_hub.py --list             # 候选串口 + 当前规则表
python scripts/serial_hub/serial_hub.py --prefer 1A86:7523  # 按 VID:PID 点名
python scripts/serial_hub/serial_hub.py --prefer name:COM7  # 按串口名（支持 * 通配）
python scripts/serial_hub/serial_hub.py --prefer desc:ch340
python scripts/serial_hub/serial_hub.py --prefer hwid:USB
```

同时有两个同级候选（板上一个、外接一个）时 hub 不会瞎猜，会直接让你用 `--com` 指定。

**加一个新家族**：在 `discovery/` 新建 `xxx.py` 暴露 `RULES = (PortRule(...),)`，再到
`discovery/__init__.py` 里 import 登记 —— 其它文件一律不用改。

## 为什么 raw / telnet 分两个端口

协议必须在**第一个字节被解释之前**就确定，而 raw 客户端永远不会自报家门 —— 它的首字节完全可能就是
`0xFF`（二进制协议的数据包、内存镜像里到处都是）。三种做法都实现了：**按端口分**（默认，零歧义）、
首字节嗅探（`--sniff-timeout` 兜底）、会话内 `@@proto` 声明。传输二进制数据时建议 `--no-sniff`，让 5555 100% 透明。

## 界面（可选；默认行为与无界面时逐字节相同）

```bash
python scripts/serial_hub/serial_hub.py --ui tui     # 全屏：状态行 + 数据面板 + 输入行
python scripts/serial_hub/serial_hub.py --ui stream  # 默认：现在的滚动输出
python scripts/serial_hub/serial_hub.py --ui none    # 完全静默（只写日志文件）
```

| 键 | 作用 |
|---|---|
| 打字 + `Enter` | 发到串口（自动补 `\r`） |
| `Tab` | 切换输入目标：发串口 / hub 命令（命令就是控制口那套） |
| `Ctrl-T` | 视图循环：`text` → `hex` → `both`（both = 左文本 / 右 hex） |
| `Ctrl-W` | 会话侧栏开关（会话号/协议/对端/收发/写锁） |
| `Ctrl-F` | 搜索：输入关键字回车，命中行加底色；`n` / `N` 跳下一个 / 上一个，`Esc` 退出搜索 |
| `Ctrl-L` / `Ctrl-S` | 清屏 / 存盘到 `out/dump/log-<时间>.{raw,txt,hex}` |
| `Ctrl-P` / `Ctrl-E` | 暂停滚动 / 显示自己发出去的内容（前缀 `>>> `） |
| `↑ ↓ PgUp PgDn End` | 翻历史（搜索状态下 `↑ ↓` = 上一个/下一个命中；`End` 回到跟随最新） |
| `F1` / `Esc` | 帮助面板开关（`Esc` 先退搜索，再关帮助） |
| `Ctrl-Q`（或连按两次 `Ctrl-C`） | 退出，串口正常释放 |

- `--ui tui` 但输出不是终端（管道/重定向）时，自动降级为 `stream` 并提示。
- 面板会自适应：终端窄于 64 列不画侧栏、窄于 48 列 `both` 自动退回单栏；
  `hex` 视图下按 `Ctrl-F` 会自动切回 `text`（hex 面板不参与高亮）。
- 界面只是**事件流的第四个 sink**：`core/relay.py` 把收发与状态 `emit` 出去，`tui/` 只画；
  想换 UI（或加 WebSocket 前端）就整个替换 `tui/` 目录，`core/` 一行都不用改。

## 日志（默认 `out/log/`）

| 文件 | 内容 |
|---|---|
| `serial-<时间>.raw` | **串口 -> PC 的字节精确流**（不含 PC->串口 方向，便于离线逐字节对账） |
| `serial-<时间>.log` | 双向、带时间戳/方向/会话号，非可见字符转义（给人看、给 AI grep） |

## 踩过的坑（都已修，留档）

- **MobaXterm 满屏 `^M`**：它只有 Telnet 会话类型，用 Telnet 连"哑中继"时，设备把它发的 IAC 协商当数据**回显**，
  客户端又把回显当协商解析 → 状态机打架。现在 telnet 口把 IAC 吃掉、且**同意 ECHO/SGA**：
  不同意 ECHO 会让客户端开本地回显（CR 就显示成 `^M`），不协商 SGA 会退回 Telnet 半双工（敲的字发不出去）。
- **`\r\r\n`**：设备发 `\r\n` 曾被补成 `\r\r\n`；现在按 NVT 规则（CR 后面必须跟 LF 或 NUL）。
- **hub 运行中日志文件看着是 0 B**：Windows 上只 `flush()` 不够，要 `fsync()`（见 `core/logstore.py`）。

## 目录

| 文件 | 职责 |
|---|---|
| `serial_hub.py` | 入口：命令行参数 + 装配 |
| `core/relay.py` | SerialHub：独占串口、selector 主循环、广播、写仲裁、掉线重连、控制命令实现 |
| `core/session.py` | Client：一条连接 = 一个会话（codec / 待发缓冲 / 写锁 / 计数） |
| `core/control.py` | 控制口 5556 的服务端（每连接一个线程） |
| `core/logstore.py` | `esc()` / `hexdump_text()` / `sync()` |
| `core/ports.py` | 串口枚举 + 首选端口编排（`--list`） |
| `discovery/` | 端口探测规则：`base.py`(PortInfo/PortRule/parse_rule_spec) + 一个家族一个文件（`ch34x.py` / `cp210x.py` / `ftdi.py` / `usb_serial.py` 兜底） |
| `core/util.py` | 时间戳 / 字节数 / 仓库根定位 |
| `protocols/base.py` | `Codec` 基类（`encode` / `decode` / `greeting` / `notes`） |
| `protocols/raw.py` | 透明字节 |
| `protocols/telnet.py` | Telnet 服务端（协商 + NVT 转义） |
| `protocols/__init__.py` | `CODECS` 注册表 |
| `tui/` | 可选全屏界面：`view.py`(纯渲染) / `app.py`(主循环) / `keys.py`(按键) / `ansi.py`(终端) |
| `tests/codec_check.py` | 离线自检（不接串口、不需要 COM 口） |
| `tests/hub_test.py` | 对着**已经在跑的** hub 测：双客户端广播 / 写锁 / 踢会话 |

## 加前端协议（rfc2217 / websocket）

1. 写一个 `Codec` 子类放 `protocols/`；
2. 在 `protocols/__init__.py` 的 `CODECS` 里登记；
3. 要独立端口就在 `core/relay.py` 的 `start_servers()` 里加一个监听（照 `--telnet-port` 抄）。

广播语义别踩错：**串口 -> PC 必须在原始字节上广播**，每个会话用自己的 codec `encode()` 后再发；
反方向 `decode()` 出来的控制事件（协商应答）只回给该会话，**绝不写进串口**。
