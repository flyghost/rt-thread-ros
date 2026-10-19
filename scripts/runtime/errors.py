"""错误类型：消息面向使用者，退出码由 CLI 边界统一决定。

原则：
- **异常携带信息，不打印**。打印只发生在 `main()` 的最后一层 catch。
- 退出码稳定（脚本里 `--help` 时代码也会用到），用类属性声明，不要在调用点写魔法数字。
"""

from __future__ import annotations

from typing import NoReturn

# 退出码约定（与习惯一致，便于 CI 判断）
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2
EXIT_ENV = 3


class RtrosError(Exception):
    """所有可预期错误的基类：这类错误应该以「一句人话 + 退出码」收场，而不是抛栈。"""

    exit_code: int = EXIT_FAIL

    def __init__(self, message: str, *, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint

    def render(self) -> str:
        """给使用者看的完整句子（含可选 hint）。"""
        if self.hint:
            return f"{self.message}\n提示：{self.hint}"
        return self.message


class UserError(RtrosError):
    """调用方式/参数错：比如 `--bin` 给了不存在的文件。"""

    exit_code = EXIT_USAGE


class ToolMissingError(RtrosError):
    """环境不满足：缺工具链、缺 pytest、没装依赖包。"""

    exit_code = EXIT_ENV

    def __init__(self, tool: str, *, hint: str = "") -> None:
        super().__init__(f"找不到 {tool}", hint=hint)
        self.tool = tool


class CommandFailed(RtrosError):
    """子进程非 0 退出：把 argv、退出码和 stderr 尾部一起带上，便于定位。"""

    def __init__(self, argv: list[str] | tuple[str, ...], returncode: int, detail: str = "") -> None:
        cmd = " ".join(argv)
        message = f"命令失败（退出码 {returncode}）：{cmd}"
        super().__init__(message, hint=detail.strip()[-2000:] if detail else "")
        self.argv = tuple(argv)
        self.returncode = returncode


def fail(exc: RtrosError) -> NoReturn:
    """CLI 边界用：打印一句人话后按异常自带退出码结束进程。"""
    import sys

    print(f"[错误] {exc.render()}", file=sys.stderr)
    raise SystemExit(exc.exit_code)
