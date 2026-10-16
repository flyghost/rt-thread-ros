@echo off
REM ============================================================
REM ramdump 工具的薄包装 —— 实现全在 build/ dump/ test/ 下的 python 入口。
REM 用法： ramdump.bat ^<子命令^> [参数]
REM   build      编译（可加 --flash / --clean / --menuconfig / --new-console）
REM   flash      只下载现有的 rtthread.bin
REM   clean      清理产物
REM   menuconfig 配置
REM   dump       全流程：编译 -> 下载 -> 触发 -> YMODEM 收
REM   recv       只收（设备已在跑）
REM   list       列出串口
REM   probe      探控制台（MSH / @ramdump>）
REM   loopback   USB VCOM 回环测试
REM   analyzer   解析 out/dump/<时间>/ 下的 dump
REM   hub        串口中枢（取代原来 bat 里的 console 死循环）
REM ============================================================
setlocal enabledelayedexpansion
set "SCRIPT_DIR=%~dp0"
REM Keep Python bytecode cache under <repo>\out\pycache (no __pycache__ in the source tree)
if not defined PYTHONPYCACHEPREFIX (
    for %%I in ("%SCRIPT_DIR%..\..") do set "PYTHONPYCACHEPREFIX=%%~fI\out\pycache"
)
set "PY=python"
"%PY%" --version >nul 2>nul || (echo [ERROR] PATH 里没有 python & exit /b 1)
if "%~1"=="" goto :usage
set "SUB=%~1"
shift
set "ARGS="
:collect
if "%~1"=="" goto :dispatch
set "ARGS=!ARGS! %1"
shift
goto :collect
:dispatch
if /i "%SUB%"=="build"      ( "%PY%" "%SCRIPT_DIR%build\build.py" !ARGS! & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="flash"      ( "%PY%" "%SCRIPT_DIR%build\build.py" --flash-only !ARGS! & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="clean"      ( "%PY%" "%SCRIPT_DIR%build\build.py" --clean !ARGS! & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="menuconfig" ( "%PY%" "%SCRIPT_DIR%build\build.py" --menuconfig !ARGS! & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="dump"       ( "%PY%" "%SCRIPT_DIR%dump\dump.py" !ARGS! & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="recv"       ( "%PY%" "%SCRIPT_DIR%dump\receive.py" !ARGS! & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="list"       ( "%PY%" "%SCRIPT_DIR%test\test_serial.py" --list & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="probe"      ( "%PY%" "%SCRIPT_DIR%test\test_serial.py" --probe !ARGS! & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="loopback"   ( "%PY%" "%SCRIPT_DIR%test\test_usb_loopback.py" !ARGS! & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="analyzer"   ( "%PY%" "%SCRIPT_DIR%analyzer\ramdump_analyzer.py" !ARGS! & exit /b !ERRORLEVEL! )
if /i "%SUB%"=="hub"        ( "%PY%" "%SCRIPT_DIR%..\serial_hub\serial_hub.py" !ARGS! & exit /b !ERRORLEVEL! )
echo [ERROR] 未知子命令：%SUB%
:usage
echo 用法： ramdump.bat [build^|flash^|clean^|menuconfig^|dump^|recv^|list^|probe^|loopback^|analyzer^|hub] [参数]
echo 例：  ramdump.bat build --flash
echo        ramdump.bat dump --com COM46 --skip-build --region sram
echo        ramdump.bat recv --com COM46
echo        ramdump.bat hub --com COM46 --ui tui
exit /b 2
