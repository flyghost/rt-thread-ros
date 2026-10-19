# AGENTS.md — 现代 Python 工程规范（通用模板）

> 本文档描述**一个现代化 Python 项目应该长什么样**：工具链、目录骨架、编码与注释规范、测试与 CI。
> 它**不包含任何特定项目的路径、模块名或业务名词**，可以直接复制到任意 Python 工程的根目录作为 `AGENTS.md` 使用。
> 若所在仓库已有更具体的规范文件，以更具体的为准，并在冲突处明确指出差异。
>
> 一句话：**格式交给工具，语义交给人，边界交给类型，正确性交给测试。**

---

## 0. 结论速览

| 关注点 | 当前主流答案 | 不要这样做 |
|---|---|---|
| 依赖与虚拟环境 | `uv`（`uv sync` / `uv run` / `uv.lock`） | 手工建 `venv`、再维护一份 `requirements.txt` |
| 格式化 + lint | `ruff`（format + check 一套工具完成） | flake8、isort、black、pylint 四件套分别维护 |
| 类型检查 | `mypy`（或 `ty`、`basedpyright`），CI 中运行 | 类型只写在注释里，运行时才发现错 |
| 测试 | `pytest` + `coverage` | 手写 `unittest` 样板类 |
| 提交前检查 | `pre-commit`，只检查改动的文件 | 依赖人记住 |
| 项目配置 | **只放 `pyproject.toml`**（PEP 621） | `setup.py`、`setup.cfg`、`tox.ini`、`.flake8` 四处分散 |
| 构建与版本 | `hatchling` 或 `uv build`，版本单一来源 | 手改 `__version__` 与 git tag 不同步 |
| 依赖审计 | `pip-audit` / `uv pip audit` | 从不检查依赖漏洞 |

---

## 1. 项目骨架（推荐形态）

```
<project>/
├── pyproject.toml          # 唯一配置：元数据 + 依赖 + ruff + mypy + pytest
├── uv.lock                 # 锁定文件，必须入库
├── .python-version         # 例如 3.12，工具链自动读取
├── .editorconfig           # 缩进/编码/行尾，给未配置 ruff 的编辑器兜底
├── .gitignore
├── .pre-commit-config.yaml
├── README.md
├── src/
│   └── <package>/
│       ├── __init__.py     # 只做导出，不写逻辑
│       ├── cli.py          # 入口：解析参数 → 调业务 → 返回退出码
│       ├── core.py         # 业务逻辑，可被测试直接 import
│       └── io.py           # 外部边界：文件、网络、进程
├── tests/
│   ├── conftest.py
│   └── test_core.py
└── .github/workflows/ci.yml
```

**为什么用 `src/` 布局**：避免“当前目录恰好可 import”掩盖打包错误；测试必须经由安装后的包运行，测到的才是使用者拿到的东西。

> 单文件脚本（少于约 300 行、无第三方依赖）不必强行套 `src/`，但**必须**有 `if __name__ == "__main__": sys.exit(main())`、类型标注和模块 docstring。

---

## 2. `pyproject.toml`：一份配置管全部

```toml
[project]
name = "myproject"
version = "0.1.0"                     # 也可用 dynamic = ["version"]
description = "一句话说明这个包做什么"
readme = "README.md"
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = [
    "httpx>=0.27,<1",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-cov>=5", "mypy>=1.11", "ruff>=0.7", "pre-commit>=3.8"]

[project.scripts]
myproject = "myproject.cli:main"      # 安装后得到同名命令

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

# ---------------- 格式化 + lint ----------------
[tool.ruff]
line-length = 100                      # PEP 8=79 / Google=80 / Black=88 / 工程界常取 100~120
target-version = "py311"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "UP", "B", "SIM", "C4", "RET", "PTH", "ARG", "RUF"]
ignore = ["E501"]                      # 行长交给 formatter，避免两套规则互相打架

[tool.ruff.lint.isort]
known-first-party = ["myproject"]

[tool.ruff.format]
quote-style = "double"

# ---------------- 类型 ----------------
[tool.mypy]
python_version = "3.11"
strict = true                          # 新项目建议直接开严格模式
warn_unused_ignores = true

# ---------------- 测试 ----------------
[tool.pytest.ini_options]
addopts = "-q --strict-markers"
testpaths = ["tests"]

[tool.coverage.report]
fail_under = 80
```

---

## 3. 日常命令（全部通过 `uv`，不污染全局环境）

```bash
uv sync                 # 按锁文件创建虚拟环境并安装依赖
uv add rich             # 加运行时依赖（同时更新 pyproject 与锁文件）
uv add --dev pytest     # 加开发依赖
uv run pytest -q        # 在项目环境内运行，无需手动 activate
uv run ruff check .     # 只检查
uv run ruff format .    # 只排版
uv run ruff check --fix .
uv run mypy src
uv lock --upgrade       # 升级依赖（改锁文件，不改约束区间）
uv build                # 产出 wheel / sdist
```

**CI 与本地必须执行完全相同的命令**，否则“我这边能过”会长期存在。

---

## 4. 命名与结构

| 对象 | 规则 | 示例 |
|---|---|---|
| 模块/包 | 全小写、简短、可用下划线 | `billing`, `http_client` |
| 类 | `CapWords` | `OrderService`, `RetryPolicy` |
| 函数/变量 | `snake_case` | `load_config`, `build_dir` |
| 常量 | `UPPER_CASE` | `MAX_RETRY`, `DEFAULT_TIMEOUT` |
| 内部实现 | 前缀 `_` | `_normalize_paths`, `_is_alive` |
| 异常类 | 以 `Error` 结尾 | `ConfigError`, `ValidationError` |
| 布尔量 | `is_` / `has_` / `can_` / `should_` | `is_ready`, `has_lock` |
| 应避免 | 单字母 `l`/`O`/`I`；`data`/`info`/`obj`；覆盖内置名 | — |

- `__init__.py` 只做再导出与 `__all__`，不写业务逻辑。
- 公开 API 显式列 `__all__`；私有实现一律 `_` 前缀。
- 一个模块聚焦一个主题；超过约 500 行先考虑拆分，而不是先加注释。
- 循环导入是设计问题，不要用“函数内 import”当常规解法（仅在打破启动期依赖时使用，并写注释说明原因）。

---

## 5. 现代类型标注（写边界，不写噪音）

| 场景 | 写法 |
|---|---|
| 可空 | `str \| None`（PEP 604），不要 `Optional[str]` |
| 容器 | `list[int]` / `dict[str, int]`（PEP 585），不要 `List` / `Dict` |
| 类型别名 | `type UserId = int`（PEP 695，3.12+）；旧版本用 `UserId: TypeAlias = int` |
| 泛型函数/类 | `def first[T](xs: list[T]) -> T:`（3.12+） |
| 结构化字典 | `TypedDict` / `dataclass` / `pydantic.BaseModel`，不要裸 `dict` |
| 可替换实现 | `Protocol`，不要继承具体类 |
| 确实未知 | `object` 而非 `Any`；一旦用 `Any` 必须写注释解释原因 |
| 兼容旧解释器 | 文件首行 `from __future__ import annotations` |

**必须标注**：公开函数签名、可能返回空值的边界、IO 边界、回调参数。
**不必标注**：显然的局部变量（但可以用注解做“意图声明”：`items: list[str] = []`）。

---

## 6. 注释：只写“为什么”

```python
# 反例：复述代码，没有信息量
count += 1          # 计数加一
time.sleep(0.01)    # 等待 10 毫秒

# 正例：解释意图、约束、坑、副作用
count += 1              # 补回本批跳过的记录，否则分页游标会漏数据
time.sleep(0.01)        # 重试前的退避，避免短时间内触发上游限流
chunk = bytearray(4096) # 分块取 4 KiB：一次写出就能发完，也不至于撑爆内存
```

规则：

| 项 | 要求 |
|---|---|
| 块注释 | 与所注释代码同缩进，不顶格 |
| 行内注释 | 与代码至少隔 **2 个空格**；`#` 后一个空格 |
| 语言 | 标识符用英文；注释可用母语；专业术语保留原文，不硬翻 |
| 时效 | 注释与代码不一致比没有注释更危险；改代码必须同步改注释 |
| 不写死代码 | 注释掉的旧代码交给版本控制，最多留一行 `# 移除原因` |
| TODO | `# TODO(负责人): 具体动作（关联 issue）`，不留无主 TODO |
| 不当分区符 | `##### 工具函数 #####` 这类装饰不提供信息，用空行与函数名表达 |

---

## 7. docstring：PEP 257 + Google 风格

```python
"""模块一句话摘要（以句号结尾）。

必要时补充：这个模块负责什么、不负责什么、典型用法。

Example:
    >>> load_config(Path("a.toml"))
    {'name': 'base'}
"""
```

```python
def load_config(path: Path, *, strict: bool = True) -> dict[str, object]:
    """Load a TOML config file.

    Args:
        path: Config file location; it must exist when ``strict`` is true.
        strict: Raise instead of returning defaults when the file is missing.

    Returns:
        Parsed config; keys are the top-level TOML tables.

    Raises:
        FileNotFoundError: If ``strict`` and ``path`` does not exist.
        ValueError: If the TOML content is malformed.
    """
```

硬规则：

- 模块、公开类、公开函数**必须有** docstring；私有函数按复杂度决定。
- 必须使用 `"""` 三双引号。
- 摘要行**命令式 + 句号**（“Return …” 而不是 “Returns …”）。
- 摘要行不要复述签名（`"""f(a, b) -> list"""` 属于反例）。
- 多行时：摘要 → 空行 → 细节；结尾 `"""` 单独一行，与开引号同缩进。
- 写**调用者需要知道的事**：前置条件、副作用、线程/异步语义、复杂度；不写实现流水账。
- 中文 docstring 允许，但 `Args:` / `Returns:` / `Raises:` 等分节标签保留英文，便于工具解析。

---

## 8. 错误处理与退出码

| 规则 | 说明 |
|---|---|
| 禁止裸 `except:` | 至少写 `except Exception`，并重新抛出或记录；吞异常必须写注释说明理由 |
| 异常链 | `raise ConfigError(f"bad {path}") from exc`，保留原始 traceback |
| 自定义异常 | 每个库/工具一组，统一继承自一个基类；调用方按类型分辨 |
| 不用异常控制流程 | 可预期分支用返回值；异常留给“不该发生”的情况 |
| CLI 退出码 | `0` 成功 / `1` 运行时失败 / `2` 用法错误 / `130` 被 Ctrl-C 终止 |
| 错误信息三段 | **做什么失败** + **为什么（原始错误）** + **下一步怎么办**，输出到 stderr |
| 不向用户抛 traceback | 除非开启 `-v`；默认只给结论与定位信息 |

```python
try:
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
except (OSError, tomllib.TOMLDecodeError) as exc:
    raise ConfigError(f"读取配置失败：{path}") from exc
```

---

## 9. CLI 约定

```python
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mytool", description="...")
    ap.add_argument("-v", "--verbose", action="count", default=0)
    ap.add_argument("--json", action="store_true", help="机器可读输出")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_build = sub.add_parser("build", help="...")
    p_build.add_argument("--dry-run", action="store_true")
    ns = ap.parse_args(argv)
    # ... 分发到具体实现 ...
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- **子命令**优于一堆互斥开关；每个子命令看 `--help` 就能用。
- 长任务提供 `--dry-run`；给脚本/CI 提供 `--json`；诊断提供 `-v/--verbose`。
- 幂等：重复执行不产生额外副作用；破坏性动作要显式确认或显式开关。
- 不交互：需要人确认时用参数或环境变量，不用 `input()`（否则 CI 会挂死）。
- 路径参数同时接受相对与绝对，内部统一转 `Path` 并 `resolve()`。
- 退出码由 `main()` 返回值决定；除最外层外不要在函数里直接 `sys.exit()`。

---

## 10. 文件与 IO

```python
from pathlib import Path

text = Path("config.toml").read_text(encoding="utf-8")        # 永远显式指定编码
Path("out").mkdir(parents=True, exist_ok=True)

# 原子写：同目录临时文件 + os.replace（跨盘不原子，因此临时文件必须同目录）
tmp = target.with_suffix(target.suffix + ".tmp")
tmp.write_text(data, encoding="utf-8", newline="\n")
os.replace(tmp, target)
```

- 一律使用 `pathlib.Path`，不用字符串拼路径，不用 `os.chdir()` 改变进程全局状态。
- **显式 `encoding="utf-8"`**（Windows 中文环境默认编码会破坏中文）；写文本时指定 `newline="\n"`，除非确实需要平台换行。
- 不写 BOM（`utf-8-sig` 仅用于读取他人带 BOM 的文件）；文件末尾保留一个换行，行尾不留空白。
- 临时文件写入系统临时目录或专门的构建目录，**不要落进源码树**。
- 大文件流式处理（逐行迭代或分块读取），不要一次性 `read_text()` 读入上百 MB。

---

## 11. 日志与输出

| 场景 | 用什么 |
|---|---|
| 用户需要看到的最终结果 | `print()`（stdout），可用 `--json` 切换机器格式 |
| 诊断、过程信息 | `logging`（stderr），级别 `debug/info/warning/error` |
| 进度、长任务 | 日志 + 状态文件，不刷屏 |

- 库代码**不配置 logging**（不调用 `basicConfig`），只 `logging.getLogger(__name__)`；配置由入口负责。
- 不用 `print` 打调试信息（提交前清干净），也不用 `logging` 打最终结果（会污染 stdout）。
- 日志带关键字段（路径、命令、退出码、耗时）；消息体用延迟格式化（`log.info("%s", x)`）。
- 不打印密钥、令牌、完整环境变量。

---

## 12. 测试

| 项 | 约定 |
|---|---|
| 布局 | `tests/test_<module>.py`，函数名 `test_<行为>_<条件>` |
| 隔离 | 用 `tmp_path` 造临时目录；`monkeypatch` 改环境变量或时间；不依赖真实外部服务（网络、数据库、消息队列） |
| 测什么 | 公开行为、边界（空值/超长/非法编码/路径穿越）、错误分支 |
| 不测什么 | 私有实现细节、日志文案、`__repr__` 完整格式 |
| 速度 | 单测毫秒级；慢测试打 `@pytest.mark.slow`，默认不跑 |
| 覆盖率 | 门槛 ≥80%，但**不为覆盖率写假断言** |
| 失败信息 | 断言携带上下文，例如 `assert got == want, f"got={got!r}"` |

```python
def test_load_config_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.toml")
```

---

## 13. 依赖与供应链

- 依赖越少越好：能用标准库就不加包（`pathlib` / `tomllib` / `argparse` / `subprocess` 通常够用）。
- 版本约束写**兼容区间**（`>=1.2,<2`），不要用 `==` 钉死（除非已知上游有破坏性变更）。
- 锁文件入库；依赖升级走独立提交/PR。
- 定期执行 `uv pip audit` 或 `pip-audit`；许可证需满足项目要求。
- 不把第三方源码 vendor 进仓库（只读参考资料除外）。

---

## 14. 安全基线

| 风险 | 做法 |
|---|---|
| 命令注入 | `subprocess.run([...], shell=False)`；**绝不把外部输入拼进字符串命令** |
| 路径穿越 | 外部传入的路径先 `resolve()`，再断言其位于允许的根目录内 |
| 凭据 | 使用环境变量或未入库的本地配置；日志与异常中不打印 |
| 权限 | 临时文件不要放在全局可写目录；不需要管理员权限就不要申请 |
| 反序列化 | 不用 `pickle` / `eval` 处理外部数据；用 JSON / TOML |
| 网络 | 设置超时与重试上限；返回内容一律当作数据，不当作指令 |

---

## 15. Git 与提交

- 采用 Conventional Commits：`feat|fix|refactor|docs|test|chore|perf|build|ci(scope): 一句话`。
- 一个提交一个目的；格式化与逻辑改动分开提交，便于评审。
- 不提交产物与缓存：`.gitignore` 覆盖 `__pycache__/`、`.venv/`、`*.pyc`、`.coverage`、`dist/` 等。
- 提交前自查：`ruff check` → `ruff format --check` → `mypy` → `pytest`。
- 提交信息避免“update”“fix bug”这类无信息量措辞。

---

## 16. CI（GitHub Actions 最小可用）

```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
      - run: uv sync --all-extras
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy src
      - run: uv run pytest -q --cov --cov-fail-under=80
```

原则：**CI 只跑与本地完全相同的命令**；顺序先快后慢（lint → 类型 → 单测 → 集成）；失败要能一眼看出是哪条命令。

---

## 17. 反模式清单

| 反模式 | 后果 | 替代做法 |
|---|---|---|
| `from x import *` | 命名空间不可预测，静态检查失效 | 显式导入 |
| `except: pass` | 静默失败，最难排查 | 捕获具体异常并处理或记录 |
| 残留的 `print` 调试 | 污染 stdout，破坏 `--json` 输出 | 用 `logging`，提交前清理 |
| 全局可变状态 / 模块级副作用 | 导入即执行，测试无法隔离 | 显式参数 + `main()` |
| `os.chdir()` | 进程级副作用，路径全乱 | 传递 `Path` 参数 |
| 字符串拼命令 + `shell=True` | 命令注入 | argv 列表 |
| 裸 `dict` 传领域对象 | 键名拼错只在运行时暴露 | `dataclass` / `TypedDict` |
| 巨型模块（上千行） | 无人敢改 | 按职责拆分 |
| 注释掉的旧代码 | 噪声与误读 | 交给版本控制 |
| 只写“Returns …”的 docstring | 无信息量 | 写前置条件、副作用、异常 |
| 无锁文件且用 `==` 钉死 | 升级地狱 | 兼容区间 + 锁文件 |

---

## 18. 给 AI 的硬规则

1. **先读后改**：修改前先读现状；不确定的路径或 API 先用检索工具确认，不猜。
2. **一个改动一个目的**：重构与功能不要混在同一次编辑里；格式化单独一步。
3. **不擅自新增依赖**：确有必要时说明“为什么标准库不够”，并写入依赖段。
4. **交付前自检**：`ruff check`、`ruff format --check`、`mypy`（若已配置）、`pytest` 至少跑目标层；退出码为 0 再汇报。
5. **产物不落源码树**：临时文件写入系统临时目录或专用构建/输出目录；必要时设置解释器不写字节码缓存。
6. **文本文件统一 UTF-8 无 BOM、LF 换行**（明确要求 CRLF 的格式除外，例如 Windows 批处理）。
7. **注释用母语、标识符用英文**；专业术语保留原文。
8. **报告要可核对**：改了哪些文件、跑了什么命令、结果如何（数字/退出码），不要只说“已完成”。
9. **不伪造验证**：没跑的测试不说跑了；无法复现的现象标注“未复现/推测”。
10. **具体规范优先**：本文档是通用底线，仓库若有更具体的规范，以更具体的为准，并指出冲突。

---

## 19. 速查

```bash
uv sync                                   # 建环境
uv run ruff check --fix . && uv run ruff format .
uv run mypy src
uv run pytest -q
pre-commit install && pre-commit run --all-files
uv lock --upgrade && uv pip audit         # 依赖升级 + 审计
```

| 想做的事 | 命令或文件 |
|---|---|
| 增加一个命令入口 | `[project.scripts]` + `cli.py:main()` |
| 调整行长 | `[tool.ruff] line-length`（只此一处） |
| 放松某条规则 | `[tool.ruff.lint] ignore = [...]`，并写明原因 |
| 新增模块 | `src/<package>/<module>.py` + `tests/test_<module>.py` |
| 查看可用命令 | `uv run <tool> --help` |

---

## 20. 参考

- [PEP 8 — Style Guide for Python Code](https://peps.python.org/pep-0008/)
- [PEP 257 — Docstring Conventions](https://peps.python.org/pep-0257/)
- [PEP 484 / 585 / 604 / 695 — 类型系统](https://peps.python.org/pep-0695/)
- [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)
- [Ruff formatter（Black 兼容）](https://docs.astral.sh/ruff/formatter/)
- [uv 文档](https://docs.astral.sh/uv/)
- [pytest 文档](https://docs.pytest.org/)
