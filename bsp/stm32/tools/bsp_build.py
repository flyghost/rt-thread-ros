"""构建逻辑（唯一实现）：各板/各项目的 ``SConstruct`` 只保留 20 行左右的 SCons 骨架。

职责边界：
  * 本模块负责**纯计算**：加载 ``rtconfig.py``、解析并校验所有路径、创建 SCons Environment；
  * ``SConstruct`` 负责 SCons 上下文语句：``Export`` / ``PrepareBuilding`` / ``SConscript`` / ``DoBuilding``
    （这些语句依赖调用方的全局命名空间，放在模块函数里会失效）。

路径来源（P1 契约，见 ``bsp_paths.py``）：
  project_root   ← 向上找 ``.git``/``AGENTS.md``（或环境变量 ``PROJECT_ROOT`` 覆盖）
  rtt_root       ← ``<project_root>/os/rt-thread``（或环境变量 ``RTT_ROOT`` 覆盖）
  libraries_dir  ← ``<board_dir>/../libraries``
  app_root       ← ``<project_root>/app``
  build_dir      ← ``<project_root>/out/build/<入口目录名>``（或环境变量 ``RT_BUILD_DIR`` 覆盖）
"""

import os
import sys

import bsp_paths


def load_project(project_dir):
    """读取 ``project.toml``（单一事实来源），返回 ``[project]`` 段。"""
    import tomllib

    path = os.path.join(os.path.abspath(project_dir), 'project.toml')
    if not os.path.isfile(path):
        raise bsp_paths.BspPathError('项目目录缺少 project.toml：%s' % path)
    with open(path, 'rb') as fp:
        data = tomllib.load(fp)
    meta = data.get('project') or {}
    if not meta.get('board'):
        raise bsp_paths.BspPathError(
            '%s 缺少 [project].board（必须写明用哪块板，例：board = "stm32f407-atk-explorer"）' % path)
    return meta


def load_rtconfig(entry_dir, artifact_dir=None):
    """按文件路径加载入口目录的 ``rtconfig.py``（不依赖 sys.path / cwd）。

    * 注入 ``RT_ARTIFACT_DIR``：rtconfig 据此把 map/bin 写到 ``out/bin/<入口名>/``；
    * 期间关闭字节码缓存：否则 import 会在入口目录留下 ``__pycache__/rtconfig.*.pyc``。
    """
    import importlib.util

    path = os.path.join(os.path.abspath(entry_dir), 'rtconfig.py')
    if not os.path.isfile(path):
        raise bsp_paths.BspPathError('入口目录缺少 rtconfig.py：%s' % path)
    name = 'rtconfig_%d' % (abs(hash(path)) % 100000)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    if artifact_dir:
        module.__dict__['RT_ARTIFACT_DIR'] = os.path.abspath(artifact_dir)
    old_flag = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = old_flag
    return module


def resolve_paths(entry_dir, project_root, stm32_library, board_dir=None):
    """解析并校验全部路径；任何一项不满足都抛 :class:`bsp_paths.BspPathError`。"""
    entry_dir = os.path.abspath(entry_dir)
    project_root = os.path.abspath(project_root)
    board_dir = os.path.abspath(board_dir or entry_dir)

    # 1) RT-Thread 内核树
    rtt_root = os.getenv('RTT_ROOT') or os.path.join(project_root, 'os', 'rt-thread')
    bsp_paths.require('RT-Thread 根目录', rtt_root,
                      ['include/rtthread.h', 'tools/building.py'])

    # 2) HAL 库目录（板目录的上一级 libraries）
    libraries_dir = os.path.join(os.path.dirname(board_dir), 'libraries')
    if not stm32_library:
        raise bsp_paths.BspPathError(
            'rtconfig.py 未声明 STM32_LIBRARY（例：STM32_LIBRARY = \'STM32F4xx_HAL\'）')
    bsp_paths.require('HAL 库目录', libraries_dir,
                      [stm32_library + '/SConscript', 'HAL_Drivers/SConscript'])

    # 3) app 源码目录
    app_root = os.getenv('APP_ROOT') or os.path.join(project_root, 'app')
    bsp_paths.require('app 源码目录', app_root, ['SConscript'])

    # 4) 中间文件目录（默认出树到 out/build/<入口名>）
    build_dir = os.getenv('RT_BUILD_DIR')
    if build_dir:
        build_dir = os.path.abspath(os.path.join(entry_dir, build_dir))
    else:
        build_dir = bsp_paths.build_root(entry_dir, project_root)
    build_dir_rel = os.path.relpath(build_dir, entry_dir)

    artifact_dir = os.getenv('RT_ARTIFACT_DIR') or bsp_paths.artifact_dir(entry_dir, project_root)
    artifact_dir = os.path.abspath(artifact_dir)
    os.makedirs(artifact_dir, exist_ok=True)

    return {
        'entry_dir': entry_dir,
        'artifact_dir': artifact_dir,
        'board_dir': board_dir,
        'project_root': project_root,
        'rtt_root': rtt_root,
        'libraries_dir': libraries_dir,
        'app_root': app_root,
        'stm32_library': stm32_library,
        'build_dir': build_dir,
        'build_dir_rel': build_dir_rel,
    }


def make_env(rtconfig):
    """创建 SCons Environment（与旧 SConstruct 逐项等价）。"""
    from SCons.Script import DefaultEnvironment, Environment

    DefaultEnvironment(tools=[])
    env = Environment(tools=['mingw'],
                      AS=rtconfig.AS, ASFLAGS=rtconfig.AFLAGS,
                      CC=rtconfig.CC, CFLAGS=rtconfig.CFLAGS,
                      AR=rtconfig.AR, ARFLAGS='-rc',
                      CXX=rtconfig.CXX, CXXFLAGS=rtconfig.CXXFLAGS,
                      LINK=rtconfig.LINK, LINKFLAGS=rtconfig.LFLAGS)
    env.PrependENVPath('PATH', rtconfig.EXEC_PATH)

    if rtconfig.PLATFORM in ['iccarm']:
        env.Replace(CCCOM=['$CC $CFLAGS $CPPFLAGS $_CPPDEFFLAGS $_CPPINCFLAGS -o $TARGET $SOURCES'])
        env.Replace(ARFLAGS=[''])
        env.Replace(LINKCOM=env['LINKCOM'] + ' --map rt-thread.map')

    return env
