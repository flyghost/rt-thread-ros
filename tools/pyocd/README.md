# tools/pyocd —— 仓库里唯一的 pyocd

`pyocd` 负责把 `rtthread.bin` 烧进 STM32F407VE。**全仓只认这一份**，没有第二套、也没有兜底分支。

## 目录

| 路径 | 进 Git | 说明 |
|---|---|---|
| `install.py` | ✅ | 安装 / 检查脚本（唯一入口） |
| `packs/` | ✅ | 芯片定义（CMSIS pack），3 个文件约 1.3 MB |
| `pkg/` | ❌ 已被 `.gitignore` 忽略 | pip 装出来的 pyocd + 18 个依赖，约 50 MB / 1652 个文件 |

`pkg/` 不进库的原因：它是"下载下来的第三方工具"，和 `*.exe` 一样属于本地产物；进库会让仓库膨胀 50 MB，且换平台（Linux/macOS）还要重装。

## 安装

```powershell
python tools\pyocd\install.py            # 装固定版本 0.45.1
python tools\pyocd\install.py --check    # 只检查
python tools\pyocd\install.py --force    # 删掉 pkg/ 重装
```

版本钉在 `install.py` 的 `PYOCD_VERSION`。脚本内部做了两件必要的事：

1. **patch `tempfile.mkdtemp`**：本机沙箱给 `mkdtemp` 建出的目录设了本进程不可写的 ACL，pip 的暂存全靠它，不 patch 就必然 `PermissionError`；
2. **同进程调用 pip**：换子进程会让 patch 失效。

## 用法

pyocd 需要 `PYTHONPATH` 指到 `pkg/`，并显式给 `--pack`（新版 pyocd 不再内置 STM32F407VE 的芯片定义）：

```powershell
$env:PYTHONPATH = "E:\GitHub\me\ros\rt-thread-ros\tools\pyocd\pkg"
python -m pyocd list
python -m pyocd flash --target STM32F407VE --erase=auto --frequency=1000000 `
    --pack tools\pyocd\packs\Keil.STM32F4xx_DFP.2.14.0-small.pack `
    bsp\stm32\stm32f407-atk-explorer\rtthread.bin
```

平时不用手敲这些 —— 统一走：

| 场景 | 入口 |
|---|---|
| 人手动烧录 | `ai_services.bat` → 菜单（内部转调下面的 Python） |
| 编译 / 烧录 / 清理 | `python scripts\build\build.py {build,flash,build-flash,clean}` |
| 沙箱里的 AI 烧录 | `scripts\guard\guard.py --request flash --wait`（守卫在沙箱外执行 pyocd） |

## 依赖

pyocd 0.45.1 声明 18 个硬依赖（`pyusb`、`libusb-package`、`intelhex`、`cmsis-pack-manager`、`prettytable`、`pyelftools`、`intervaltree`、`pylink-square`、`hidapi`、`capstone`、`lark`、`colorama`、`natsort`、`pyyaml`、`importlib_metadata`、`importlib_resources`、`typing_extensions`），其中 `hidapi`、`cffi` 是编译型 wheel。所以"从源码跑 pyocd"不等于"零依赖"。

## 历史

`tools/pyocd/0.1.3/`（RT-Thread 打包的 PyInstaller 单文件 `pyocd.exe`，实际版本 0.27）已删除：它认不到 CMSIS-DAP **v2**（WinUSB/bulk）探针，`list` 恒为空，留着只会误导。仓内只保留它的两个 pack 文件（上移到 `packs/`）。
