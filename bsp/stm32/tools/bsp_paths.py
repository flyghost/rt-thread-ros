"""显式路径契约：项目根定位 + 标记文件校验（不猜路径、缺了就报错）。

设计约定（与 AGENTS.md「构建接入」一致）：
  * 不写 ``os.getcwd() + '/../../..'`` 这类“数层级”的路径，布局变动即失效；
  * 项目根 = 从调用者目录向上找标记文件（``.git`` / ``AGENTS.md``）；
  * 环境变量 ``PROJECT_ROOT`` / ``RTT_ROOT`` 只做**覆盖**，必须是存在的绝对路径；
  * 每个“根”都必须通过标记文件校验，失败即退出码 1，并打印解析依据。

本文件位于 ``bsp/stm32/tools/``，被以下位置引用：
  * 各板 ``SConstruct``（薄壳，``..`` → 本目录）
  * ``bsp/stm32/tools/bsp_build.py``
  * ``scripts/src/toolbelt/firmware/``（Python 侧算中间文件目录时复用同一套规则）
"""

import os
import sys

# 项目根的标记文件：任一存在即认为到达仓库根
ROOT_MARKERS = ('.git', 'AGENTS.md')


class BspPathError(RuntimeError):
    """路径契约不满足（缺声明 / 缺标记文件 / 覆盖值无效）。"""


def find_project_root(start, env_name='PROJECT_ROOT'):
    """从 ``start`` 向上定位项目根。

    优先级：环境变量 ``PROJECT_ROOT`` → 向上找 ``ROOT_MARKERS`` → 报错。
    """
    override = os.getenv(env_name)
    if override:
        root = os.path.abspath(override)
        if not os.path.isdir(root):
            raise BspPathError(
                '环境变量 %s 指向的目录不存在：%s\n'
                '        环境变量只做覆盖，必须是存在的绝对路径' % (env_name, root))
        return root

    current = os.path.abspath(start)
    while True:
        for marker in ROOT_MARKERS:
            if os.path.exists(os.path.join(current, marker)):
                return current
        parent = os.path.dirname(current)
        if parent == current:
            raise BspPathError(
                '找不到项目根：从 %s 向上既没有 %s\n'
                '        仓库根应包含 %s 之一；也可设置环境变量 %s=<绝对路径>'
                % (start, ' 也没有 '.join(ROOT_MARKERS),
                   ' 或 '.join(ROOT_MARKERS), env_name))
        current = parent


def require(tag, root, markers):
    """校验 ``root`` 下 ``markers`` 全部存在，否则抛 :class:`BspPathError`。"""
    missing = [m for m in markers if not os.path.exists(os.path.join(root, m))]
    if missing:
        raise BspPathError(
            '找不到%s：%s\n'
            '        缺少标记文件：%s' % (tag, root, ', '.join(missing)))
    return root


def fail(exc, where=''):
    """统一报错出口：打印上下文并以退出码 1 结束（构建脚本顶层调用）。"""
    lines = ['', '[build] %s' % exc]
    if where:
        lines.append('        调用位置：%s' % where)
    lines.append('')
    sys.stderr.write('\n'.join(lines) + '\n')
    sys.exit(1)


def artifact_dir(entry_dir, project_root=None):
    """返回 ``out/bin/<entry 目录名>`` 的绝对路径（产物 elf/map/bin 都放这里）。"""
    root = project_root or find_project_root(entry_dir)
    name = os.path.basename(os.path.abspath(entry_dir).rstrip('\\/'))
    return os.path.join(root, 'out', 'bin', name)


def build_root(entry_dir, project_root=None):
    """返回 ``out/build/<entry 目录名>`` 的绝对路径（没有就返回默认值，不创建）。"""
    root = project_root or find_project_root(entry_dir)
    name = os.path.basename(os.path.abspath(entry_dir).rstrip('\\/'))
    return os.path.join(root, 'out', 'build', name)
