@echo off
REM ============================================================
REM Thin wrapper for the ramdump toolchain. All logic lives in python
REM entry points under build/ dump/ test/ analyzer/.
REM Usage: ramdump.bat <subcommand> [args...]
REM   build       compile (supports --flash / --clean / --menuconfig)
REM   flash       flash the existing rtthread.bin only
REM   clean       remove build artifacts
REM   menuconfig  open the Kconfig menu
REM   dump        full flow: build -> flash -> trigger -> YMODEM receive
REM   recv        receive only (device already running)
REM   list        list serial ports
REM   probe       probe the console (MSH / @ramdump>)
REM   loopback    USB VCOM loopback test
REM   analyzer    analyze a dump under out/dump/<timestamp>/
REM   hub         serial hub (replaces the old console loop)
REM ============================================================
setlocal enabledelayedexpansion
set "SCRIPT_DIR=%~dp0"
REM Keep Python bytecode cache under <repo>\out\pycache (no __pycache__ in the source tree)
if not defined PYTHONPYCACHEPREFIX (
    for %%I in ("%SCRIPT_DIR%..\..") do set "PYTHONPYCACHEPREFIX=%%~fI\out\pycache"
)
set "PY=python"
"%PY%" --version >nul 2>nul || (echo [ERROR] python not found in PATH & exit /b 1)
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
echo [ERROR] unknown subcommand: %SUB%
:usage
echo Usage: ramdump.bat [build^|flash^|clean^|menuconfig^|dump^|recv^|list^|probe^|loopback^|analyzer^|hub] [args]
echo Example:
echo   ramdump.bat build --flash
echo   ramdump.bat dump --com COM46 --skip-build --region sram
echo   ramdump.bat recv --com COM46
echo   ramdump.bat hub --com COM46 --ui tui
exit /b 2
