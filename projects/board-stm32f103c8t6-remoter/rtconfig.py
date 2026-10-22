# 项目级 rtconfig：**继承板级配置**，只覆盖"项目特有"的部分。
# 注意：本文件被 SCons 直接 exec（不参与固件编译），必须保持可读、可用内置库。
import importlib.util
import os
import re
import tomllib

_HERE = os.path.dirname(os.path.abspath(__file__))


def _repo_root():
    root = os.environ.get('PROJECT_ROOT')
    if root:
        return root
    d = _HERE
    while True:
        if os.path.exists(os.path.join(d, '.git')) or os.path.exists(os.path.join(d, 'AGENTS.md')):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            raise RuntimeError('无法定位仓库根目录：请设置 PROJECT_ROOT 环境变量')
        d = parent


with open(os.path.join(_HERE, 'project.toml'), 'rb') as _fp:
    _META = tomllib.load(_fp)['project']

# 板级配置的物理位置，由 project.toml 的 board 字段决定
BOARD_DIR = os.path.join(_repo_root(), 'bsp', 'stm32', _META['board'])
_spec = importlib.util.spec_from_file_location(
    'board_rtconfig', os.path.join(BOARD_DIR, 'rtconfig.py'))
_board = importlib.util.module_from_spec(_spec)
# 把产物目录也告诉板级 rtconfig：它负责把 map/bin 从 cwd 指到 out/bin/<入口名>/
_board.__dict__['RT_ARTIFACT_DIR'] = os.path.join(
    _repo_root(), 'out', 'bin', os.path.basename(_HERE))
_spec.loader.exec_module(_board)

# 透传板级全部配置（CROSS_TOOL / PLATFORM / CC / CFLAGS / LFLAGS / TARGET_EXT / BUILD ...）
for _name in dir(_board):
    if not _name.startswith('__'):
        globals()[_name] = getattr(_board, _name)

# 链接脚本必须绝对化：链接阶段的 cwd 是项目目录，板级的相对路径
# “board/linker_scripts/link.lds” 在这里并不存在。
_LDS = os.path.join(BOARD_DIR, 'board', 'linker_scripts', 'link.lds').replace('\\', '/')
LFLAGS = re.sub(r'-T\s+\S*board[/\\]linker_scripts[/\\]link\.lds', '-T ' + _LDS, LFLAGS)

# 产物目录的 map/bin 改写由板级 rtconfig 完成（上面已注入 RT_ARTIFACT_DIR）。
